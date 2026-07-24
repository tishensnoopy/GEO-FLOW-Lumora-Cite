"""Task 3：GEOFlow 只读模型跨 schema 查询测试（TDD RED 阶段先写）。

验证目标：
1. GEOFlow 只读模型映射到 public schema（与监测系统 monitor schema 隔离）；
2. GeoflowBase 与监测系统 Base 相互独立（DeclarativeBase.metadata 不共享）；
3. 模型字段与 GEOFlow Laravel migration 实际 schema 一致；
4. 只读约定：模型不引入写操作（通过限制主键自增不参与 monitor alembic）。

字段事实来源：GEOFlow-main/database/migrations/ 下的迁移文件，而非简报中的假设。
"""
import pytest
from sqlalchemy import inspect
from sqlalchemy.orm import DeclarativeBase

from app.models.base import Base as MonitorBase
from app.models.geoflow_models import (
    GeoflowAdmin,
    GeoflowArticle,
    GeoflowArticleDistribution,
    GeoflowBase,
    GeoflowDistributionChannel,
)


# --------------------------------------------------------------------------- #
# 1. schema 归属                                                              #
# --------------------------------------------------------------------------- #
def test_geoflow_article_model_schema():
    """验证 GEOFlow Article 模型在 public schema 下。"""
    assert GeoflowArticle.__table__.schema == "public"


def test_geoflow_article_distribution_model_schema():
    """验证 GEOFlow ArticleDistribution 模型在 public schema 下。"""
    assert GeoflowArticleDistribution.__table__.schema == "public"


def test_geoflow_distribution_channel_model_schema():
    """验证 GEOFlow DistributionChannel 模型在 public schema 下。"""
    assert GeoflowDistributionChannel.__table__.schema == "public"


def test_geoflow_admin_model_schema():
    """验证 GEOFlow Admin 模型在 public schema 下。"""
    assert GeoflowAdmin.__table__.schema == "public"


# --------------------------------------------------------------------------- #
# 2. GeoflowBase 与监测系统 Base 独立                                         #
# --------------------------------------------------------------------------- #
def test_geoflow_base_is_declarative_base_subclass():
    """GeoflowBase 必须是 DeclarativeBase 子类。"""
    assert issubclass(GeoflowBase, DeclarativeBase)


def test_geoflow_base_metadata_independent_from_monitor_base():
    """GeoflowBase 与 MonitorBase 的 metadata 必须是不同对象，避免表注册冲突。"""
    assert GeoflowBase.metadata is not MonitorBase.metadata


def test_geoflow_models_register_in_geoflow_metadata_only():
    """GEOFlow 模型只注册到 GeoflowBase.metadata，不污染 MonitorBase.metadata。"""
    geoflow_table_names = set(GeoflowBase.metadata.tables.keys())
    monitor_table_names = set(MonitorBase.metadata.tables.keys())

    # public schema 表全在 GeoflowBase 下
    assert "public.articles" in geoflow_table_names
    assert "public.article_distributions" in geoflow_table_names
    assert "public.distribution_channels" in geoflow_table_names
    assert "public.admins" in geoflow_table_names

    # 监测系统 metadata 不应包含 GEOFlow 表
    assert "public.articles" not in monitor_table_names
    assert "public.article_distributions" not in monitor_table_names
    assert "public.distribution_channels" not in monitor_table_names
    assert "public.admins" not in monitor_table_names


# --------------------------------------------------------------------------- #
# 3. 表名                                                                     #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "model,expected",
    [
        (GeoflowArticle, "articles"),
        (GeoflowArticleDistribution, "article_distributions"),
        (GeoflowDistributionChannel, "distribution_channels"),
        (GeoflowAdmin, "admins"),
    ],
)
def test_geoflow_tablename(model, expected):
    """表名必须与 GEOFlow Laravel migration 一致（admins 不是 users）。"""
    assert model.__tablename__ == expected


# --------------------------------------------------------------------------- #
# 4. 字段对齐 GEOFlow migration 实际 schema                                   #
# --------------------------------------------------------------------------- #
def test_geoflow_article_has_required_fields():
    """验证 GEOFlow Article 模型有监测系统需要的字段。

    字段集来自 2026_04_18_120000_geoflow_legacy_schema.php 与
    2026_04_26_121000_add_promotion_flags_to_articles_table.php。
    注意：keywords 在 migration 中是 TEXT，不是 JSON。
    """
    columns = GeoflowArticle.__table__.columns
    required = [
        "id",
        "title",
        "slug",
        "content",
        "excerpt",
        "keywords",
        "meta_description",
        "original_keyword",
        "published_at",
        # 监测系统也会读取的实际字段
        "category_id",
        "author_id",
        "task_id",
        "status",
        "review_status",
        "view_count",
        "is_ai_generated",
        "is_hot",
        "is_featured",
        "created_at",
        "updated_at",
        "deleted_at",
    ]
    for field in required:
        assert field in columns.keys(), f"GeoflowArticle 缺少字段: {field}"


