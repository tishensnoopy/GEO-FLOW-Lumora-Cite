# index-monitor/tests/unit/test_monitor_db_config.py
"""改进 2：config.py 可选 MONITOR_DB_USER 配置测试（TDD RED 阶段先写）。

验证目标
========
1. ``MONITOR_DB_USER`` / ``MONITOR_DB_PASSWORD`` 默认 ``None``（未启用 DB 层隔离，
   向后兼容继续用 ``POSTGRES_USER``）。
2. 默认 ``DATABASE_URL`` 含 ``geo_user``（POSTGRES_USER）。
3. 设置 ``MONITOR_DB_USER`` + ``MONITOR_DB_PASSWORD`` 时，``DATABASE_URL`` 重建
   使用 ``monitor_user`` 凭据，host/port/db 仍取自 ``POSTGRES_*``。
4. 设置 ``MONITOR_DB_USER`` 但不设密码时，回退 ``POSTGRES_PASSWORD``。

设计说明
========
- 不连接真实 DB，只校验配置派生逻辑——纯单元测试。
- 构造独立 ``Settings()`` 实例（不复用模块级 ``settings`` 单例），避免被环境变量
  污染断言；显式传 kwargs 覆盖 env。
- ``MONITOR_DB_USER`` 是启用 DB 层权限隔离的开关：设了就用 monitor_user，
  没设就用 geo_user（向后兼容，部署侧按需启用）。
"""
import pytest

from app.core.config import Settings


# --------------------------------------------------------------------------- #
# 1. 默认值：MONITOR_DB_USER / PASSWORD 为 None                                #
#    用 monkeypatch 清除环境变量，确保测试的是 Settings 默认值而非 env 覆盖    #
#    （Docker 中 MONITOR_DB_USER= 为空串会覆盖 None 默认值）                   #
# --------------------------------------------------------------------------- #
def test_monitor_db_user_defaults_to_none(monkeypatch):
    """MONITOR_DB_USER 默认 None（未启用 DB 层隔离）。"""
    monkeypatch.delenv("MONITOR_DB_USER", raising=False)
    monkeypatch.delenv("MONITOR_DB_PASSWORD", raising=False)
    s = Settings()
    assert s.MONITOR_DB_USER is None, (
        f"MONITOR_DB_USER 默认应为 None，实际: {s.MONITOR_DB_USER!r}"
    )


def test_monitor_db_password_defaults_to_none(monkeypatch):
    """MONITOR_DB_PASSWORD 默认 None。"""
    monkeypatch.delenv("MONITOR_DB_USER", raising=False)
    monkeypatch.delenv("MONITOR_DB_PASSWORD", raising=False)
    s = Settings()
    assert s.MONITOR_DB_PASSWORD is None, (
        f"MONITOR_DB_PASSWORD 默认应为 None，实际: {s.MONITOR_DB_PASSWORD!r}"
    )


# --------------------------------------------------------------------------- #
# 2. 默认 DATABASE_URL 使用 POSTGRES_USER（geo_user）                          #
# --------------------------------------------------------------------------- #
def test_database_url_uses_postgres_user_by_default():
    """未设 MONITOR_DB_USER 时，DATABASE_URL 含 POSTGRES_USER（geo_user）。"""
    s = Settings(POSTGRES_USER="geo_user")
    assert "geo_user" in s.DATABASE_URL, (
        f"默认 DATABASE_URL 应含 geo_user，当前: {s.DATABASE_URL}"
    )
    assert "monitor_user" not in s.DATABASE_URL, (
        f"未启用隔离时 DATABASE_URL 不应含 monitor_user，当前: {s.DATABASE_URL}"
    )


# --------------------------------------------------------------------------- #
# 3. 启用 MONITOR_DB_USER 时 DATABASE_URL 重建                                 #
# --------------------------------------------------------------------------- #
def test_database_url_uses_monitor_user_when_set():
    """设 MONITOR_DB_USER + PASSWORD 时，DATABASE_URL 重建使用 monitor_user。"""
    s = Settings(
        POSTGRES_HOST="geoflow-postgres",
        POSTGRES_PORT=5432,
        POSTGRES_DB="geo_flow",
        POSTGRES_USER="geo_user",
        POSTGRES_PASSWORD="geo_password",
        MONITOR_DB_USER="monitor_user",
        MONITOR_DB_PASSWORD="monitor_secret",
    )
    url = s.DATABASE_URL
    assert "monitor_user" in url, f"DATABASE_URL 应含 monitor_user，当前: {url}"
    assert "monitor_secret" in url, f"DATABASE_URL 应含 monitor 密码，当前: {url}"
    assert "geoflow-postgres" in url, f"DATABASE_URL 应含 host，当前: {url}"
    assert "geo_flow" in url, f"DATABASE_URL 应含 db 名，当前: {url}"
    assert "asyncpg" in url, f"DATABASE_URL 应含 asyncpg 驱动，当前: {url}"


def test_database_url_excludes_geo_user_when_monitor_user_set():
    """启用 monitor_user 后 DATABASE_URL 不再含 geo_user（凭据完全切换）。"""
    s = Settings(
        POSTGRES_USER="geo_user",
        POSTGRES_PASSWORD="geo_password",
        MONITOR_DB_USER="monitor_user",
        MONITOR_DB_PASSWORD="monitor_secret",
    )
    # URL 中 user 段应为 monitor_user:monitor_secret@，不含 geo_user
    assert "geo_user" not in s.DATABASE_URL, (
        f"启用 monitor_user 后 DATABASE_URL 不应含 geo_user，当前: {s.DATABASE_URL}"
    )


# --------------------------------------------------------------------------- #
# 4. MONITOR_DB_PASSWORD 未设时回退 POSTGRES_PASSWORD                          #
# --------------------------------------------------------------------------- #
def test_database_url_falls_back_to_postgres_password():
    """MONITOR_DB_USER 设但 MONITOR_DB_PASSWORD 未设时，用 POSTGRES_PASSWORD。"""
    s = Settings(
        POSTGRES_USER="geo_user",
        POSTGRES_PASSWORD="geo_password",
        MONITOR_DB_USER="monitor_user",
        # MONITOR_DB_PASSWORD 不设置
    )
    url = s.DATABASE_URL
    assert "monitor_user" in url, f"DATABASE_URL 应含 monitor_user，当前: {url}"
    assert "geo_password" in url, (
        f"密码未设时应回退 POSTGRES_PASSWORD=geo_password，当前: {url}"
    )
