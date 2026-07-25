# index-monitor/app/services/archive_service.py
"""归档服务：定期归档已删除的分发记录。

任务 9 补丁（D01/D02/D06 修复）：
- D01：client_id 通过 domain_map 匹配，匹配不到则跳过（不为 None）
- D02：content_keywords 从 Text 转 JSON（json.loads）
- D06：查询条件用 action=="delete"（不是 status=="deleted"）

前置条件（D25）：
- alembic upgrade head 已执行（当前版本 ≥ 009）
- 迁移 006 已创建 monitor.archived_distributions 表
- 迁移 009 已删除孤儿表 monitor.article_distributions
"""
import json
import logging

from sqlalchemy import select, exists
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.archived_distribution import ArchivedDistribution
from app.models.client import ClientSite
from app.models.geoflow_models import (
    GeoflowArticle,
    GeoflowArticleDistribution,
    GeoflowDistributionChannel,
)
# 注：IndexResult / CitationResult 顶部 import 保留（控制者裁定 5），
# 原计划用于 scheduled_monthly_archive（不在任务 9 范围，不实现）。
from app.models.index_result import IndexResult  # noqa: F401
from app.models.citation_result import CitationResult  # noqa: F401
from app.utils.validators import normalize_domain

logger = logging.getLogger(__name__)


class ArchiveService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def _build_domain_map(self) -> dict[str, str]:
        """domain → client_id 映射（用于 D01 匹配）。"""
        result = await self.db.execute(
            select(ClientSite).where(ClientSite.status == "active")
        )
        return {
            normalize_domain(s.domain): s.client_id
            for s in result.scalars().all()
        }

    @staticmethod
    def _parse_keywords(raw) -> list:
        """D02：Text → JSON list 转换（参考 distribution_query._serialize_geoflow）。"""
        if isinstance(raw, str) and raw:
            try:
                return json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                return [k.strip() for k in raw.split(",") if k.strip()]
        return raw or []

    async def archive_deleted_distributions(self) -> int:
        """归档已删除的分发记录（action=='delete'）。

        D06 修复：查询条件用 action=="delete"（GEOFlow 删除标记），
        不是 status=="deleted"（status 默认是 queued/synced）。
        """
        # D06：查 action=='delete' 的记录
        # 去重：排除已归档的 remote_url（scheduler 每日运行，避免重复归档）
        query = (
            select(GeoflowArticleDistribution, GeoflowArticle, GeoflowDistributionChannel)
            .join(GeoflowArticle, GeoflowArticle.id == GeoflowArticleDistribution.article_id)
            .outerjoin(
                GeoflowDistributionChannel,
                GeoflowDistributionChannel.id == GeoflowArticleDistribution.distribution_channel_id,
            )
            .where(
                GeoflowArticleDistribution.action == "delete",  # D06
                GeoflowArticleDistribution.remote_url.isnot(None),
                ~exists(select(ArchivedDistribution).where(
                    ArchivedDistribution.remote_url == GeoflowArticleDistribution.remote_url
                )),
            )
        )
        rows = (await self.db.execute(query)).fetchall()
        domain_map = await self._build_domain_map()

        count = 0
        for dist, article, channel in rows:
            domain = normalize_domain(dist.remote_url)
            client_id = domain_map.get(domain)
            if client_id is None:
                # D01：未匹配 domain 则跳过（不为 None）
                logger.warning(f"归档跳过：URL {dist.remote_url} 的 domain {domain} 未登记")
                continue

            archived = ArchivedDistribution(
                client_id=client_id,  # D01：不为 None
                remote_url=dist.remote_url,
                # 注：简报步骤 3 还列出 source/action/channel_name/distributed_at，
                # 但 ArchivedDistribution 模型（迁移 006）无这 4 列，SQLAlchemy
                # _declarative_constructor 会抛 TypeError。控制者裁定 4 要求"逐字段
                # 实现"，但无法为不存在的列赋值——此处按模型实际列集合实现，
                # 多余字段已在报告中标记为简报缺陷。
                content_title=article.title if article else None,
                content_slug=article.slug if article else None,
                content_excerpt=article.excerpt if article else None,
                content_body=article.content if article else None,
                content_keywords=self._parse_keywords(article.keywords),  # D02：Text→JSON
                meta_description=article.meta_description if article else None,
                original_keyword=article.original_keyword if article else None,
                published_at=article.published_at if article else None,
                # archived_at 由 DB server_default=func.now() 自动填值，无需显式赋值
                # 模型有 geoflow_article_id 列（Integer），简报步骤 3 遗漏——补上以
                # 保留跨 schema 关联（article.id 来自 public.articles）。
                geoflow_article_id=article.id if article else None,
            )
            self.db.add(archived)
            count += 1

        await self.db.commit()
        return count
