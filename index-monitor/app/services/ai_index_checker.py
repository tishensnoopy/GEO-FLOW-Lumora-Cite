# index-monitor/app/services/ai_index_checker.py
"""AI 收录检测服务：检测 AI 大模型是否收录了目标 URL。

收录检测在问题监测之前执行（双阶段管道 Phase 1）：
1. 对每个 URL × 模型组合，直接询问 AI 是否了解该 URL
2. 解析响应判定 indexed / not_indexed
3. 存入 ai_index_results 表

仅对 index_status='indexed' 的组合执行问题监测（Phase 2 改造）。
"""
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integration.geoflow import GeoflowRepository
from app.models.ai_index_result import AIIndexResult
from app.models.client import ClientSite
from app.models.manual_distribution import ManualDistribution
from app.services.citation_check.providers import adapter_catalog
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
        2. ai_index_results 中无该 URL×model 记录（增量）
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

        # 2. 查已有收录检测记录，排除已检测的 URL×model 组合
        existing_result = await self.db.execute(
            select(AIIndexResult.url, AIIndexResult.model)
        )
        existing = {(row[0], row[1]) for row in existing_result.fetchall()}

        # 3. 生成 pending 组合
        pending: list[tuple[str, str, str]] = []
        for url, client_id in distributed.items():
            for model in models:
                if (url, model) not in existing:
                    pending.append((url, client_id, model))

        return pending
