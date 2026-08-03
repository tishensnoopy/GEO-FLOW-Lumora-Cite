# index-monitor/tests/_geoflow_test_models.py
"""GEOFlow 表的测试替身 ORM 模型（仅测试用）。

用途
====

任务 11 删除 ``app/models/geoflow_models.py`` 后，生产代码通过防腐层
（``app/integration/geoflow/``）访问 GEOFlow schema，不再直接持有 ORM 模型。
但测试需要向 ``public`` schema 的 GEOFlow 表播种数据以验证业务逻辑，因此
本模块提供与 GEOFlow 真实 migration 等价的 ORM 模型，**仅供测试使用**：

- 建表：``GeoflowBase.metadata.create_all(engine)`` 创建 public schema 表
- 播种：``db_session.add(GeoflowArticle(...))`` 写入测试数据
- 查询：``select(GeoflowArticleDistribution, ...)`` 跨 schema JOIN 断言

与防腐层的关系
==============

- 防腐层 ``reader.py`` 内部有自己的私有 ORM 模型（``_Distribution`` /
  ``_Article`` / ``_Channel``），列定义最小化（只含查询用到的列），
  且拥有独立的 ``DeclarativeBase.metadata``，与这里的测试替身物理隔离。
- 本模块的模型是 **完整 schema**（对齐 GEOFlow Laravel migration），
  用于建表和播种——测试需要真实表结构才能验证业务逻辑。
- 两套模型映射到同样的物理表但归属不同 metadata，互不冲突。

字段事实来源
============

- ``articles``: ``2026_04_18_120000_geoflow_legacy_schema.php`` +
  ``2026_04_26_121000_add_promotion_flags_to_articles_table.php``
- ``article_distributions``: ``2026_05_17_000000_create_distribution_management_tables.php`` +
  ``2026_05_23_000000_add_wordpress_distribution_columns.php`` +
  ``2026_05_18_180000_align_distribution_management_tables.php``
- ``distribution_channels``: ``2026_05_17_000000`` + ``2026_05_19_000000`` +
  ``2026_05_20_000000`` + ``2026_05_23_000000``
- ``admins``: ``2026_04_18_100000`` + ``2026_04_18_130000`` + ``2026_04_23_000000``

注意：``articles.keywords`` 在 migration 中是 ``TEXT``（不是 JSON）；
``article_distributions`` 外键字段名是 ``distribution_channel_id``（不是 ``channel_id``）；
GEOFlow 用户表叫 ``admins``（不是 ``users``）。
"""
from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import DeclarativeBase


class GeoflowBase(DeclarativeBase):
    """测试替身 ORM 基类——独立 metadata，与监测系统 Base 物理隔离。"""

    pass


class GeoflowArticle(GeoflowBase):
    """GEOFlow 文章表（``public.articles``）测试替身。"""

    __tablename__ = "articles"
    __table_args__ = {"schema": "public"}

    id = Column(BigInteger, primary_key=True)
    title = Column(String(500), nullable=False)
    slug = Column(String(500), nullable=False, unique=True)
    excerpt = Column(Text, default="")
    content = Column(Text, nullable=False)
    category_id = Column(BigInteger, nullable=False)
    author_id = Column(BigInteger, nullable=False)
    task_id = Column(BigInteger, nullable=True)
    original_keyword = Column(String(200), default="")
    keywords = Column(Text, default="")  # TEXT，不是 JSON
    meta_description = Column(Text, default="")
    status = Column(String(20), default="draft")
    review_status = Column(String(20), default="pending")
    view_count = Column(Integer, default=0)
    is_ai_generated = Column(Integer, default=0)
    is_hot = Column(Boolean, default=False)
    is_featured = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True))
    updated_at = Column(DateTime(timezone=True))
    published_at = Column(DateTime(timezone=True), nullable=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)


