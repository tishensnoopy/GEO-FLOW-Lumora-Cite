"""Dashboard 趋势数据 API。

为前端 StatCard 的 sparkline 和同比提供 30 天历史数据。

设计说明
========

1. 路由前缀 ``/admin/dashboard``，配合 main.py 的 ``/api/v1`` 前缀，
   最终路径为 ``/api/v1/admin/dashboard/trend``。
2. 任何子查询失败时降级为空数组（返回 [0]*days），保证接口始终 200 不 500。
3. 数据源（已根据实际模型适配，与简报假设不一致处以实际模型为准）：
   - 分发趋势：ManualDistribution（monitor.manual_distributions）
     + GeoflowArticleDistribution（public.article_distributions，跨 schema 只读）
     —— 简报假设的 ``geoflow_article_distribution`` 模块不存在，实际在
     ``app.models.geoflow_models`` 中。
   - 收录趋势：IndexHistory.total_indexed 按 check_date 日聚合
     —— 简报上下文称 IndexHistory 不存在，实际它在 ``app.models.index_result``
     模块中（与 IndexResult 同文件），有 check_date(Date) + total_indexed(Integer)。
   - 采信趋势：CitationResult.hit_type != 'none' 按 created_at 日聚合
     —— hit_type 字段实际存在（String(32)，可空索引）。
   - 收录率：每日 indexed / distributions * 100（distributions 为 0 时记 0）。
4. 日期对齐：以 UTC 当日 date 为 key，查询结果按 date_trunc('day', ...) 后
   统一转 UTC date，避免时区错位导致漏填。
"""
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_admin
from app.core.database import get_db
from app.models.citation_result import CitationResult
from app.models.geoflow_models import GeoflowArticleDistribution
from app.models.index_result import IndexHistory
from app.models.manual_distribution import ManualDistribution

router = APIRouter(prefix="/admin/dashboard", tags=["dashboard"])


def _to_date(value) -> date | None:
    """把 SQL 查询返回的 date / aware datetime 统一转换为 Python ``date``。

    - ``datetime`` aware：astimezone(UTC) 后取 date，避免 DB session 时区偏移
      导致日期被错位到前一天；
    - ``datetime`` naive：直接取 date（PostgreSQL ``timestamp without time zone``
      场景，按服务器本地时区解释，足够近似）；
    - ``date``：原样返回（``IndexHistory.check_date`` 即 DATE 类型）。
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            return value.astimezone(timezone.utc).date()
        return value.date()
    if isinstance(value, date):
        return value
    return None


@router.get("/trend")
async def get_dashboard_trend(
    days: int = Query(30, ge=1, le=90),
    admin: dict = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """返回最近 ``days`` 天趋势数据，用于 StatCard sparkline 和同比计算。

    返回结构::

        {
          "distributions": {"daily": [...], "total": N, "change_pct": 12.0},
          "indexed":        {"daily": [...], "total": N},
          "citations":      {"daily": [...], "total": N},
          "index_rate":     {"daily": [...], "current": 73.4}
        }

    任何子查询失败时该维度降级为 ``[0]*days``，确保接口始终返回 200。
    """
    now = datetime.now(timezone.utc)
    start_date = now - timedelta(days=days)

    # 最近 days 天的日期序列（含今天）。
    # 用 now 反推而非 start_date 正推，确保序列尾部对齐"今天"，与前端 sparkline
    # 末位 = 今天的视觉预期一致。
    date_seq = [(now - timedelta(days=days - 1 - i)).date() for i in range(days)]
    date_set = set(date_seq)

    # ---- 1. 分发趋势（manual + geoflow，按日聚合 created_at）----
    dist_daily_map: dict[date, int] = {d: 0 for d in date_seq}

    try:
        day_expr = func.date_trunc("day", ManualDistribution.created_at).label("day")
        manual_rows = await db.execute(
            select(day_expr, func.count(ManualDistribution.id).label("count"))
            .where(ManualDistribution.created_at >= start_date)
            .group_by(day_expr)
        )
        for row in manual_rows:
            d = _to_date(row.day)
            if d in date_set:
                dist_daily_map[d] += int(row.count)
    except Exception:
        # 降级：保留全 0 数组
        pass

    try:
        day_expr = func.date_trunc("day", GeoflowArticleDistribution.created_at).label("day")
        geoflow_rows = await db.execute(
            select(day_expr, func.count(GeoflowArticleDistribution.id).label("count"))
            .where(GeoflowArticleDistribution.created_at >= start_date)
            .group_by(day_expr)
        )
        for row in geoflow_rows:
            d = _to_date(row.day)
            if d in date_set:
                dist_daily_map[d] += int(row.count)
    except Exception:
        pass

    dist_daily = [dist_daily_map[d] for d in date_seq]

    # 同比：本周 vs 上周（最近 7 天 vs 再前 7 天）
    this_week = sum(dist_daily[-7:])
    last_week = sum(dist_daily[-14:-7]) if len(dist_daily) >= 14 else 0
    dist_change = (
        ((this_week - last_week) / last_week * 100) if last_week > 0 else 0.0
    )

    # ---- 2. 收录数趋势（IndexHistory.total_indexed 按 check_date 聚合）----
    indexed_daily_map: dict[date, int] = {d: 0 for d in date_seq}
    try:
        indexed_rows = await db.execute(
            select(
                IndexHistory.check_date.label("day"),
                func.sum(IndexHistory.total_indexed).label("count"),
            )
            .where(IndexHistory.check_date >= start_date.date())
            .group_by(IndexHistory.check_date)
        )
        for row in indexed_rows:
            d = _to_date(row.day)
            if d in date_set:
                indexed_daily_map[d] += int(row.count or 0)
    except Exception:
        pass

    indexed_daily = [indexed_daily_map[d] for d in date_seq]

    # ---- 3. 采信数趋势（CitationResult hit_type != 'none'）----
    citation_daily_map: dict[date, int] = {d: 0 for d in date_seq}
    try:
        day_expr = func.date_trunc("day", CitationResult.created_at).label("day")
        citation_rows = await db.execute(
            select(day_expr, func.count(CitationResult.id).label("count"))
            .where(
                and_(
                    CitationResult.created_at >= start_date,
                    CitationResult.hit_type != "none",
                )
            )
            .group_by(day_expr)
        )
        for row in citation_rows:
            d = _to_date(row.day)
            if d in date_set:
                citation_daily_map[d] += int(row.count)
    except Exception:
        pass

    citation_daily = [citation_daily_map[d] for d in date_seq]

    # ---- 4. 收录率趋势（每日 indexed / total * 100；total=0 时记 0）----
    rate_daily = []
    for i in range(days):
        total = dist_daily[i]
        idx = indexed_daily[i]
        rate = round(idx / total * 100, 1) if total > 0 else 0.0
        rate_daily.append(rate)

    return {
        "distributions": {
            "daily": dist_daily,
            "total": sum(dist_daily),
            "change_pct": round(dist_change, 1),
        },
        "indexed": {
            "daily": indexed_daily,
            "total": sum(indexed_daily),
        },
        "citations": {
            "daily": citation_daily,
            "total": sum(citation_daily),
        },
        "index_rate": {
            "daily": rate_daily,
            "current": rate_daily[-1] if rate_daily else 0,
        },
    }
