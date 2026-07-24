"""统一数据库集成测试——monitor schema 命名空间。

验收：监测系统的表位于 monitor schema，GEOFlow 的表位于 public schema。
本测试验证迁移 001_create_monitor_schema 已正确创建 monitor schema，
同时 public schema 不受影响。
"""
import pytest
from sqlalchemy import text


@pytest.mark.asyncio
async def test_monitor_schema_exists(db_session):
    """验证 monitor schema 已创建。"""
    result = await db_session.execute(
        text("SELECT schema_name FROM information_schema.schemata WHERE schema_name = 'monitor'")
    )
    assert result.scalar() == "monitor"


@pytest.mark.asyncio
async def test_public_schema_still_exists(db_session):
    """验证 public schema 仍然存在（GEOFlow 的表不受影响）。"""
    result = await db_session.execute(
        text("SELECT schema_name FROM information_schema.schemata WHERE schema_name = 'public'")
    )
    assert result.scalar() == "public"
