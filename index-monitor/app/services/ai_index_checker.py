# index-monitor/app/services/ai_index_checker.py
"""AI 收录检测服务：检测 AI 大模型是否收录了目标 URL。

收录检测在问题监测之前执行（双阶段管道 Phase 1）：
1. 对每个 URL × 模型组合，直接询问 AI 是否了解该 URL
2. 解析响应判定 indexed / not_indexed
3. 存入 ai_index_results 表

仅对 index_status='indexed' 的组合执行问题监测（Phase 2 改造）。
"""
import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Awaitable, Callable, Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.integration.geoflow import GeoflowRepository
from app.models.ai_index_result import AIIndexResult
from app.models.client import ClientSite
from app.models.manual_distribution import ManualDistribution
from app.services.citation_check.providers import adapter_catalog
from app.services.scan_task_manager import update_progress
from app.utils.validators import normalize_domain

logger = logging.getLogger(__name__)

# AI 回复中的否定短语——命中即判定 not_indexed
NEGATIVE_PHRASES = (
    "不了解", "不知道", "无法访问", "没有相关信息",
    "未收录", "不清楚", "不熟悉", "无法获取",
    "我没有关于", "我无法确认", "无法确认其内容",
)


def parse_index_response(response: str) -> str:
    """判定 AI 收录检测响应 → 'indexed' 或 'not_indexed'。

    判定规则：
    1. 空回复 → not_indexed
    2. 以"不了解"开头 → not_indexed
    3. 短回复（<50字）含否定短语 → not_indexed
    4. 长回复含"我没有关于"/"我无法确认" → not_indexed
    5. 其他（AI 提供了实质描述）→ indexed
    """
    text = (response or "").strip()
    if not text:
        return "not_indexed"
    if text.startswith("不了解"):
        return "not_indexed"
    # 短回复含否定短语
    if len(text) < 50 and any(p in text for p in NEGATIVE_PHRASES):
        return "not_indexed"
    # 长回复中的强否定短语
    strong_negatives = ("我没有关于", "我无法确认", "无法确认其内容")
    if any(p in text for p in strong_negatives):
        return "not_indexed"
    return "indexed"


def build_index_prompt(url: str) -> str:
    """构建 AI 收录检测 prompt。"""
    return (
        f"你是否了解这个网页的内容？请直接回答。\n\n"
        f"URL: {url}\n\n"
        f"如果你了解该网页的内容，请用 100 字以内简要描述其主要内容。\n"
        f"如果你不了解，请只回答\"不了解\"。"
    )