class GeoflowArticleDistribution(GeoflowBase):
    """GEOFlow 文章分发表（``public.article_distributions``）测试替身。

    外键字段名为 ``distribution_channel_id``，不是 ``channel_id``。
    """

    __tablename__ = "article_distributions"
    __table_args__ = {"schema": "public"}

    id = Column(BigInteger, primary_key=True)
    article_id = Column(BigInteger, nullable=False)
    distribution_channel_id = Column(BigInteger, nullable=False)
    action = Column(String(30), default="publish")
    status = Column(String(30), default="queued", index=True)
    remote_id = Column(String(120), nullable=True)
    remote_url = Column(String(500), nullable=True)
    remote_meta = Column(JSON, nullable=True)
    idempotency_key = Column(String(120), unique=True)
    attempt_count = Column(Integer, default=0)
    next_retry_at = Column(DateTime(timezone=True), nullable=True)
    last_attempt_at = Column(DateTime(timezone=True), nullable=True)
    last_error_message = Column(Text, nullable=True)
    payload_hash = Column(String(64), nullable=True)
    created_at = Column(DateTime(timezone=True))
    updated_at = Column(DateTime(timezone=True))


class GeoflowDistributionChannel(GeoflowBase):
    """GEOFlow 分发渠道表（``public.distribution_channels``）测试替身。"""

    __tablename__ = "distribution_channels"
    __table_args__ = {"schema": "public"}

    id = Column(BigInteger, primary_key=True)
    name = Column(String(120), nullable=False)
    domain = Column(String(255), nullable=False)
    endpoint_url = Column(String(500), nullable=False)
    channel_type = Column(String(60), default="geoflow_agent")
    front_mode = Column(String(30), default="static")
    template_key = Column(String(120), nullable=True)
    site_settings = Column(JSON, nullable=True)
    channel_config = Column(JSON, nullable=True)
    status = Column(String(30), default="active", index=True)
    description = Column(Text, nullable=True)
    last_health_status = Column(String(30), nullable=True)
    last_health_checked_at = Column(DateTime(timezone=True), nullable=True)
    last_error_message = Column(Text, nullable=True)
    created_by_admin_id = Column(BigInteger, nullable=True, index=True)
    created_at = Column(DateTime(timezone=True))
    updated_at = Column(DateTime(timezone=True))


class GeoflowAdmin(GeoflowBase):
    """GEOFlow 管理员表（``public.admins``）测试替身。

    GEOFlow 用 ``admins`` 表（不是 ``users``），SSO 认证读取。
    """

    __tablename__ = "admins"
    __table_args__ = {"schema": "public"}

    id = Column(BigInteger, primary_key=True)
    username = Column(String(50), nullable=False, unique=True)
    password = Column(String(255), nullable=False)
    email = Column(String(100), default="")
    display_name = Column(String(100), default="")
    role = Column(String(20), default="admin")
    status = Column(String(20), default="active")
    created_by = Column(BigInteger, nullable=True)
    last_login = Column(DateTime(timezone=True), nullable=True)
    welcome_seen_version = Column(String(120), nullable=True)
    welcome_dismissed_at = Column(DateTime(timezone=True), nullable=True)
    remember_token = Column(String(100), nullable=True)
    created_at = Column(DateTime(timezone=True))
    updated_at = Column(DateTime(timezone=True))


def seed_geoflow_base_data(engine) -> None:
    """预置 GEOFlow 基础数据（authors id=1 + categories id=1）。

    ``articles`` 表有外键约束 ``articles_author_id_fkey`` 和
    ``articles_category_id_fkey``，测试播种 ``GeoflowArticle(author_id=1,
    category_id=1)`` 时若 ``authors``/``categories`` 表无对应记录会触发
    IntegrityError。本函数在建表后插入 id=1 的基础行（ON CONFLICT DO NOTHING
    幂等），保证外键约束满足。

    用 raw SQL 而非 ORM——``authors``/``categories`` 不在 ``GeoflowBase``
    metadata 中（真实表由 GEOFlow Laravel migration 创建），且只需最小列集。
    """
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO public.authors (id, name) VALUES (1, '测试作者') "
                "ON CONFLICT (id) DO NOTHING"
            )
        )
        conn.execute(
            text(
                "INSERT INTO public.categories (id, name, slug) "
                "VALUES (1, '测试分类', 'test-category') "
                "ON CONFLICT (id) DO NOTHING"
            )
        )
