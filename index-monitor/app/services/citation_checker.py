# index-monitor/app/services/citation_checker.py
"""AI 采信检测服务：封装 lumora-cite 完整检测流程（3 阶段）。

流程：
1. 准备：抓取公开内容、加载客户活跃监测问题、配置引用检测模型
2. 模型探测：探测所选模型联网能力（probe_adapter_capabilities）
3. 引用检测：执行 run_citation_check 并存储结果

所有 lumora-cite 同步调用通过 asyncio.to_thread() 包装，不阻塞事件循环。

稳定性增强：
- selected_ids 含已下线 id 时过滤并告警
- 每步骤失败时异常带阶段标签 [N/3 阶段名]，便于批量失败诊断
- check_all_pending 的 failures 项含 {url, stage, error} 结构
- on_config_changed() 清探测缓存，供配置变更后调用
"""
import asyncio
import logging
import os
import re
import time
from typing import Awaitable, Callable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integration.geoflow import GeoflowRepository
from app.models.manual_distribution import ManualDistribution
from app.models.citation_result import CitationResult
from app.models.citation_check_log import CitationCheckLog
from app.models.index_result import IndexResult
from app.models.client import ClientSite
from app.utils.validators import normalize_domain
# 阶段 2 - ④b：progress 回调默认实现复用 scan_task_manager.add_log（sync，线程安全）
# 阶段 4 - ⑤：复用 update_citation_model 结构化存储模型 probe 状态
# 阶段 4 - ⑤：复用 update_progress 推进活动窗口进度计数（processed/success/failed）
from app.services.scan_task_manager import add_log, update_citation_model, update_progress
from app.services.llm_client import load_ai_configs
from app.services.citation_check import run_citation_check
from app.services.citation_check.engine import probe_adapter_capabilities
from app.services.citation_check.engine import invalidate_probe_cache
from app.services.citation_check.fetcher import fetch_public_content
from app.services.citation_check.providers import default_adapters, adapter_catalog

logger = logging.getLogger(__name__)

# system_config 中所有 AI 相关配置 key
AI_CONFIG_KEYS = [
    "ai_deepseek_api_key",
    "ai_dashscope_api_key",
    "ai_ark_api_key",
    "ai_baidu_api_key",
    "ai_openai_api_key",
    "ai_gemini_api_key",
    "ai_anthropic_api_key",
    "ai_citation_models",
]

# system_config key → lumora-cite providers.py 读取的环境变量名
_PROVIDER_ENV_MAP = {
    "ai_dashscope_api_key": "DASHSCOPE_API_KEY",
    "ai_ark_api_key": "ARK_API_KEY",
    "ai_baidu_api_key": "BAIDU_API_KEY",
    "ai_openai_api_key": "OPENAI_API_KEY",
    "ai_gemini_api_key": "GEMINI_API_KEY",
    "ai_anthropic_api_key": "ANTHROPIC_API_KEY",
}

# 阶段标签正则：[1/3 准备] [2/3 模型探测] [3/3 引用检测]
_STAGE_LABEL_RE = re.compile(r"^\[(\d+/\d+\s+[^\]]+)\]")

# 3 个阶段名（与 check_url 步骤对应）
_STAGES = {
    1: "1/3 准备",
    2: "2/3 模型探测",
    3: "3/3 引用检测",
}


def _extract_stage(message: str) -> str:
    """从异常消息中提取 [N/3 阶段名] 前缀，无标签返回 'unknown'。"""
    match = _STAGE_LABEL_RE.match(str(message or ""))
    return match.group(1) if match else "unknown"


def _wrap_with_stage(stage_num: int, exc: Exception) -> ValueError:
    """把异常包装成带阶段标签的 ValueError。"""
    stage = _STAGES.get(stage_num, f"{stage_num}/3 未知阶段")
    original = str(exc)
    # 避免重复包装（异常本身已含阶段标签时不再叠加）
    if _STAGE_LABEL_RE.match(original):
        return ValueError(original)
    return ValueError(f"[{stage}] {original}")


