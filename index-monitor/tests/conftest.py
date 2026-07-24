import os
import sys

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# 让 `app` 包从 index-monitor 项目根可导入，无论 pytest 从哪个目录启动
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


@pytest_asyncio.fixture
async def db_session():
    """提供一个 AsyncSession，用完即关。

    用于集成测试连接真实 PostgreSQL（docker-compose 起的 geo-postgres-local）。

    实现说明：每个测试创建独立的 async engine——pytest-asyncio 在 strict 模式下
    为每个测试用例创建独立事件循环，复用模块级 engine（app.core.database.engine）
    会触发 "Future attached to a different loop"。这里就地构造 engine，
    既避免污染生产 engine，也保证测试间事件循环隔离。
    """
    from app.core.config import settings

    url = (
        f"postgresql+asyncpg://{settings.POSTGRES_USER}:{settings.POSTGRES_PASSWORD}"
        f"@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}"
    )
    engine = create_async_engine(url, echo=False)
    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async with session_factory() as session:
        yield session

    await engine.dispose()
