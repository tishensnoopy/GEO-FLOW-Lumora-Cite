"""Task 4：数据库连接配置测试（TDD RED 阶段先写）。

验证目标：
1. DATABASE_URL 默认指向 GEOFlow 的 PG（不是旧的 postgres:15-alpine 容器）；
2. DATABASE_URL 包含 GEOFlow 的数据库名（geo_flow / geoflow / geo）；
3. SSO 配置项已加入 settings，后续 SSO 任务可直接引用；
4. database.py 使用 settings.DATABASE_URL 而非自行拼接 POSTGRES_*。

设计说明
========

- 本测试只校验配置字符串，不连接真实数据库，因此即使 GEOFlow PG 容器
  尚未启动也能通过——这是 "配置意图" 测试，不是 "连通性" 测试。
- 实际连通性由 tests/integration/test_db_unified.py 通过 conftest.py
  的 db_session fixture（使用 POSTGRES_* 环境变量）覆盖。
"""
import pytest

from app.core.config import settings


# --------------------------------------------------------------------------- #
# 1. DATABASE_URL 指向 GEOFlow PG                                             #
# --------------------------------------------------------------------------- #
def test_database_url_points_to_geoflow_pg():
    """验证数据库 URL 指向 GEOFlow 的 PG（不是旧的 postgres:15-alpine）。

    默认 DATABASE_URL 应包含 GEOFlow PG 容器名（geoflow-postgres）或
    旧的 prod 容器名（geo-postgres）或本地开发的 127.0.0.1:15432。
    环境变量 DATABASE_URL 可覆盖，但默认值必须指向 GEOFlow PG，确保生产部署开箱即用。

    注：本地开发环境 DATABASE_URL 形如
    ``postgresql+asyncpg://geo_user:geo_password@127.0.0.1:15432/geo_flow``，
    数据库名 ``geo_flow`` 含 ``geo`` 但不含 ``geoflow`` 子串，故断言需兼容此格式。
    """
    db_url = settings.DATABASE_URL
    assert (
        "geo-postgres" in db_url
        or "geoflow-postgres" in db_url
        or "geo_flow" in db_url
        or "15432" in db_url  # GEOFlow PG 本地端口
    ), f"DATABASE_URL 应指向 GEOFlow PG，当前: {db_url}"


def test_database_url_has_correct_db_name():
    """验证数据库名称正确（GEOFlow 的数据库名 geo_flow）。"""
    db_url = settings.DATABASE_URL
    # GEOFlow 的数据库名通常是 geo_flow 或 geoflow
    assert any(name in db_url for name in ["geo_flow", "geoflow", "geo"]), (
        f"DATABASE_URL 应包含 GEOFlow 数据库名，当前: {db_url}"
    )


def test_database_url_uses_asyncpg_driver():
    """验证 DATABASE_URL 使用 asyncpg 驱动（与 database.py 的 async engine 兼容）。"""
    db_url = settings.DATABASE_URL
    assert "asyncpg" in db_url, (
        f"DATABASE_URL 应使用 asyncpg 驱动，当前: {db_url}"
    )


# --------------------------------------------------------------------------- #
# 2. SSO 配置项                                                               #
# --------------------------------------------------------------------------- #
def test_sso_config_fields_exist():
    """验证 SSO 配置项已加入 settings（后续 SSO 任务依赖）。"""
    assert hasattr(settings, "SSO_GEOFLOW_BASE_URL"), "settings 缺少 SSO_GEOFLOW_BASE_URL"
    assert hasattr(settings, "SSO_GEOFLOW_USERINFO_URL"), "settings 缺少 SSO_GEOFLOW_USERINFO_URL"
    assert hasattr(settings, "SSO_REDIRECT_URI"), "settings 缺少 SSO_REDIRECT_URI"
    assert hasattr(settings, "SSO_JWT_SECRET"), "settings 缺少 SSO_JWT_SECRET"
    assert hasattr(settings, "SSO_JWT_EXPIRE_DAYS"), "settings 缺少 SSO_JWT_EXPIRE_DAYS"


def test_sso_userinfo_url_derived_from_base_url():
    """SSO_GEOFLOW_USERINFO_URL 默认应基于 SSO_GEOFLOW_BASE_URL 拼接。"""
    # 默认 base url 是 zkeeeai.com，userinfo 路径是 /api/sso/userinfo
    if settings.SSO_GEOFLOW_BASE_URL == "https://zkeeeai.com":
        assert settings.SSO_GEOFLOW_USERINFO_URL == "https://zkeeeai.com/api/sso/userinfo", (
            f"SSO_GEOFLOW_USERINFO_URL 默认值应为 base_url + /api/sso/userinfo，"
            f"当前: {settings.SSO_GEOFLOW_USERINFO_URL}"
        )


def test_sso_jwt_expire_days_is_int():
    """SSO_JWT_EXPIRE_DAYS 应为整数。"""
    assert isinstance(settings.SSO_JWT_EXPIRE_DAYS, int), (
        f"SSO_JWT_EXPIRE_DAYS 应为 int，实际 {type(settings.SSO_JWT_EXPIRE_DAYS).__name__}"
    )


# --------------------------------------------------------------------------- #
# 3. database.py 使用 settings.DATABASE_URL                                   #
# --------------------------------------------------------------------------- #
def test_database_module_uses_settings_database_url():
    """验证 database.py 的 DATABASE_URL 来自 settings.DATABASE_URL。

    确保配置单一事实来源——database.py 不再自行拼接 POSTGRES_*。
    """
    from app.core import database

    assert database.DATABASE_URL == settings.DATABASE_URL, (
        f"database.DATABASE_URL 应等于 settings.DATABASE_URL，"
        f"实际 database={database.DATABASE_URL} settings={settings.DATABASE_URL}"
    )
