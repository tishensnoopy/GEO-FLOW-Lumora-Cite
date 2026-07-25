# index-monitor/app/services/distribution_query.py
"""分发记录查询服务——跨 schema JOIN GEOFlow + 手动录入。

设计文档第 7 节。

数据来源
========
1. GEOFlow 分发（public.article_distributions）：跨 schema JOIN 查询，
   通过 domain 匹配 monitor.client_sites 找到 client_id
2. 手动录入（monitor.manual_distributions）：直接查询，client_id 已知

合并后按 distributed_at 降序排列。
"""
import json
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client import ClientSite
from app.models.geoflow_models import (
    GeoflowArticle,
    GeoflowArticleDistribution,
    GeoflowDistributionChannel,
)
from app.models.index_result import IndexResult
from app.models.manual_distribution import ManualDistribution
from app.utils.validators import normalize_domain


class DistributionQueryService:
    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def _extract_domain(url: str) -> str:
        """提取并标准化 domain（委托给 normalize_domain）。"""
        return normalize_domain(url)

    async def _build_domain_map(self) -> dict[str, tuple[str, str]]:
        """查所有 active client_sites，建 domain → (client_id, site_type) 映射。"""
        result = await self.db.execute(
            select(ClientSite).where(ClientSite.status == "active")
        )
        sites = result.scalars().all()
        return {
            self._extract_domain(s.domain): (s.client_id, s.site_type)
            for s in sites
        }

    async def _query_geoflow_distributions(
        self, client_id: Optional[str] = None
    ) -> list[dict]:
        """查 GEOFlow 的 article_distributions（跨 schema JOIN）。

        domain 匹配采用 Python 层处理：先查所有 client_sites 建映射，再匹配。
        """
        query = (
            select(
                GeoflowArticleDistribution,
                GeoflowArticle,
                GeoflowDistributionChannel,
                IndexResult,
            )
            .join(GeoflowArticle, GeoflowArticle.id == GeoflowArticleDistribution.article_id)
            .outerjoin(
                GeoflowDistributionChannel,
                GeoflowDistributionChannel.id == GeoflowArticleDistribution.distribution_channel_id,
            )
            .outerjoin(IndexResult, IndexResult.url == GeoflowArticleDistribution.remote_url)
            .where(
                GeoflowArticleDistribution.status == "synced",
                GeoflowArticleDistribution.action != "delete",
                GeoflowArticleDistribution.remote_url.isnot(None),
            )
        )
        result = await self.db.execute(query)
        rows = result.fetchall()

        domain_map = await self._build_domain_map()

        records = []
        for row in rows:
            dist, article, channel, index_result = row
            domain = self._extract_domain(dist.remote_url)
            matched = domain_map.get(domain)
            if matched is None:
                continue  # 未登记 domain，跳过
            cid, site_type = matched
            if client_id and cid != client_id:
                continue
            records.append(
                self._serialize_geoflow(dist, article, channel, index_result, cid, site_type)
            )
        return records

    def _serialize_geoflow(
        self, dist, article, channel, index_result, client_id, site_type
    ) -> dict:
        """序列化 GEOFlow 分发记录。"""
        keywords_raw = article.keywords if article else None
        if isinstance(keywords_raw, str) and keywords_raw:
            try:
                keywords = json.loads(keywords_raw)
            except (json.JSONDecodeError, ValueError):
                keywords = [k.strip() for k in keywords_raw.split(",") if k.strip()]
        else:
            keywords = keywords_raw or []

        return {
            "id": str(dist.id),
            "source": "geoflow",
            "client_id": client_id,
            "site_type": site_type,
            "remote_url": dist.remote_url,
            "action": dist.action,
            "status": dist.status,
            "channel_name": channel.name if channel else None,
            "channel_type": channel.channel_type if channel else None,
            "content_title": article.title if article else None,
            "content_slug": article.slug if article else None,
            "content_excerpt": article.excerpt if article else None,
            "content_body": article.content if article else None,
            "content_keywords": keywords,
            "meta_description": article.meta_description if article else None,
            "original_keyword": article.original_keyword if article else None,
            "published_at": article.published_at.isoformat() if article and article.published_at else None,
            "distributed_at": dist.created_at.isoformat() if dist.created_at else None,
            "index_status": {
                "baidu": index_result.baidu_status if index_result else "pending",
                "toutiao": index_result.toutiao_status if index_result else "pending",
                "sogou": index_result.sogou_status if index_result else "pending",
                "so360": index_result.so360_status if index_result else "pending",
                "bing": index_result.bing_status if index_result else "pending",
            },
        }

    # _query_manual_distributions / list_distributions / create_manual_distribution
    # 在后续任务实现
