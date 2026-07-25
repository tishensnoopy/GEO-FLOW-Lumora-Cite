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

from fastapi import HTTPException
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


class DistributionConflictError(HTTPException):
    """URL 重复冲突（409）。"""
    def __init__(self, detail: str):
        super().__init__(status_code=409, detail=detail)


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

    async def _query_manual_distributions(
        self, client_id: Optional[str] = None
    ) -> list[dict]:
        """查手动录入的记录（monitor.manual_distributions）。"""
        query = select(ManualDistribution).where(ManualDistribution.status == "synced")
        if client_id:
            query = query.where(ManualDistribution.client_id == client_id)
        result = await self.db.execute(query)
        records = result.scalars().all()

        # 批量查 index_results
        urls = [r.remote_url for r in records]
        index_map = await self._aggregate_index_results(urls)

        return [self._serialize_manual(r, index_map) for r in records]

    def _serialize_manual(self, record, index_map: dict) -> dict:
        """序列化手动录入记录。

        字段对齐 ``_serialize_geoflow``：无对应内容数据的字段填 None
        （content_keywords 填空列表 []，与 geoflow 默认值一致）。
        ``note`` 是 manual 特有字段，放在 distributed_at 之后、index_status 之前。
        """
        url = record.remote_url
        idx = index_map.get(url)
        return {
            "id": str(record.id),
            "source": "manual",
            "client_id": record.client_id,
            "site_type": None,
            "remote_url": url,
            "action": "manual",
            "status": record.status,
            "channel_name": None,
            "channel_type": None,
            "content_title": None,
            "content_slug": None,
            "content_excerpt": None,
            "content_body": None,
            "content_keywords": [],
            "meta_description": None,
            "original_keyword": None,
            "published_at": None,
            "distributed_at": record.created_at.isoformat() if record.created_at else None,
            "note": record.note,
            "index_status": {
                "baidu": idx.baidu_status if idx else "pending",
                "toutiao": idx.toutiao_status if idx else "pending",
                "sogou": idx.sogou_status if idx else "pending",
                "so360": idx.so360_status if idx else "pending",
                "bing": idx.bing_status if idx else "pending",
            } if idx else {k: "pending" for k in ("baidu", "toutiao", "sogou", "so360", "bing")},
        }

    async def _aggregate_index_results(self, urls: list[str]) -> dict:
        """批量查 index_results，返回 url → IndexResult 映射。"""
        if not urls:
            return {}
        result = await self.db.execute(
            select(IndexResult).where(IndexResult.url.in_(urls))
        )
        return {r.url: r for r in result.scalars().all()}

    async def list_distributions(
        self,
        client_id: Optional[str] = None,
        source: Optional[str] = None,
        include_manual: bool = True,
    ) -> list[dict]:
        """查询分发记录（合并 GEOFlow + 手动录入）。

        Parameters
        ----------
        client_id : str | None
            按客户过滤。None = 全部客户（admin）。
        source : str | None
            'geoflow' / 'manual' / None（全部）。
        include_manual : bool
            是否包含手动录入（默认 True）。
        """
        results = []
        if source in (None, "geoflow"):
            geoflow_records = await self._query_geoflow_distributions(client_id)
            results.extend(geoflow_records)
        if include_manual and source in (None, "manual"):
            manual_records = await self._query_manual_distributions(client_id)
            results.extend(manual_records)
        # 按时间降序
        results.sort(
            key=lambda x: x.get("distributed_at") or x.get("created_at") or "",
            reverse=True,
        )
        return results

    async def _match_client_by_domain(self, remote_url: str) -> tuple[str, str]:
        """通过 URL 的 domain 匹配 client_sites，返回 (client_id, site_type)。"""
        domain = self._extract_domain(remote_url)
        domain_map = await self._build_domain_map()
        matched = domain_map.get(domain)
        if matched is None:
            raise HTTPException(
                status_code=400,
                detail=f"URL 的 domain '{domain}' 未在客户站点中登记",
            )
        return matched

    async def create_manual_distribution(
        self,
        remote_url: str,
        admin_user_id: int,
        admin_name: str,
        client_id: Optional[str] = None,
        note: Optional[str] = None,
    ) -> dict:
        """运营手动录入 URL。

        client_id 为 None 时自动通过 domain 匹配。
        重复检测：手动表 + GEOFlow 表。
        """
        if client_id is None:
            client_id, _ = await self._match_client_by_domain(remote_url)

        # 检查手动表重复
        existing_manual = await self.db.execute(
            select(ManualDistribution).where(
                ManualDistribution.client_id == client_id,
                ManualDistribution.remote_url == remote_url,
            )
        )
        if existing_manual.scalar_one_or_none():
            raise DistributionConflictError(f"URL 已存在（手动录入）：{remote_url}")

        # 检查 GEOFlow 表重复
        existing_geoflow = await self.db.execute(
            select(GeoflowArticleDistribution).where(
                GeoflowArticleDistribution.remote_url == remote_url,
                GeoflowArticleDistribution.status == "synced",
            )
        )
        if existing_geoflow.scalar_one_or_none():
            raise DistributionConflictError(f"URL 已存在（GEOFlow 推送）：{remote_url}")

        record = ManualDistribution(
            client_id=client_id,
            remote_url=remote_url,
            status="synced",
            note=note,
            created_by_admin_id=admin_user_id,
        )
        self.db.add(record)
        await self.db.commit()

        return {"action": "created", "client_id": client_id, "source": "manual"}