def test_geoflow_article_keywords_is_text_not_json():
    """keywords 字段在 migration 中是 TEXT，不是 JSON（简报假设有误）。"""
    keywords_col = GeoflowArticle.__table__.columns["keywords"]
    # String/Text 类型族；不能是 JSON 类型
    type_name = type(keywords_col.type).__name__.upper()
    assert type_name in {"TEXT", "VARCHAR", "STRING"}, (
        f"keywords 字段类型应为 TEXT，实际 {type_name}"
    )
    assert type_name != "JSON"


def test_geoflow_article_distribution_has_required_fields():
    """验证 GEOFlow ArticleDistribution 模型字段。

    字段集来自 2026_05_17_000000_create_distribution_management_tables.php
    和 2026_05_23_000000_add_wordpress_distribution_columns.php。

    重要：外键字段名是 distribution_channel_id（不是简报假设的 channel_id）。
    """
    columns = GeoflowArticleDistribution.__table__.columns
    required = [
        "id",
        "article_id",
        "distribution_channel_id",
        "action",
        "status",
        "remote_id",
        "remote_url",
        "remote_meta",
        "idempotency_key",
        "attempt_count",
        "next_retry_at",
        "last_attempt_at",
        "last_error_message",
        "payload_hash",
        "created_at",
        "updated_at",
    ]
    for field in required:
        assert field in columns.keys(), (
            f"GeoflowArticleDistribution 缺少字段: {field}"
        )


def test_geoflow_article_distribution_no_channel_id_alias():
    """简报假设 channel_id 字段不存在；实际外键叫 distribution_channel_id。"""
    columns = GeoflowArticleDistribution.__table__.columns
    assert "channel_id" not in columns.keys(), (
        "article_distributions 表无 channel_id 字段，应为 distribution_channel_id"
    )


def test_geoflow_distribution_channel_has_required_fields():
    """验证 GEOFlow DistributionChannel 模型字段。

    字段集来自 2026_05_17_000000、2026_05_19_000000、2026_05_20_000000、
    2026_05_23_000000 四个 migration 的合并结果。
    """
    columns = GeoflowDistributionChannel.__table__.columns
    required = [
        "id",
        "name",
        "domain",
        "endpoint_url",
        "channel_type",
        "front_mode",
        "template_key",
        "site_settings",
        "channel_config",
        "status",
        "description",
        "last_health_status",
        "last_health_checked_at",
        "last_error_message",
        "created_by_admin_id",
        "created_at",
        "updated_at",
    ]
    for field in required:
        assert field in columns.keys(), (
            f"GeoflowDistributionChannel 缺少字段: {field}"
        )


def test_geoflow_admin_has_required_fields():
    """验证 GEOFlow Admin 模型字段（SSO 认证读取）。

    字段集来自 2026_04_18_100000_create_geoflow_admins_and_site_settings_tables.php、
    2026_04_18_130000_add_remember_token_to_admins_table.php、
    2026_04_23_000000_add_welcome_fields_to_admins_table.php。
    """
    columns = GeoflowAdmin.__table__.columns
    required = [
        "id",
        "username",
        "password",
        "email",
        "display_name",
        "role",
        "status",
        "created_by",
        "last_login",
        "welcome_seen_version",
        "welcome_dismissed_at",
        "remember_token",
        "created_at",
        "updated_at",
    ]
    for field in required:
        assert field in columns.keys(), f"GeoflowAdmin 缺少字段: {field}"


# --------------------------------------------------------------------------- #
# 5. JSON 字段类型确认（用于跨 schema 查询时的反序列化）                       #
# --------------------------------------------------------------------------- #
def test_geoflow_distribution_channel_json_columns():
    """site_settings / channel_config 在 migration 中是 JSON 类型。"""
    table = GeoflowDistributionChannel.__table__
    assert type(table.columns["site_settings"].type).__name__.upper() == "JSON"
    assert type(table.columns["channel_config"].type).__name__.upper() == "JSON"


def test_geoflow_article_distribution_remote_meta_is_json():
    """remote_meta 在 migration 中是 JSON 类型。"""
    col = GeoflowArticleDistribution.__table__.columns["remote_meta"]
    assert type(col.type).__name__.upper() == "JSON"


# --------------------------------------------------------------------------- #
# 6. 只读约定：模型不带主键自增、不带 monitor alembic 版本污染                  #
# --------------------------------------------------------------------------- #
def test_geoflow_models_not_in_monitor_metadata():
    """GEOFlow 模型不应出现在监测系统的 alembic 版本表中（只读跨 schema 查询）。"""
    # 反向验证：监测系统的所有模型表都在 monitor schema 下
    for name, table in MonitorBase.metadata.tables.items():
        assert table.schema == "monitor", (
            f"监测系统 metadata 中出现非 monitor schema 表 {name!r} (schema={table.schema!r})"
        )


def test_geoflow_table_count_in_metadata():
    """GeoflowBase.metadata 恰好包含 4 张 public schema 表。"""
    public_tables = {
        name for name, table in GeoflowBase.metadata.tables.items()
        if table.schema == "public"
    }
    assert public_tables == {
        "public.articles",
        "public.article_distributions",
        "public.distribution_channels",
        "public.admins",
    }
