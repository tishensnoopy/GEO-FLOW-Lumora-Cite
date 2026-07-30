"""客户端只读 API 路由。

所有端点用 get_current_client_id 鉴权，client_id 强制从 JWT 取。
数据范围限制：仅返回该客户自己的数据，隐藏 pending/not_indexed/未引用。
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func, case
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_client_id
from app.core.database import get_db
from app.integration.geoflow import GeoflowRepository
from app.models.ai_index_result import AIIndexResult
from app.models.citation_result import CitationResult
from app.models.manual_distribution import ManualDistribution
from app.models.client import ClientSite
from app.models.index_result import IndexResult
from app.utils.validators import normalize_domain

logger = logging.getLogger(__name__)
router = APIRouter()


async def _get_client_urls(db: AsyncSession, client_id: str) -> set[str]:
    """获取属于该客户的所有 URL（手动录入 + GEOFlow 分发匹配 ClientSite）。"""
    # 1. 手动录入
    manual = await db.execute(
        select(ManualDistribution.remote_url).where(
            ManualDistribution.client_id == client_id,
            ManualDistribution.status == "synced",
        )
    )
    urls = {row[0] for row in manual.fetchall() if row[0]}

    # 2. GEOFlow 分发（按 ClientSite.domain 匹配）
    try:
        repo = GeoflowRepository(db)
        geoflow_urls = await repo.get_synced_distribution_urls()
        sites = await db.execute(
            select(ClientSite).where(
                ClientSite.client_id == client_id,
                ClientSite.status == "active",
            )
        )
        domains = {normalize_domain(s.domain) for s in sites.scalars().all()}
        urls.update(u for u in geoflow_urls if normalize_domain(u) in domains)
    except Exception as exc:
        # asyncpg 在查询失败后会把当前事务置为 aborted 状态，后续 SQL 全部报
        # "current transaction is aborted" —— 必须 rollback 才能继续用此 session。
        # 本端点为只读，rollback 不会丢数据；上面 manual 查询结果已在 urls 集合中。
        await db.rollback()
        logger.warning("客户端 URL 归属判定-GEOFlow 查询失败: %s", exc)

    return urls


@router.get("/ai-index/overview")
async def ai_index_overview(
    client_id: str = Depends(get_current_client_id),
    db: AsyncSession = Depends(get_db),
):
    """我的收录概览（仅已收录，简化）。"""
    if client_id == "admin":
        raise HTTPException(status_code=403, detail="本端点仅供客户使用")

    client_urls = await _get_client_urls(db, client_id)
    if not client_urls:
        return {"total_indexed": 0, "total_not_indexed": 0, "index_rate": 0, "articles": []}

    # 查该客户 URL 的收录结果
    result = await db.execute(
        select(AIIndexResult).where(AIIndexResult.url.in_(client_urls))
    )
    all_records = result.scalars().all()

    indexed_urls = {r.url for r in all_records if r.index_status == "indexed"}
    total_indexed = len(indexed_urls)
    total_not_indexed = len({r.url for r in all_records if r.index_status == "not_indexed"})
    index_rate = total_indexed / (total_indexed + total_not_indexed) if (total_indexed + total_not_indexed) > 0 else 0

    # 获取 URL → title 映射（I2 修复：与 citation_evidence 对齐，补全 title 字段）
    indexed_url_set = {r.url for r in all_records if r.index_status == "indexed"}
    title_map: dict[str, str] = {}
    if indexed_url_set:
        title_result = await db.execute(
            select(IndexResult.url, IndexResult.content_title).where(
                IndexResult.url.in_(indexed_url_set)
            )
        )
        title_map = {row[0]: row[1] or "" for row in title_result.fetchall()}

    # 仅返回 indexed 的文章（隐藏 pending/not_indexed 详情）
    articles = [
        {
            "url": r.url,
            "title": title_map.get(r.url) or "",
            "model": r.model,
            "index_status": r.index_status,
            "checked_at": r.checked_at.isoformat() if r.checked_at else None,
        }
        for r in all_records
        if r.index_status == "indexed"
    ]

    return {
        "total_indexed": total_indexed,
        "total_not_indexed": total_not_indexed,
        "index_rate": index_rate,
        "articles": articles,
    }


@router.get("/citations/evidence")
async def citation_evidence(
    client_id: str = Depends(get_current_client_id),
    db: AsyncSession = Depends(get_db),
):
    """我的引用证据（仅被引用的 Q&A，hit_type != 'none'）。"""
    if client_id == "admin":
        raise HTTPException(status_code=403, detail="本端点仅供客户使用")

    client_urls = await _get_client_urls(db, client_id)
    if not client_urls:
        return []

    result = await db.execute(
        select(CitationResult).where(
            CitationResult.url.in_(client_urls),
            CitationResult.hit_type != "none",
        ).order_by(CitationResult.created_at.desc())
    )
    records = result.scalars().all()

    # 获取 URL → title 映射
    title_result = await db.execute(
        select(IndexResult.url, IndexResult.content_title).where(
            IndexResult.url.in_({r.url for r in records})
        )
    )
    title_map = {row[0]: row[1] for row in title_result.fetchall()}

    return [
        {
            "id": str(r.id),
            "url": r.url,
            "title": title_map.get(r.url, ""),
            "model": r.model,
            "question": r.question,
            "answer": r.answer,
            "hit_type": r.hit_type,
            "sources": r.sources,
            "checked_at": r.checked_at.isoformat() if r.checked_at else None,
        }
        for r in records
    ]


@router.get("/stats")
async def client_stats(
    client_id: str = Depends(get_current_client_id),
    db: AsyncSession = Depends(get_db),
):
    """我的统计卡片数据。"""
    if client_id == "admin":
        raise HTTPException(status_code=403, detail="本端点仅供客户使用")

    client_urls = await _get_client_urls(db, client_id)
    if not client_urls:
        return {
            "ai_indexed_count": 0,
            "ai_cited_count": 0,
            "ai_mention_rate": 0,
            "total_articles": 0,
            "index_rate": 0,
        }

    # AI 收录数（distinct URL with indexed）
    indexed_result = await db.execute(
        select(func.count(func.distinct(AIIndexResult.url))).where(
            AIIndexResult.url.in_(client_urls),
            AIIndexResult.index_status == "indexed",
        )
    )
    ai_indexed_count = indexed_result.scalar() or 0

    # AI 提及数（distinct URL with cited）
    cited_result = await db.execute(
        select(func.count(func.distinct(CitationResult.url))).where(
            CitationResult.url.in_(client_urls),
            CitationResult.hit_type != "none",
        )
    )
    ai_cited_count = cited_result.scalar() or 0

    # AI 提及率
    ai_mention_rate = ai_cited_count / ai_indexed_count if ai_indexed_count > 0 else 0

    # 文章总数
    total_articles = len(client_urls)

    # 搜索引擎收录率
    idx_result = await db.execute(
        select(
            func.count(IndexResult.id).label("total"),
            func.sum(case(
                ((IndexResult.baidu_status == "indexed")
                 | (IndexResult.toutiao_status == "indexed")
                 | (IndexResult.sogou_status == "indexed")
                 | (IndexResult.so360_status == "indexed")
                 | (IndexResult.bing_status == "indexed"), 1),
                else_=0,
            )).label("indexed"),
        ).where(IndexResult.url.in_(client_urls))
    )
    row = idx_result.one()
    idx_total = row.total or 0
    idx_indexed = int(row.indexed or 0)
    index_rate = idx_indexed / idx_total if idx_total > 0 else 0

    return {
        "ai_indexed_count": ai_indexed_count,
        "ai_cited_count": ai_cited_count,
        "ai_mention_rate": ai_mention_rate,
        "total_articles": total_articles,
        "index_rate": index_rate,
    }