class AIIndexChecker:
    """AI 收录检测器：检测 AI 大模型是否收录了目标 URL。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def _get_configured_models() -> list[str]:
        """获取已配置 API Key 的 AI 模型 ID 列表（从 adapter_catalog）。"""
        return [item["id"] for item in adapter_catalog() if item["configured"]]

    async def get_pending_urls(self) -> list[tuple[str, str, str]]:
        """获取待收录检测的 URL × 模型组合（增量）。

        返回 [(url, client_id, model), ...]

        筛选条件：
        1. URL 已分发（manual_distributions status='synced' 或 GEOFlow 分发）
        2. ai_index_results 中无该 URL×model 的终态记录（indexed/not_indexed）；
           pending 状态记录保留以便批量重试（API 失败可重检测）
        """
        models = self._get_configured_models()
        if not models:
            logger.warning("未配置任何 AI 模型 API Key，无待检测组合")
            return []

        # 1. 收集已分发 URL → client_id 映射
        # 手动录入
        manual_result = await self.db.execute(
            select(ManualDistribution.remote_url, ManualDistribution.client_id)
            .where(ManualDistribution.status == "synced")
        )
        distributed: dict[str, str] = {}
        for url, client_id in manual_result.fetchall():
            distributed[url] = client_id

        # GEOFlow 分发（跨 schema）
        try:
            repo = GeoflowRepository(self.db)
            geoflow_urls = await repo.get_synced_distribution_urls()
            sites_result = await self.db.execute(
                select(ClientSite).where(ClientSite.status == "active")
            )
            domain_map = {
                normalize_domain(s.domain): s.client_id
                for s in sites_result.scalars().all()
            }
            for url in geoflow_urls:
                domain = normalize_domain(url)
                client_id = domain_map.get(domain)
                if client_id:
                    distributed.setdefault(url, client_id)
        except Exception as exc:
            logger.warning("GEOFlow 分发查询失败（降级为仅手动录入）: %s", exc)

        if not distributed:
            return []

        # 2. 查已有收录检测记录，排除已终态（indexed/not_indexed）的组合；
        #    pending 状态保留以便批量重试（API 失败可重检测）
        existing_result = await self.db.execute(
            select(AIIndexResult.url, AIIndexResult.model).where(
                AIIndexResult.index_status.in_(["indexed", "not_indexed"])
            )
        )
        existing = {(row[0], row[1]) for row in existing_result.fetchall()}

        # 3. 生成 pending 组合
        pending: list[tuple[str, str, str]] = []
        for url, client_id in distributed.items():
            for model in models:
                if (url, model) not in existing:
                    pending.append((url, client_id, model))

        return pending

    def _build_adapter(self, model: str):
        """构建单个模型的 adapter（复用现有 providers.default_adapters）。

        收录检测禁用 web_search：测的是训练数据是否收录，非实时检索能力。
        """
        from app.services.citation_check.providers import default_adapters
        adapters = default_adapters([model])
        if not adapters:
            raise ValueError(f"模型 {model} 未配置 API Key 或不支持")
        return adapters[0]

    async def check_url(
        self,
        url: str,
        model: str,
        *,
        task_id: Optional[str] = None,
        progress: Optional[Callable[..., Awaitable[None]]] = None,
    ) -> dict:
        """检测单个 URL 在单个模型上的收录状态。

        Returns:
            {"url", "model", "index_status", "ai_response", "error"}
            - index_status: 'indexed' / 'not_indexed' / 'pending'（API 失败时）
        """
        prompt = build_index_prompt(url)

        async def _report(stage, status, message, **kw):
            if progress:
                try:
                    await progress(stage, status, message, **kw)
                except Exception:
                    pass

        await _report("收录检测", "start", f"开始检测 {model} 是否收录: {url}")
        t0 = time.time()

        try:
            adapter = self._build_adapter(model)
            # adapter.ask 是同步调用，用 to_thread 包装
            answer = await asyncio.to_thread(adapter.ask, prompt)
            response_text = getattr(answer, "text", "") or ""

            index_status = parse_index_response(response_text)

            # 存储结果（幂等：UNIQUE(url, model)）
            await self._store_result(url, model, index_status, response_text)

            await _report(
                "收录检测", "success",
                f"{model} → {index_status}",
                model=model,
                duration_ms=int((time.time() - t0) * 1000),
            )

            return {
                "url": url,
                "model": model,
                "index_status": index_status,
                "ai_response": response_text,
                "error": None,
            }

        except Exception as exc:
            logger.error("收录检测失败 %s [%s]: %s", url, model, exc)
            # API 失败时存储 pending 状态（可重试），区分于 not_indexed
            await self._store_result(url, model, "pending", str(exc))

            await _report(
                "收录检测", "error",
                f"{model} 检测失败: {exc}",
                model=model,
                duration_ms=int((time.time() - t0) * 1000),
            )

            return {
                "url": url,
                "model": model,
                "index_status": "pending",
                "ai_response": None,
                "error": str(exc),
            }

    async def _store_result(
        self, url: str, model: str, index_status: str, ai_response: str
    ) -> None:
        """存储收录检测结果（幂等：UNIQUE(url, model)）。

        使用 PostgreSQL ``INSERT ... ON CONFLICT (url, model) DO UPDATE`` 原子
        upsert，避免并发下 select-then-insert 导致 UNIQUE 约束冲突。
        """
        stmt = pg_insert(AIIndexResult).values(
            url=url,
            model=model,
            index_status=index_status,
            ai_response=ai_response,
            checked_at=datetime.now(timezone.utc),
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["url", "model"],
            set_={
                "index_status": stmt.excluded.index_status,
                "ai_response": stmt.excluded.ai_response,
                "checked_at": stmt.excluded.checked_at,
            },
        )
        await self.db.execute(stmt)
        await self.db.commit()

    async def check_all_pending(
        self, *, task_id: Optional[str] = None, concurrency: int = 3
    ) -> dict:
        """批量检测所有待检测的 URL×模型组合（增量）。

        并发执行，单条失败不影响其他。

        Returns:
            {"total", "success", "failed", "failures"}
            failures 项：{"url", "model", "error"}
        """
        pending = await self.get_pending_urls()
        total = len(pending)
        if total == 0:
            return {"total": 0, "success": 0, "failed": 0, "failures": []}

        if task_id:
            try:
                update_progress(task_id, total=total)
            except Exception as exc:  # noqa: BLE001
                logger.warning("update_progress(total) 失败（已忽略）: %s", exc)

        from app.core.database import async_session
        semaphore = asyncio.Semaphore(max(1, concurrency))
        results: list[dict] = []
        processed = 0

        async def _check_one(url: str, client_id: str, model: str) -> None:
            nonlocal processed
            async with semaphore:
                # 独立 session：AsyncSession 并发不安全
                async with async_session() as task_db:
                    checker = AIIndexChecker(task_db)
                    try:
                        await checker.check_url(url, model, task_id=task_id)
                        results.append({"ok": True, "url": url, "model": model})
                    except Exception as exc:  # noqa: BLE001
                        logger.error("收录检测失败 %s [%s]: %s", url, model, exc)
                        results.append({
                            "ok": False, "url": url, "model": model, "error": str(exc),
                        })
                processed += 1
                if task_id:
                    try:
                        update_progress(
                            task_id,
                            processed=processed,
                            success=sum(1 for r in results if r["ok"]),
                            failed=sum(1 for r in results if not r["ok"]),
                        )
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("update_progress 失败（已忽略）: %s", exc)

        await asyncio.gather(
            *[_check_one(url, cid, model) for url, cid, model in pending]
        )

        success = sum(1 for r in results if r["ok"])
        failures = [
            {"url": r["url"], "model": r["model"], "error": r["error"]}
            for r in results if not r["ok"]
        ]

        return {
            "total": total,
            "success": success,
            "failed": len(failures),
            "failures": failures,
        }
