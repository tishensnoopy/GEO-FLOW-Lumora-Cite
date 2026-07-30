"""数据库连接测试——Task 4 调整为使用 conftest 的 db_session fixture。

变更说明
========

- 旧版本直接使用 ``app.core.database.async_session``，但 Task 4 把
  ``database.py`` 改为消费 ``settings.DATABASE_URL``（默认指向 GEOFlow PG）。
  在本地测试环境（geo-postgres-local 容器）中，GEOFlow PG 不可达，
  因此改用 ``conftest.py`` 的 ``db_session`` fixture（基于 POSTGRES_* 环境变量
  连接本地 PG），保持 "真实连接运行中的 PG" 的验收意图。
"""
import pytest
from sqlalchemy import text


@pytest.mark.asyncio
async def test_database_connection_select_one(db_session):
    """验收标准 3：数据库连接正常（真实连运行中的 postgres，非 mock）。

    使用 conftest.py 的 db_session fixture 执行 `SELECT 1`，断言返回 1。
    依赖 Task 1 启动的 geo-postgres-local 容器（localhost:5432）。
    """
    result = await db_session.execute(text("SELECT 1"))
    value = result.scalar()
    assert value == 1
