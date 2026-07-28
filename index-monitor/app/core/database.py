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

# 连接池配置（P0 性能优化）：
# - pool_size=10：常驻连接数，满足常规并发（原默认 5 在扫描场景不够）
# - max_overflow=20：突发并发可额外创建的连接数
# - pool_pre_ping=True：连接前 ping 检查，避免使用已被 PG 断开的连接
# - pool_recycle=1800：30 分钟回收连接，避免长连接被 PG idle_timeout 断开
engine = create_async_engine(
    DATABASE_URL,
    echo=settings.DEBUG,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    pool_recycle=1800,
)

# SQLAlchemy 2.0 推荐使用 async_sessionmaker（替代 sessionmaker）
async_session = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


async def get_db():
    # async with 上下文退出时自动 close，无需 finally 手动 close
    async with async_session() as session:
        yield session
