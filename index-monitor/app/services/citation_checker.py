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
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.geoflow_models import GeoflowArticleDistribution
from app.models.manual_distribution import ManualDistribution
from app.models.citation_result import CitationResult
from app.models.index_result import IndexResult
from app.models.client import ClientSite
from app.utils.validators import normalize_domain
from app.models.system_config import SystemConfig
from app.services.llm_client import (
    call_deepseek,
    load_ai_configs,
    make_call_generator,
    # P1 新增：带解析重试的调用入口
    call_deepseek_with_parse_retry,
    make_parse_retry_generator,
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
        """获取待检测采信的 URL 列表。

        筛选条件：GEOFlow 分发 + 手动录入 status='synced' 且 citation_results 中无记录。
        返回 [(remote_url, client_id), ...]。
        """
        geoflow_result = await self.db.execute(
            select(GeoflowArticleDistribution.remote_url)
            .where(
                GeoflowArticleDistribution.status == "synced",
                GeoflowArticleDistribution.action != "delete",
                GeoflowArticleDistribution.remote_url.isnot(None),
            )
        )
        geoflow_urls = {row[0] for row in geoflow_result.fetchall()}

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

        # 排除已有采信记录的 URL
        checked_result = await self.db.execute(select(CitationResult.url))
        checked_urls = {row[0] for row in checked_result.fetchall()}

        return [
            (url, client_id)
            for url, client_id in distributed.items()
            if url not in checked_urls
        ]

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
    # 单 URL 检测
    # ------------------------------------------------------------------

    async def check_url(self, url: str, client_id: str) -> dict:
        """对单个 URL 执行完整 AI 采信检测。

        返回 lumora-cite run_citation_check 的完整结果 dict，
        并附带 purpose/questions 元信息供 API 响应使用。

        每步骤失败时抛带阶段标签 [N/5 阶段名] 的 ValueError，便于
        check_all_pending 汇总失败诊断。
        """
        config = await self._load_ai_config()
        deepseek_key = config.get("ai_deepseek_api_key", "")
        question_model = config.get("ai_question_model", DEFAULT_QUESTION_MODEL)

        if not deepseek_key:
            raise ValueError(
                "DeepSeek API Key 未配置，无法生成检测问题。"
                "请在系统设置 → AI API Key 管理中配置 DeepSeek API Key。"
            )

        # Step 1: 抓取公开内容
        logger.info("采信检测 [1/5] 抓取内容: %s", url)
        try:
            content = await asyncio.to_thread(fetch_public_content, url)
            if not content.suitability.suitable:
                raise ValueError(
                    f"内容不适合检测：{content.suitability.rejection_reason}"
                    f"（code={content.suitability.rejection_code}）"
                )
        except Exception as exc:
            raise _wrap_with_stage(1, exc) from exc

        title = content.title
        text = content.text
        target_urls = [
            u for u in (content.requested_url, content.resolved_url, content.canonical_url)
            if u
        ]

        # Step 2: DeepSeek 推断发布目的（带解析重试）
        logger.info("采信检测 [2/5] 推断发布目的（DeepSeek %s）: %s", question_model, title)
        try:
            purpose_prompt = build_purpose_prompt(title, text)
            # P1 改用 call_deepseek_with_parse_retry：调用成功但 JSON 解析失败时
            # 自动追加"请严格只返回 JSON"提示重调，最多 2 次解析重试
            purpose = await asyncio.to_thread(
                call_deepseek_with_parse_retry,
                deepseek_key,
                question_model,
                purpose_prompt,
                parser=parse_purpose_response,
            )
        except Exception as exc:
            raise _wrap_with_stage(2, exc) from exc

        # Step 3: DeepSeek 生成检测问题（带解析重试）
        logger.info("采信检测 [3/5] 生成检测问题（DeepSeek %s）: %s", question_model, title)
        try:
            # P1 改用 make_parse_retry_generator：包装 make_call_generator + 解析重试
            call_generator = make_parse_retry_generator(
                deepseek_key,
                question_model,
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
                    "请检查 DeepSeek API Key 是否有效，或重试。"
                )
        except Exception as exc:
            raise _wrap_with_stage(3, exc) from exc

        # Step 4: 配置引用检测模型 + 探测联网能力
        self._set_provider_env(config)
        citation_models_str = config.get("ai_citation_models", "")
        selected_ids = (
            [m.strip() for m in citation_models_str.split(",") if m.strip()]
            if citation_models_str
            else None
        )
        # P1 catalog 过滤：selected_ids 含已下线 id（如 deepseek）时过滤并告警
        # 避免因配置残留导致"未配置任何引用检测模型"报错
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
            capabilities = await asyncio.to_thread(probe_adapter_capabilities, adapters)
            verified_ids = {
                item["provider_id"] for item in capabilities if item["status"] == "verified"
            }
            verified_adapters = [a for a in adapters if a.provider_id in verified_ids]
            if not verified_adapters:
                failed_models = [
                    f"{item['model']}({item['status']})"
                    for item in capabilities
                ]
                raise ValueError(
                    "所选引用检测模型均未通过联网搜索与来源 URL 返回检测。"
                    f"模型状态：{', '.join(failed_models)}。"
                    "请检查 API Key 是否有效，或更换支持联网搜索的模型。"
                )
        except Exception as exc:
            raise _wrap_with_stage(4, exc) from exc

        # Step 5: 执行引用检测
        question_count = min(len(candidates), 10)
        logger.info(
            "采信检测 [5/5] 执行引用检测: %s（%d 问题 × %d 模型）",
            url, question_count, len(verified_adapters),
        )
        try:
            result = await asyncio.to_thread(
                run_citation_check,
                target_urls=target_urls,
                candidates=candidates,
                adapters=verified_adapters,
                question_count=question_count,
                forbidden_terms=[*target_urls, title],
            )
        except Exception as exc:
            raise _wrap_with_stage(5, exc) from exc

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

    async def _store_results(self, url: str, result: dict) -> None:
        """将检测结果存入 citation_results 表（幂等：URL+model+question 唯一）。"""
        stored_count = 0
        for item in result.get("results", []):
            hit_type = item["hit"]["layer"]
            question = item["question"]
            model = item["model"]

            # 幂等检查：URL + model + question 唯一
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
            ))
            stored_count += 1

        await self.db.commit()
        logger.info(
            "采信检测结果已存储: %s（%d 条新记录）",
            url, stored_count,
        )

    # ------------------------------------------------------------------
    # 批量检测
    # ------------------------------------------------------------------

    async def check_all_pending(self) -> dict:
        """检测所有待检测的 URL，返回汇总信息。

        failures 项结构：{"url", "stage", "error"}
        - stage：从异常消息的 [N/5 阶段名] 前缀提取，无标签为 "unknown"
        - 便于运维按阶段聚合失败原因，定位瓶颈步骤
        """
        pending = await self.get_pending_urls()
        total = len(pending)
        success = 0
        failures: list[dict] = []

        for url, client_id in pending:
            try:
                await self.check_url(url, client_id)
                success += 1
            except Exception as exc:
                error_msg = str(exc)
                stage = _extract_stage(error_msg)
                logger.error("采信检测失败 %s [%s]: %s", url, stage, exc)
                failures.append({
                    "url": url,
                    "stage": stage,
                    "error": error_msg,
                })

        return {
            "total": total,
            "success": success,
            "failed": len(failures),
            "failures": failures,
        }
