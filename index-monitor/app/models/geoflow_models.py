"""GEOFlow 表的只读 SQLAlchemy 模型，用于监测系统跨 schema 查询。

设计说明
========

1. 这些模型映射到 GEOFlow 的 ``public`` schema 表，监测系统只读不写。
2. 使用独立的 :class:`GeoflowBase`，不继承监测系统的 :class:`app.models.base.Base`，
   避免 ``DeclarativeBase.metadata`` 共享导致 alembic autogenerate 把 GEOFlow
   表误当作监测系统迁移目标。
3. 字段定义以 ``GEOFlow-main/database/migrations/`` 下的迁移文件为唯一事实来源，
   而非简报中的假设。变更字段前必须先核对对应 migration。
4. 与简报假设不一致的几处关键差异：
   - ``articles.keywords`` 在 migration 中是 ``TEXT``，**不是 JSON**。
   - ``article_distributions`` 的外键字段叫 ``distribution_channel_id``，
     **不是简报假设的 ``channel_id``**；``status`` 默认 ``'queued'``，
     ``action`` 默认 ``'publish'``。
   - GEOFlow 用户表实际叫 ``admins``（不是 ``users``），SSO 认证读 ``admins``。
     模型类名相应取 ``GeoflowAdmin``。
   - ``articles`` 表后追加 ``is_hot`` / ``is_featured`` 布尔字段
     （见 ``2026_04_26_121000_add_promotion_flags_to_articles_table.php``）。
   - ``distribution_channels`` 后追加 ``front_mode`` 字段
     （见 ``2026_05_20_000000_add_front_mode_and_publish_scope_to_distribution.php``）。

字段事实来源
============

- ``articles``: ``2026_04_18_120000_geoflow_legacy_schema.php`` +
  ``2026_04_26_121000_add_promotion_flags_to_articles_table.php``
- ``article_distributions``: ``2026_05_17_000000_create_distribution_management_tables.php`` +
  ``2026_05_23_000000_add_wordpress_distribution_columns.php`` +
  ``2026_05_18_180000_align_distribution_management_tables.php``
- ``distribution_channels``: ``2026_05_17_000000_create_distribution_management_tables.php`` +
  ``2026_05_19_000000_add_site_settings_to_distribution_channels.php`` +
  ``2026_05_20_000000_add_front_mode_and_publish_scope_to_distribution.php`` +
  ``2026_05_23_000000_add_wordpress_distribution_columns.php``
- ``admins``: ``2026_04_18_100000_create_geoflow_admins_and_site_settings_tables.php`` +
  ``2026_04_18_130000_add_remember_token_to_admins_table.php`` +
  ``2026_04_23_000000_add_welcome_fields_to_admins_table.php``
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
    """GEOFlow 只读模型的独立基类。

    与监测系统的 :class:`app.models.base.Base` 隔离 ``metadata``，避免监测系统
    alembic 把 GEOFlow 的 ``public`` schema 表纳入迁移管理。所有 GEOFlow 模型
    通过 ``__table_args__ = {"schema": "public"}`` 显式归属 ``public`` schema。
    """

    pass


class GeoflowArticle(GeoflowBase):
    """GEOFlow 文章表（``public.articles``），监测系统只读。"""

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
    keywords = Column(Text, default="")  # 注意：TEXT，不是 JSON
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
    """GEOFlow 文章分发表（``public.article_distributions``），监测系统只读。

    注意外键字段名为 ``distribution_channel_id``，不是 ``channel_id``。
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
    """GEOFlow 分发渠道表（``public.distribution_channels``），监测系统只读。"""

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
    """GEOFlow 管理员表（``public.admins``），SSO 认证读取。

    GEOFlow 用 ``admins`` 表（不是 ``users``）。
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
