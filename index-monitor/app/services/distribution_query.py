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
import logging
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integration.geoflow import GeoflowRepository
from app.models.client import ClientSite
from app.models.index_result import IndexResult
from app.models.manual_distribution import ManualDistribution
from app.utils.validators import normalize_domain

logger = logging.getLogger(__name__)


def _date_from_lower_bound(d: date) -> datetime:
    """date_from → 当天 00:00:00 UTC（含当天起始）。"""
    return datetime.combine(d, time.min, tzinfo=timezone.utc)


def _date_to_upper_bound(d: date) -> datetime:
    """date_to → 次日 00:00:00 UTC（用 < 比较，含当天结束）。"""
    return datetime.combine(d + timedelta(days=1), time.min, tzinfo=timezone.utc)


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
        self,
        client_id: Optional[str] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
    ) -> list[dict]:
        """查 GEOFlow 的 article_distributions（跨 schema JOIN）。

        domain 匹配采用 Python 层处理：先查所有 client_sites 建映射，再匹配。

        日期过滤（C10 修复）：按 ``article_distributions.created_at`` 过滤，
        与序列化字段 ``distributed_at`` 同源。``date_from`` 含当天起始，
        ``date_to`` 含当天结束（用 < 次日零点比较）。
        """
        # 通过防腐层查三表 join（不含 IndexResult——那是 LumoraCite 自己的表）
        repo = GeoflowRepository(self.db)
        geoflow_dtos = await repo.get_distributions_with_article(
            date_from=_date_from_lower_bound(date_from) if date_from is not None else None,
            date_to=_date_to_upper_bound(date_to) if date_to is not None else None,
        )

        # 单独查 IndexResult，建 url→result 映射
        index_result_map: dict[str, IndexResult] = {}
        if geoflow_dtos:
            urls = [dto.distribution.remote_url for dto in geoflow_dtos]
            index_result_rows = await self.db.execute(
                select(IndexResult).where(IndexResult.url.in_(urls))
            )
            for ir in index_result_rows.scalars().all():
                index_result_map[ir.url] = ir

        domain_map = await self._build_domain_map()

        records = []
        for dto in geoflow_dtos:
            dist = dto.distribution
            article = dto.article
            channel = dto.channel
            index_result = index_result_map.get(dist.remote_url)
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
        self,
        client_id: Optional[str] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
    ) -> list[dict]:
        """查手动录入的记录（monitor.manual_distributions）。

        日期过滤（C10 修复）：按 ``ManualDistribution.created_at`` 过滤，
        与序列化字段 ``distributed_at`` 同源。
        """
        query = select(ManualDistribution).where(ManualDistribution.status == "synced")
        if client_id:
            query = query.where(ManualDistribution.client_id == client_id)
        # C10：日期范围过滤（distributed_at = record.created_at）
        if date_from is not None:
            query = query.where(
                ManualDistribution.created_at >= _date_from_lower_bound(date_from)
            )
        if date_to is not None:
            query = query.where(
                ManualDistribution.created_at < _date_to_upper_bound(date_to)
            )
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
        修复：返回 record.content_title（原硬编码 None，导致手动录入的标题丢失）。
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
            "content_title": record.content_title,  # 修复：返回抓取到的标题
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
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
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
        date_from : datetime.date | None
            起始日期（含当天），按 ``distributed_at``（即 ``created_at``）过滤。
            None = 不限下界。C10 修复新增。
        date_to : datetime.date | None
            结束日期（含当天），按 ``distributed_at`` 过滤。
            None = 不限上界。C10 修复新增。
        """
        results = []
        if source in (None, "geoflow"):
            try:
                geoflow_records = await self._query_geoflow_distributions(
                    client_id=client_id, date_from=date_from, date_to=date_to
                )
                results.extend(geoflow_records)
            except Exception as exc:
                # 优雅降级：GEOFlow 表缺失或跨 schema 查询失败时，不阻塞手动记录加载。
                # 常见触发场景：GEOFlow migration 未跑全（article_distributions 表缺失）、
                # GEOFlow 数据库重启后表未恢复等。
                logger.warning("GEOFlow 分发查询失败，跳过 GEOFlow 记录: %s", exc)
        if include_manual and source in (None, "manual"):
            manual_records = await self._query_manual_distributions(
                client_id=client_id, date_from=date_from, date_to=date_to
            )
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

        admin_user_id / admin_name 预留用于 Task 7 审计日志接入
        （当前未引用，计划强制保留签名）。
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

        # 检查 GEOFlow 表重复（精确查询，避免拉全量 url 列表）
        # 优雅降级：GEOFlow 表缺失时跳过重复检测，不阻塞手动录入
        try:
            repo = GeoflowRepository(self.db)
            if await repo.get_synced_url_exists(remote_url):
                raise DistributionConflictError(f"URL 已存在（GEOFlow 推送）：{remote_url}")
        except DistributionConflictError:
            raise
        except Exception as exc:
            logger.warning("GEOFlow 重复检测失败，跳过: %s", exc)

        record = ManualDistribution(
            client_id=client_id,
            remote_url=remote_url,
            status="synced",
            note=note,
            created_by_admin_id=admin_user_id,
        )
        self.db.add(record)

        # P0 修复：同步创建 IndexResult 行，确保文章列表立即可见
        # （文章列表查 index_results 表，分发记录查 manual_distributions 表，
        #   不同步创建会导致"文章列表和分发记录不同步"）
        existing_index = await self.db.execute(
            select(IndexResult).where(IndexResult.url == remote_url)
        )
        if not existing_index.scalar_one_or_none():
            site_type = "manual"
            index_record = IndexResult(
                url=remote_url,
                client_id=client_id,
                site_type=site_type,
                content_title=None,  # 异步抓取后更新
            )
            self.db.add(index_record)

        await self.db.commit()

        # 标题抓取由调用方（admin_routes.py create_manual_distribution）同步处理：
        # 优先用户输入 title，否则抓取。此处不再异步触发 _fetch_and_update_title，
        # 因为异步任务会在调用方保存用户标题后覆盖掉用户填的标题（竞态条件）。
        return {"action": "created", "client_id": client_id, "source": "manual", "id": str(record.id)}

    async def _fetch_and_update_title(self, url: str, distribution_id: str) -> None:
        """异步抓取文章标题并更新 IndexResult + ManualDistribution。"""
        try:
            from app.services.article_fetcher import ArticleFetcher
            fetcher = ArticleFetcher()
            title, snapshot = await fetcher.fetch_title_and_snapshot(url)
            if title:
                # 更新 IndexResult
                await self.db.execute(
                    IndexResult.__table__.update()
                    .where(IndexResult.url == url)
                    .values(content_title=title, content_snapshot=snapshot)
                )
                # 更新 ManualDistribution
                import uuid as _uuid
                try:
                    await self.db.execute(
                        ManualDistribution.__table__.update()
                        .where(ManualDistribution.id == _uuid.UUID(distribution_id))
                        .values(content_title=title)
                    )
                except (ValueError, Exception):
                    pass
                await self.db.commit()
        except Exception:
            pass  # 标题抓取失败不影响主流程
