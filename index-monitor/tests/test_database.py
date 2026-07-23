import pytest
from sqlalchemy import text

from app.core.database import async_session


@pytest.mark.asyncio
async def test_database_connection_select_one():
    """验收标准 3：数据库连接正常（真实连运行中的 postgres，非 mock）。

    使用 app.core.database.async_session 执行 `SELECT 1`，断言返回 1。
    依赖 Task 1 启动的 geo-postgres-local 容器（localhost:5432）。
    """
    async with async_session() as session:
        result = await session.execute(text("SELECT 1"))
        value = result.scalar()
        assert value == 1
