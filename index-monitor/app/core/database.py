# index-monitor/app/core/database.py
"""
监测系统数据库连接层——Task 4 起直接消费 settings.DATABASE_URL。

变更说明
========

- 不再从 POSTGRES_* 字段拼接 URL，统一使用 settings.DATABASE_URL 作为
  单一事实来源，避免配置分散。
- conftest.py 和 alembic/env.py 仍保留 POSTGRES_* 构造逻辑，用于测试
  环境和迁移环境连接本地 PG（docker-compose 注入 POSTGRES_HOST=postgres）。
  这是刻意的不对称：生产走 DATABASE_URL，测试走 POSTGRES_*，二者解耦。
"""
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from app.core.config import settings

# 单一事实来源——直接消费 settings.DATABASE_URL（默认指向 GEOFlow PG）
DATABASE_URL = settings.DATABASE_URL

engine = create_async_engine(DATABASE_URL, echo=settings.DEBUG)

# SQLAlchemy 2.0 推荐使用 async_sessionmaker（替代 sessionmaker）
async_session = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


async def get_db():
    # async with 上下文退出时自动 close，无需 finally 手动 close
    async with async_session() as session:
        yield session
