"""契约测试公共夹具。

升级 GEOFlow 前执行：pytest tests/contract/ -v
需要真实 GEOFlow DB 可连接（从 .env 读 DATABASE_URL 或 GEOFLOW_DATABASE_URL）。

skipif 通过 ``pytest_collection_modifyitems`` 钩子应用到本目录下所有测试
——直接在 conftest.py 设 ``pytestmark`` 不会传播到 test 模块（pytest 设计如此）。
"""
import os

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine

# 契约测试需要真实 DB——若无配置则跳过（不阻塞 unit 测试运行）
GEOFLOW_DB_URL = os.getenv("GEOFLOW_DATABASE_URL") or os.getenv("DATABASE_URL", "")


def _is_pg_url(url: str) -> bool:
    return url.startswith("postgresql://") or url.startswith("postgresql+asyncpg://")


_SKIP_REASON = "契约测试需要 GEOFLOW_DATABASE_URL 或 DATABASE_URL 指向 PostgreSQL"


def pytest_collection_modifyitems(config, items):
    """对本目录下所有测试应用 DB 可用性 skipif。

    无 DB URL 时整张套件被跳过——避免阻塞 unit 测试运行。
    """
    for item in items:
        # 只处理本目录（geoflow_schema）下的测试——其他目录的测试不受影响
        if "tests/contract/geoflow_schema" in str(item.fspath).replace("\\", "/"):
            if not GEOFLOW_DB_URL or not _is_pg_url(GEOFLOW_DB_URL):
                item.add_marker(pytest.mark.skip(reason=_SKIP_REASON))


@pytest_asyncio.fixture
async def geoflow_engine():
    """每个测试函数独立的 async engine。

    用 ``@pytest_asyncio.fixture`` 而非 ``@pytest.fixture``——项目 pytest-asyncio
    在 strict 模式下，async 生成器 fixture 必须用 ``pytest_asyncio.fixture``
    才能被正确 await（否则 fixture 返回未消费的 async_generator 对象）。

    为什么不用 ``scope="session"``：pytest-asyncio strict 模式为每个测试函数
    创建独立事件循环，session 级 engine 的连接池绑定到首个循环，后续测试
    复用会触发 "Future attached to a different loop"。这与 ``tests/conftest.py``
    里 ``db_session`` fixture 的实现策略一致。
    """
    url = GEOFLOW_DB_URL
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    engine = create_async_engine(url)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def geoflow_session(geoflow_engine):
    """每个测试函数独立的 async session。"""
    async with geoflow_engine.connect() as conn:
        yield conn