class CitationChecker:
    """AI 采信检测器，封装 lumora-cite 完整流程。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ------------------------------------------------------------------
    # 待检测 URL 获取
    # ------------------------------------------------------------------

    async def get_pending_urls(self) -> list[tuple[str, str]]:
        """获取待检测采信的 URL 列表（增量 + 4 条件 pending + 优先级）。

        4 条件全满足才 pending：
        1. URL 已分发（manual_distributions 或 GEOFlow，status='synced'）
        2. URL 有至少一个已收录模型（ai_index_results.index_status='indexed'）
        3. URL 对应客户有活跃监测问题（client_questions.status='active'）
        4. URL 尚无 citation_results 记录（增量）

        返回 [(remote_url, client_id), ...]。

        优先级：按 IndexResult.created_at DESC 排序，新文章优先检测。
        已收录文章更可能被 AI 引用，优先做采信检测；未收录文章（无 IndexResult，
        created_at 为 NULL）排末尾。
        """
        # Phase 3 修复（I3）：GEOFlow 查询加 try/except 降级，与
        # AIIndexChecker.get_pending_urls 对齐。GEOFlow schema 表缺失或短暂不可用时
        # 降级为仅返回手动录入 URL，而非抛异常导致 citation 检测完全瘫痪。
        # 注意：asyncpg 查询失败会把事务置为 aborted 状态，后续 SQL 全报
        # "current transaction is aborted"，必须 rollback 才能继续用此 session。
        manual_result = await self.db.execute(
            select(ManualDistribution.remote_url, ManualDistribution.client_id)
            .where(ManualDistribution.status == "synced")
        )
        distributed: dict[str, str] = {}
        for url, client_id in manual_result.fetchall():
            distributed[url] = client_id

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
            # asyncpg 在查询失败后会把当前事务置为 aborted 状态，后续 SQL 全部报
            # "current transaction is aborted" —— 必须 rollback 才能继续用此 session。
            await self.db.rollback()
            logger.warning("GEOFlow 分发查询失败（降级为仅手动录入）: %s", exc)

        if not distributed:
            return []

        # 条件 2: 有已收录模型的 URL 集合
        from app.models.ai_index_result import AIIndexResult
        indexed_result = await self.db.execute(
            select(AIIndexResult.url).where(AIIndexResult.index_status == "indexed")
        )
        indexed_urls = {row[0] for row in indexed_result.fetchall()}

        # 条件 3: 有活跃监测问题的 client_id 集合
        from app.models.client_question import ClientQuestion
        active_clients_result = await self.db.execute(
            select(ClientQuestion.client_id).where(ClientQuestion.status == "active")
        )
        active_clients = {row[0] for row in active_clients_result.fetchall()}

        # 条件 4: 无 citation_results 记录的 URL 集合（增量）
        checked_result = await self.db.execute(select(CitationResult.url))
        checked_urls = {row[0] for row in checked_result.fetchall()}

        # 4 条件过滤：synced（已在 distributed）+ indexed + 客户有 active 问题 + 增量
        pending = [
            (url, client_id)
            for url, client_id in distributed.items()
            if url in indexed_urls  # 条件 2
            and client_id in active_clients  # 条件 3
            and url not in checked_urls  # 条件 4
        ]
        if not pending:
            return []

        # 优先级：按 IndexResult.created_at DESC（新文章优先）；未收录文章排末尾。
        # 一次 IN 查询拿到所有待检测 URL 的首次收录时间，避免 N 次查询。
        pending_urls = [url for url, _ in pending]
        idx_result = await self.db.execute(
            select(IndexResult.url, IndexResult.created_at)
            .where(IndexResult.url.in_(pending_urls))
        )
        created_at_map = {row[0]: row[1] for row in idx_result.fetchall()}

        with_ts: list[tuple[object, str, str]] = []
        without_ts: list[tuple[str, str]] = []
        for url, cid in pending:
            ts = created_at_map.get(url)
            if ts is None:
                without_ts.append((url, cid))
            else:
                with_ts.append((ts, url, cid))
        # created_at 降序：新文章（ts 大）排前
        with_ts.sort(key=lambda x: x[0], reverse=True)
        return [(url, cid) for _, url, cid in with_ts] + without_ts

    # ------------------------------------------------------------------
    # 配置加载
    # ------------------------------------------------------------------

    async def _load_ai_config(self) -> dict[str, str]:
        """从 DB 加载所有 AI 配置。"""
        return await load_ai_configs(self.db, AI_CONFIG_KEYS)

    def _set_provider_env(self, config: dict[str, str]) -> None:
        """将 DB 中的 API Key 设置到环境变量，供 lumora-cite providers.py 读取。

        lumora-cite 的 providers.py 通过 os.getenv() 读取各平台 API Key，
        因此在调用 default_adapters() 前需要将 DB 中的值写入 os.environ。
        """
        for config_key, env_key in _PROVIDER_ENV_MAP.items():
            value = config.get(config_key, "")
            if value:
                os.environ[env_key] = value

    # ------------------------------------------------------------------
    # Phase 2 辅助方法
    # ------------------------------------------------------------------

    async def _get_client_questions(self, client_id: str) -> list[str]:
        """获取客户的活跃监测问题，按 sort_order 排序。

        替代 Phase 1 的 LLM 自动生成问题。
        """
        from app.models.client_question import ClientQuestion
        result = await self.db.execute(
            select(ClientQuestion.question)
            .where(
                ClientQuestion.client_id == client_id,
                ClientQuestion.status == "active",
            )
            .order_by(ClientQuestion.sort_order)
        )
        return [row[0] for row in result.fetchall()]

    async def _get_indexed_models(self, url: str) -> list[str]:
        """从 ai_index_results 取该 URL 已收录的模型列表。

        仅 index_status='indexed' 的模型才执行问题监测。
        """
        from app.models.ai_index_result import AIIndexResult
        result = await self.db.execute(
            select(AIIndexResult.model)
            .where(
                AIIndexResult.url == url,
                AIIndexResult.index_status == "indexed",
            )
        )
        return [row[0] for row in result.fetchall()]

    # ------------------------------------------------------------------
    # 单 URL 检测
    # ------------------------------------------------------------------

    async def check_url(
        self,
        url: str,
        client_id: str,
        *,
        task_id: Optional[str] = None,
        progress: Optional[Callable[..., Awaitable[None]]] = None,
    ) -> dict:
        """对单个 URL 执行 AI 采信检测（3 阶段）。

        阶段：
        1/3 准备：抓取内容 + 加载客户问题 + 筛选已收录模型
        2/3 模型探测：对已收录模型探测联网能力
        3/3 引用检测：用客户问题对已收录模型执行引用检测

        每步骤失败时抛带阶段标签 [N/3 阶段名] 的 ValueError。
        """
        if progress is None:
            progress = self._make_default_progress(task_id, url)

        async def _report(stage: str, status: str, message: str, **kw) -> None:
            try:
                await progress(stage, status, message, **kw)
            except Exception as cb_exc:  # noqa: BLE001
                logger.warning("progress 回调异常（已忽略）: %s", cb_exc)

        config = await self._load_ai_config()

        # ──────── 1/3 准备 ────────
        # 1a. 抓取内容
        await _report("1/3 准备", "start", f"开始抓取内容: {url}")
        t0 = time.time()
        logger.info("采信检测 [1/3] 抓取内容: %s", url)
        try:
            content = await asyncio.to_thread(fetch_public_content, url)
            if not content.suitability.suitable:
                raise ValueError(
                    f"内容不适合检测：{content.suitability.rejection_reason}"
                    f"（code={content.suitability.rejection_code}）"
                )
        except Exception as exc:
            await _report("1/3 准备", "error", f"抓取失败: {exc}", duration_ms=int((time.time() - t0) * 1000))
            raise _wrap_with_stage(1, exc) from exc

        title = content.title
        target_urls = [
            u for u in (content.requested_url, content.resolved_url, content.canonical_url)
            if u
        ]

        # 1b. 加载客户问题（替代 LLM 自动生成）
        questions = await self._get_client_questions(client_id)
        if not questions:
            await _report("1/3 准备", "error", f"客户 {client_id} 未配置监测问题")
            raise ValueError(
                f"客户 {client_id} 未配置监测问题。"
                "请在客户管理 → 监测问题中添加问题后重试。"
            )

        # 1c. 筛选已收录模型
        indexed_models = await self._get_indexed_models(url)
        if not indexed_models:
            await _report("1/3 准备", "error", "该 URL 未被任何 AI 模型收录")
            raise ValueError("该 URL 未被任何 AI 模型收录，跳过问题监测")

        await _report(
            "1/3 准备", "success",
            f"准备完成: {len(questions)} 问题, {len(indexed_models)} 已收录模型",
            detail={"title": title, "question_count": len(questions), "indexed_models": indexed_models},
            duration_ms=int((time.time() - t0) * 1000),
        )

        # ──────── 2/3 模型探测 ────────
        await _report("2/3 模型探测", "start", f"开始探测 {len(indexed_models)} 个模型的联网能力")
        t0 = time.time()
        self._set_provider_env(config)
        # 与配置的 citation_models 取交集
        citation_models_str = config.get("ai_citation_models", "")
        configured_ids = (
            [m.strip() for m in citation_models_str.split(",") if m.strip()]
            if citation_models_str else None
        )
        # catalog 过滤
        catalog_ids = {item["id"] for item in adapter_catalog()}
        selected_ids = [
            mid for mid in indexed_models
            if mid in catalog_ids and (configured_ids is None or mid in configured_ids)
        ]
        if not selected_ids:
            await _report("2/3 模型探测", "error", "已收录模型均未配置 API Key 或不在配置列表中")
            raise ValueError(
                "已收录模型均未配置 API Key 或不在配置列表中。"
                "请在系统设置中配置对应模型的 API Key。"
            )

        try:
            adapters = await asyncio.to_thread(default_adapters, selected_ids)
            if not adapters:
                raise ValueError("未配置任何引用检测模型。")

            capabilities = await asyncio.to_thread(probe_adapter_capabilities, adapters)
            verified_count = sum(1 for item in capabilities if item["status"] == "verified")
            logger.info(
                "采信检测 [2/3] 模型探测完成: %d/%d 通过联网验证",
                verified_count, len(adapters),
            )
            for item in capabilities:
                model_name = item.get("model", item.get("provider_id", "?"))
                status = item.get("status", "unknown")
                await _report(
                    "2/3 模型探测", "info" if status == "verified" else "error",
                    f"{model_name}: {status}",
                    model=model_name,
                    detail={"provider_id": item.get("provider_id"), "status": status, "error": item.get("error")},
                )
            await _report(
                "2/3 模型探测", "success",
                f"模型探测完成: {verified_count}/{len(adapters)} 通过联网验证",
                duration_ms=int((time.time() - t0) * 1000),
            )
        except Exception as exc:
            await _report("2/3 模型探测", "error", f"模型探测失败: {exc}", duration_ms=int((time.time() - t0) * 1000))
            raise _wrap_with_stage(2, exc) from exc

        # ──────── 3/3 引用检测 ────────
        question_count = min(len(questions), 20)
        await _report(
            "3/3 引用检测", "start",
            f"开始引用检测（{question_count} 问题 × {len(adapters)} 模型）",
        )
        t0 = time.time()
        logger.info(
            "采信检测 [3/3] 引用检测: %s（%d 问题 × %d 模型）",
            url, question_count, len(adapters),
        )
        try:
            result = await asyncio.to_thread(
                run_citation_check,
                target_urls=target_urls,
                candidates=[],  # 不再用生成的问题
                adapters=adapters,
                question_count=question_count,
                forbidden_terms=[*target_urls],
                client_questions=questions[:question_count],  # 客户问题直通
            )
        except Exception as exc:
            await _report("3/3 引用检测", "error", f"引用检测失败: {exc}", duration_ms=int((time.time() - t0) * 1000))
            raise _wrap_with_stage(3, exc) from exc
        await _report("3/3 引用检测", "success", "引用检测完成", duration_ms=int((time.time() - t0) * 1000))

        # 附加元信息（不再有 purpose）
        result["target"] = {
            "requested_url": url,
            "resolved_url": target_urls[-1] if target_urls else url,
            "title": title,
            "extraction_method": content.extraction_method,
        }
        result["provider_capabilities"] = capabilities

        # 存储结果
        await self._store_results(url, result, questions, client_id)

        return result

    def _make_default_progress(self, task_id: Optional[str], url: str) -> Callable[..., Awaitable[None]]:
        """构造默认 progress 回调：写 scan_task_manager.add_log + 持久化 CitationCheckLog。

        - 有 task_id 时同步调 ``add_log(task_id, level, message)``（供 ScanPanel 实时轮询）；
        - 始终 ``db.add(CitationCheckLog(...))`` + commit（供历史查询与运维排查）；
        - task_id 为 None（定时任务）时只持久化，不写内存任务日志。

        回调签名：``async def progress(stage, status, message, *, detail, model, duration_ms)``。
        """
        db = self.db
        # status → scan_task_manager 日志级别映射
        level_map = {"start": "info", "success": "success", "error": "error", "info": "info"}

        async def progress(stage, status, message, *, detail=None, model=None, duration_ms=None):
            level = level_map.get(status, "info")
            # 1. 内存任务日志（供 ScanPanel 2s 轮询）
            if task_id:
                try:
                    add_log(task_id, level, message)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("add_log 失败（已忽略）: %s", exc)
                # 阶段 4 - ⑤：stage 4 模型级上报时，结构化存储 probe 状态。
                # detail["status"] 是真实 probe 状态（verified/error/no_search/...），
                # 供 ScanPanel 模型状态卡片直接读取，无需从日志文本解析。
                if stage == "2/3 模型探测" and model and detail and detail.get("status"):
                    try:
                        update_citation_model(
                            task_id, model, detail["status"], detail.get("error"),
                        )
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("update_citation_model 失败（已忽略）: %s", exc)
            # 2. 持久化到 citation_check_logs（供历史查询）
            db.add(CitationCheckLog(
                task_id=task_id,
                url=url,
                stage=stage,
                status=status,
                model=model,
                detail=detail,
                duration_ms=duration_ms,
            ))
            await db.commit()

        return progress

    def on_config_changed(self, provider_id: Optional[str] = None) -> None:
        """AI 配置变更后调用，清空探测缓存。

        - provider_id=None：清空全部（批量配置变更时调用）
        - provider_id="qwen"：只清该模型（单模型 Key 更新时调用）

        本子项目只暴露入口，API 路由的接入属子项目 C/D 范围。
        """
        invalidate_probe_cache(provider_id)

    # ------------------------------------------------------------------
    # 结果存储
    # ------------------------------------------------------------------

    async def _store_results(
        self, url: str, result: dict, questions: list[str], client_id: str
    ) -> None:
        """将检测结果存入 citation_results 表（幂等：URL+model+question 唯一）。

        Phase 2: 关联 client_question_id（通过 question 文本匹配 ClientQuestion.id）。
        """
        # 构建 question → client_question_id 映射
        from app.models.client_question import ClientQuestion
        q_result = await self.db.execute(
            select(ClientQuestion.id, ClientQuestion.question).where(
                ClientQuestion.client_id == client_id,
                ClientQuestion.status == "active",
            )
        )
        question_id_map = {row[1]: row[0] for row in q_result.fetchall()}

        stored_count = 0
        for item in result.get("results", []):
            hit_type = item["hit"]["layer"]
            question = item["question"]
            model = item["model"]

            existing = await self.db.execute(
                select(CitationResult).where(
                    CitationResult.url == url,
                    CitationResult.model == model,
                    CitationResult.question == question,
                )
            )
            if existing.scalar_one_or_none():
                continue

            self.db.add(CitationResult(
                url=url,
                model=model,
                question=question,
                answer=item.get("answer", ""),
                hit_type=hit_type,
                sources=item.get("sources", []),
                client_question_id=question_id_map.get(question),
            ))
            stored_count += 1

        await self.db.commit()
        logger.info("采信检测结果已存储: %s（%d 条新记录）", url, stored_count)

    # ------------------------------------------------------------------
    # 批量检测
    # ------------------------------------------------------------------

    async def check_all_pending(
        self, *, task_id: Optional[str] = None, concurrency: int = 3
    ) -> dict:
        """检测所有待检测的 URL，返回汇总信息。

        failures 项结构：{"url", "stage", "error"}
        - stage：从异常消息的 [N/5 阶段名] 前缀提取，无标签为 "unknown"
        - 便于运维按阶段聚合失败原因，定位瓶颈步骤

        阶段 2 - ④b：task_id 透传给 check_url，使批量扫描的每条 URL 日志都能
        写入 scan_task_manager + citation_check_logs。

        阶段 3 - ②：并发化。原串行实现 N 个 URL 耗时 = N × 单条耗时；改用
        ``asyncio.gather`` + ``Semaphore(concurrency)`` 并发，单条失败不影响其他。
        concurrency 默认 3（平衡 API 限流与吞吐）。每条 check_url 在独立 semaphore
        槽位内执行，异常被捕获记入 failures，不传播到 gather 导致整批取消。

        Bugfix：每个 _check_one 创建独立 AsyncSession + CitationChecker。
        原实现共享 self.db，但 SQLAlchemy AsyncSession 不是并发安全的——
        多协程并发 commit 会导致事务状态混乱（PendingRollbackError）+
        citation_check_logs 主键冲突 + release_scan_lock 失败（锁泄漏）。
        独立 session 既保留并发优势，又保证事务隔离。
        """
        pending = await self.get_pending_urls()
        total = len(pending)
        if total == 0:
            return {"total": 0, "success": 0, "failed": 0, "failures": []}

        # 修复进度 >100%：trigger_scan 用第一次查询的 pending 设 create_task(total)，
        # 本方法重新查询 pending 可能因期间新分发同步而数量不同。用实际 pending 数
        # 更新 task.total，确保 processed 不会超过 total（ScanPanel 进度不会 >100%）。
        if task_id:
            try:
                update_progress(task_id, total=total)
            except Exception as exc:  # noqa: BLE001
                logger.warning("update_progress(total) 失败（已忽略）: %s", exc)

        from app.core.database import async_session
        semaphore = asyncio.Semaphore(max(1, concurrency))
        success = 0
        failures: list[dict] = []
        # 用列表收集结果，避免闭包变量竞争
        results: list[dict] = []
        processed = 0

        async def _check_one(url: str, client_id: str) -> None:
            nonlocal success, processed
            async with semaphore:
                # 独立 session：AsyncSession 并发不安全，每条 URL 用自己的 session
                async with async_session() as task_db:
                    checker = CitationChecker(task_db)
                    try:
                        await checker.check_url(url, client_id, task_id=task_id)
                        results.append({"ok": True, "url": url})
                    except Exception as exc:
                        error_msg = str(exc)
                        stage = _extract_stage(error_msg)
                        logger.error("采信检测失败 %s [%s]: %s", url, stage, exc)
                        results.append({"ok": False, "url": url, "stage": stage, "error": error_msg})
                # 阶段 4 - ⑤：每条完成即更新活动窗口进度计数（processed/success/failed），
                # 供 ScanPanel 进度条实时推进。task_id 为 None（定时任务无活动窗口）时跳过。
                processed += 1
                if task_id:
                    try:
                        update_progress(
                            task_id,
                            processed=processed,
                            success=sum(1 for r in results if r["ok"]),
                            failed=sum(1 for r in results if not r["ok"]),
                        )
                    except Exception as exc:  # noqa: BLE001 - 进度更新失败不应中断检测
                        logger.warning("update_progress 失败（已忽略）: %s", exc)

        # 并发执行所有 URL 的检测
        await asyncio.gather(*[_check_one(url, cid) for url, cid in pending])

        # 汇总结果（gather 完成后顺序遍历，无竞争）
        for r in results:
            if r["ok"]:
                success += 1
            else:
                failures.append({"url": r["url"], "stage": r["stage"], "error": r["error"]})

        return {
            "total": total,
            "success": success,
            "failed": len(failures),
            "failures": failures,
        }
