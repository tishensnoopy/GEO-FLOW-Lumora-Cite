"""GEOFlow schema 查询实现（防腐层内部）。

ORM 模型定义在此文件内部——防腐层自持独立的 ``GeoflowBase`` 与最小化列映射，
不依赖监测系统外的任何 GEOFlow ORM 模块。所有函数都是 async，接收
``db: AsyncSession``，返回 raw row（未映射为 DTO）。映射职责在 ``mappers.py``，
编排职责在 ``repository.py``。
"""
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    String,
    Text,
    func,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase


# ---- 防腐层内部 Base（不对外导出）----
# 独立的 ``DeclarativeBase.metadata``，与监测系统 Base 物理隔离，互不影响。
# GEOFlow schema 升级时只改这里的列定义 + mappers.py 的字段访问。


class GeoflowBase(DeclarativeBase):
    """防腐层内部 ORM 基类，与监测系统 Base 物理隔离。"""

    pass


# ---- 防腐层内部 ORM 模型（不对外导出）----
# 这些模型只在 reader.py 内部使用，是 GEOFlow schema 在防腐层内的唯一映射点。
# GEOFlow 升级改字段时，只改这里的列定义 + mappers.py 的字段访问。


class _Distribution(GeoflowBase):
    __tablename__ = "article_distributions"
    __table_args__ = {"schema": "public"}

    id = Column(BigInteger, primary_key=True)
    article_id = Column(BigInteger, nullable=True)
    remote_url = Column(String(500), nullable=True)
    status = Column(String(30), default="queued")
    action = Column(String(30), default="publish")
    distribution_channel_id = Column(BigInteger, nullable=True)
    created_at = Column(DateTime(timezone=True))


class _Article(GeoflowBase):
    __tablename__ = "articles"
    __table_args__ = {"schema": "public"}

    id = Column(BigInteger, primary_key=True)
    title = Column(String(500), nullable=False)
    slug = Column(String(500), nullable=False, unique=True)
    excerpt = Column(Text, default="")
    content = Column(Text, nullable=False)
    keywords = Column(Text, default="")
    meta_description = Column(Text, default="")
    original_keyword = Column(String(200), default="")
    published_at = Column(DateTime(timezone=True), nullable=True)


class _Channel(GeoflowBase):
    __tablename__ = "distribution_channels"
    __table_args__ = {"schema": "public"}

    id = Column(BigInteger, primary_key=True)
    name = Column(String(120), nullable=False)
    domain = Column(String(255), nullable=False)
    channel_type = Column(String(60), default="geoflow_agent")


# ---- 查询函数 ----


async def fetch_synced_distribution_urls(db: AsyncSession) -> list[str]:
    """查所有 status='synced' 且 action!='delete' 且 remote_url 非空的 url。"""
    result = await db.execute(
        select(_Distribution.remote_url).where(
            _Distribution.status == "synced",
            _Distribution.action != "delete",
            _Distribution.remote_url.isnot(None),
        )
    )
    return [row[0] for row in result.fetchall()]


async def fetch_distribution_by_ids(
    db: AsyncSession, ids: list[int]
) -> list:
    """按 id 批量查，remote_url 非空过滤。返回 ORM 行列表。"""
    if not ids:
        return []
    result = await db.execute(
        select(_Distribution).where(
            _Distribution.id.in_(ids),
            _Distribution.remote_url.isnot(None),
        )
    )
    return result.scalars().all()


async def fetch_distribution_count_by_date(
    db: AsyncSession, start_date: datetime
) -> list[tuple]:
    """按天聚合 created_at，返回 [(day, count), ...]。"""
    day_expr = func.date_trunc("day", _Distribution.created_at).label("day")
    result = await db.execute(
        select(day_expr, func.count(_Distribution.id).label("count"))
        .where(_Distribution.created_at >= start_date)
        .group_by(day_expr)
    )
    return result.fetchall()


async def fetch_distributions_with_article(
    db: AsyncSession,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> list:
    """三表 join 查询 synced 分发。不含 IndexResult——调用方自行 join。

    返回 raw row 列表，每个 row 可按 (dist, article, channel) 解包。
    """
    query = (
        select(_Distribution, _Article, _Channel)
        .join(_Article, _Article.id == _Distribution.article_id)
        .outerjoin(
            _Channel,
            _Channel.id == _Distribution.distribution_channel_id,
        )
        .where(
            _Distribution.status == "synced",
            _Distribution.action != "delete",
            _Distribution.remote_url.isnot(None),
        )
    )
    if date_from is not None:
        query = query.where(_Distribution.created_at >= date_from)
    if date_to is not None:
        query = query.where(_Distribution.created_at < date_to)
    result = await db.execute(query)
    return result.fetchall()


async def fetch_deleted_distributions_with_article(db: AsyncSession) -> list:
    """三表 join 查询 action='delete' 的分发。不含 ~exists 过滤——调用方自行处理。

    返回 raw row 列表，每个 row 可按 (dist, article, channel) 解包。
    """
    query = (
        select(_Distribution, _Article, _Channel)
        .join(_Article, _Article.id == _Distribution.article_id)
        .outerjoin(
            _Channel,
            _Channel.id == _Distribution.distribution_channel_id,
        )
        .where(
            _Distribution.action == "delete",
            _Distribution.remote_url.isnot(None),
        )
    )
    result = await db.execute(query)
    return result.fetchall()
