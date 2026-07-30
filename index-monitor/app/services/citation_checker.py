# index-monitor/app/services/citation_checker.py
"""AI 采信检测服务：封装 lumora-cite 完整检测流程。

流程：抓取公开内容 → DeepSeek 推断发布目的+生成检测问题 →
      配置引用检测模型 → 探测模型联网能力 → 执行引用检测 → 存储结果。

所有 lumora-cite 同步调用通过 asyncio.to_thread() 包装，不阻塞事件循环。

P1 稳定性增强（子项目 A）：
- 步骤 2/3 改用 call_deepseek_with_parse_retry / make_parse_retry_generator
  对 LLM 返回的脏 JSON 自动重调
- 步骤 4 加 catalog 过滤：selected_ids 含已下线 id 时过滤并告警
- 每步骤失败时异常带阶段标签 [N/5 阶段名]，便于批量失败诊断
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
from app.models.system_config import SystemConfig
# 阶段 2 - ④b：progress 回调默认实现复用 scan_task_manager.add_log（sync，线程安全）
# 阶段 4 - ⑤：复用 update_citation_model 结构化存储模型 probe 状态
# 阶段 4 - ⑤：复用 update_progress 推进活动窗口进度计数（processed/success/failed）
from app.services.scan_task_manager import add_log, update_citation_model, update_progress
from app.services.llm_client import (
    call_deepseek,
    load_ai_configs,
    make_call_generator,
    # P1 新增：带解析重试的调用入口
    call_deepseek_with_parse_retry,
    make_parse_retry_generator,
    # 阶段 2 - ⑥b 新增：通用 provider fallback 入口
    build_question_providers,
    call_llm_with_parse_retry_fallback,
    make_fallback_parse_retry_generator,
)
# 修复：DEFAULT_QUESTION_MODEL 从 llm_client 导入，保持单一数据源。
# 原本地定义 "deepseek-chat" 已被 DeepSeek API 废弃（2026年），
# 会调用失败导致采信检测整体失灵。
from app.services.llm_client import DEFAULT_QUESTION_MODEL
from app.services.citation_check import (
    generate_candidates,
    run_citation_check,
)
from app.services.citation_check.engine import probe_adapter_capabilities
from app.services.citation_check.engine import invalidate_probe_cache
from app.services.citation_check.fetcher import fetch_public_content
from app.services.citation_check.providers import default_adapters, adapter_catalog
from app.services.citation_check.question_generation import (
    build_purpose_prompt,
    parse_purpose_response,
    parse_candidate_response,
)

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
    "ai_question_model",
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

# 阶段标签正则：[1/5 抓取] [2/5 目的推断] 等
_STAGE_LABEL_RE = re.compile(r"^\[(\d+/\d+\s+[^\]]+)\]")

# 5 个阶段名（与 check_url 步骤对应）
_STAGES = {
    1: "1/5 抓取",
    2: "2/5 目的推断",
    3: "3/5 问题生成",
    4: "4/5 模型探测",
    5: "5/5 引用检测",
}


def _extract_stage(message: str) -> str:
    """从异常消息中提取 [N/5 阶段名] 前缀，无标签返回 'unknown'。"""
    match = _STAGE_LABEL_RE.match(str(message or ""))
    return match.group(1) if match else "unknown"


def _wrap_with_stage(stage_num: int, exc: Exception) -> ValueError:
    """把异常包装成带阶段标签的 ValueError。"""
    stage = _STAGES.get(stage_num, f"{stage_num}/5 未知阶段")
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
        """获取待检测采信的 URL 列表（增量 + 优先级）。

        筛选条件：GEOFlow 分发 + 手动录入 status='synced' 且 citation_results 中无记录。
        返回 [(remote_url, client_id), ...]。

        阶段 3 - ② 增量优先级：
        - 增量：排除已有 citation_results 记录的 URL（LEFT JOIN ... IS NULL 语义）。
        - 优先级：按 IndexResult.created_at DESC 排序，新文章优先检测。
          已收录文章更可能被 AI 引用，优先做采信检测；未收录文章（无 IndexResult，
          created_at 为 NULL）排末尾。
        """
        repo = GeoflowRepository(self.db)
        geoflow_urls = set(await repo.get_synced_distribution_urls())

        manual_result = await self.db.execute(
            select(ManualDistribution.remote_url, ManualDistribution.client_id)
            .where(ManualDistribution.status == "synced")
        )
        distributed: dict[str, str] = {}
        for url, client_id in manual_result.fetchall():
            distributed[url] = client_id

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

        # 增量：排除已有采信记录的 URL
        checked_result = await self.db.execute(select(CitationResult.url))
        checked_urls = {row[0] for row in checked_result.fetchall()}
        pending = [
            (url, client_id)
            for url, client_id in distributed.items()
            if url not in checked_urls
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
        """对单个 URL 执行完整 AI 采信检测。

        返回 lumora-cite run_citation_check 的完整结果 dict，
        并附带 purpose/questions 元信息供 API 响应使用。

        每步骤失败时抛带阶段标签 [N/5 阶段名] 的 ValueError，便于
        check_all_pending 汇总失败诊断。

        阶段 2 - ④b：新增 task_id + progress 回调，解决"采信检测黑盒"问题。
        - progress(stage, status, message, *, detail, model, duration_ms) 是 async 回调；
        - 不传 progress 时用默认回调：写 scan_task_manager.add_log（供 ScanPanel 实时
          轮询）+ 持久化 CitationCheckLog（供历史查询）；
        - task_id 为 None（定时任务）时只写 CitationCheckLog，不写内存任务日志。
        """
        if progress is None:
            progress = self._make_default_progress(task_id, url)

        async def _report(stage: str, status: str, message: str, **kw) -> None:
            """progress 回调的薄封装，忽略回调自身异常不影响主流程。"""
            try:
                await progress(stage, status, message, **kw)
            except Exception as cb_exc:  # noqa: BLE001 - 回调失败不应中断检测
                logger.warning("progress 回调异常（已忽略）: %s", cb_exc)

        config = await self._load_ai_config()
        question_model = config.get("ai_question_model", DEFAULT_QUESTION_MODEL)

        # 阶段 2 - ⑥b：构建问题生成 provider 列表（DeepSeek→千问→豆包 fallback）。
        question_providers = build_question_providers(config)
        if not question_providers:
            await _report("2/5 目的推断", "error", "未配置任何可用于问题生成的 chat 模型 API Key")
            raise ValueError(
                "未配置任何可用于问题生成的 chat 模型 API Key。"
                "请在系统设置 → AI API Key 管理中配置 DeepSeek / DashScope(千问) / ARK(豆包) 任一 Key。"
            )

        # Step 1: 抓取公开内容
        await _report("1/5 抓取", "start", f"开始抓取内容: {url}")
        t0 = time.time()
        logger.info("采信检测 [1/5] 抓取内容: %s", url)
        try:
            content = await asyncio.to_thread(fetch_public_content, url)
            if not content.suitability.suitable:
                raise ValueError(
                    f"内容不适合检测：{content.suitability.rejection_reason}"
                    f"（code={content.suitability.rejection_code}）"
                )
        except Exception as exc:
            await _report("1/5 抓取", "error", f"抓取失败: {exc}", duration_ms=int((time.time() - t0) * 1000))
            raise _wrap_with_stage(1, exc) from exc
        await _report(
            "1/5 抓取", "success", f"抓取完成: {content.title}",
            detail={"extraction_method": content.extraction_method},
            duration_ms=int((time.time() - t0) * 1000),
        )

        title = content.title
        text = content.text
        target_urls = [
            u for u in (content.requested_url, content.resolved_url, content.canonical_url)
            if u
        ]

        # Step 2: 推断发布目的（带 provider fallback + 解析重试）
        await _report("2/5 目的推断", "start", f"开始推断发布目的（providers: {','.join(p.provider_id for p in question_providers)}）")
        t0 = time.time()
        logger.info(
            "采信检测 [2/5] 推断发布目的（providers: %s）: %s",
            ",".join(p.provider_id for p in question_providers), title,
        )
        try:
            purpose_prompt = build_purpose_prompt(title, text)
            purpose_raw = await asyncio.to_thread(
                call_llm_with_parse_retry_fallback,
                question_providers,
                purpose_prompt,
                parser=parse_purpose_response,
            )
            purpose = parse_purpose_response(purpose_raw)
        except Exception as exc:
            await _report("2/5 目的推断", "error", f"目的推断失败: {exc}", duration_ms=int((time.time() - t0) * 1000))
            raise _wrap_with_stage(2, exc) from exc
        await _report("2/5 目的推断", "success", f"目的推断完成: {purpose.primary_purpose}", duration_ms=int((time.time() - t0) * 1000))

        # Step 3: 生成检测问题（带 provider fallback + 解析重试）
        await _report("3/5 问题生成", "start", f"开始生成检测问题（providers: {','.join(p.provider_id for p in question_providers)}）")
        t0 = time.time()
        logger.info(
            "采信检测 [3/5] 生成检测问题（providers: %s）: %s",
            ",".join(p.provider_id for p in question_providers), title,
        )
        try:
            call_generator = make_fallback_parse_retry_generator(
                question_providers,
                parser=parse_candidate_response,
            )
            candidates = await asyncio.to_thread(
                generate_candidates,
                title=title,
                text=text,
                purpose=purpose,
                call_generator=call_generator,
            )
            if len(candidates) < 3:
                raise ValueError(
                    f"生成的问题不足：需要至少 3 个，实际 {len(candidates)} 个。"
                    "请检查问题生成模型 API Key 是否有效，或重试。"
                )
        except Exception as exc:
            await _report("3/5 问题生成", "error", f"问题生成失败: {exc}", duration_ms=int((time.time() - t0) * 1000))
            raise _wrap_with_stage(3, exc) from exc
        await _report("3/5 问题生成", "success", f"生成 {len(candidates)} 个候选问题", duration_ms=int((time.time() - t0) * 1000))

        # Step 4: 配置引用检测模型 + 探测联网能力
        await _report("4/5 模型探测", "start", "开始配置引用检测模型并探测联网能力")
        t0 = time.time()
        self._set_provider_env(config)
        citation_models_str = config.get("ai_citation_models", "")
        selected_ids = (
            [m.strip() for m in citation_models_str.split(",") if m.strip()]
            if citation_models_str
            else None
        )
        # P1 catalog 过滤：selected_ids 含已下线 id（如 deepseek）时过滤并告警
        if selected_ids:
            catalog_ids = {item["id"] for item in adapter_catalog()}
            valid_selected_ids = [mid for mid in selected_ids if mid in catalog_ids]
            dropped = set(selected_ids) - catalog_ids
            if dropped:
                logger.warning(
                    "引用检测模型列表含已下线项，已过滤: %s",
                    ", ".join(sorted(dropped)),
                )
            selected_ids = valid_selected_ids if valid_selected_ids else None

        try:
            adapters = await asyncio.to_thread(default_adapters, selected_ids)
            if not adapters:
                raise ValueError(
                    "未配置任何引用检测模型。请在系统设置中配置 DashScope/ARK/OpenAI 等 API Key，"
                    "使引用检测模型（千问/豆包/ChatGPT 等）可用。"
                )

            logger.info("采信检测 [4/5] 探测模型联网能力: %s", url)
            # 阶段 1 - ③：probe 降级为标注，不再淘汰模型。
            capabilities = await asyncio.to_thread(probe_adapter_capabilities, adapters)
            verified_count = sum(1 for item in capabilities if item["status"] == "verified")
            logger.info(
                "采信检测 [4/5] 模型探测完成: %d/%d 通过联网验证（通过仅作标注，不淘汰未通过模型）",
                verified_count, len(adapters),
            )
            # 阶段 2 - ④b：按模型逐条上报 probe 结果（供 ScanPanel 展示模型状态卡片）
            for item in capabilities:
                model_name = item.get("model", item.get("provider_id", "?"))
                status = item.get("status", "unknown")
                await _report(
                    "4/5 模型探测", "info" if status == "verified" else "error",
                    f"{model_name}: {status}",
                    model=model_name,
                    detail={"provider_id": item.get("provider_id"), "status": status, "error": item.get("error")},
                )
            await _report(
                "4/5 模型探测", "success",
                f"模型探测完成: {verified_count}/{len(adapters)} 通过联网验证",
                duration_ms=int((time.time() - t0) * 1000),
            )
        except Exception as exc:
            await _report("4/5 模型探测", "error", f"模型探测失败: {exc}", duration_ms=int((time.time() - t0) * 1000))
            raise _wrap_with_stage(4, exc) from exc

        # Step 5: 执行引用检测
        question_count = min(len(candidates), 10)
        await _report(
            "5/5 引用检测", "start",
            f"开始引用检测（{question_count} 问题 × {len(adapters)} 模型）",
        )
        t0 = time.time()
        logger.info(
            "采信检测 [5/5] 执行引用检测: %s（%d 问题 × %d 模型）",
            url, question_count, len(adapters),
        )
        try:
            result = await asyncio.to_thread(
                run_citation_check,
                target_urls=target_urls,
                candidates=candidates,
                adapters=adapters,
                question_count=question_count,
                # 阶段 1 - ⑥a：forbidden_terms 只禁目标 URL，允许标题词出现。
                forbidden_terms=[*target_urls],
            )
        except Exception as exc:
            await _report("5/5 引用检测", "error", f"引用检测失败: {exc}", duration_ms=int((time.time() - t0) * 1000))
            raise _wrap_with_stage(5, exc) from exc
        await _report("5/5 引用检测", "success", "引用检测完成", duration_ms=int((time.time() - t0) * 1000))

        # 附加元信息
        result["purpose"] = purpose.to_dict()
        result["target"] = {
            "requested_url": url,
            "resolved_url": target_urls[-1] if target_urls else url,
            "title": title,
            "extraction_method": content.extraction_method,
        }
        result["provider_capabilities"] = capabilities

        # 存储结果
        await self._store_results(url, result)

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
                if stage == "4/5 模型探测" and model and detail and detail.get("status"):
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
