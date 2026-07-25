# index-monitor/tests/integration/test_manual_distribution_endpoint.py
"""手动录入端点测试。设计文档第 9 节。

测试基础设施说明
================

本文件复用 ``test_admin_endpoints.py`` 与 ``test_cross_schema_join.py`` 的既有模式：

1. ``_override_app_db`` (autouse)：为每个测试 override ``get_db`` 依赖，使用当前
   事件循环的全新 engine。pytest-asyncio strict 模式为每个测试创建独立事件循环，
   复用模块级 ``app.core.database.engine`` 会触发 "Future attached to a different
   loop"。

2. ``geoflow_mock_tables`` (module-scoped autouse)：在 ``public`` schema 创建
   GEOFlow mock 表（``articles`` / ``article_distributions``）。本地 ``geo-postgres-local``
   容器的 ``public`` schema 没有 GEOFlow 真实表（只有 ``alembic_version`` 与
   ``distribution_channels``），而 ``DistributionQueryService.list_distributions``
   会跨 schema JOIN ``public.article_distributions`` ⨝ ``public.articles``，缺表
   会触发 ``UndefinedTableError``。模块结束 DROP 清理。
"""
import pytest
import pytest_asyncio
import jwt
from datetime import datetime, timedelta, timezone

from app.core.config import settings


# --------------------------------------------------------------------------- #
# Mock 表 DDL：与 GEOFlow migration 字段对齐（复用自 test_cross_schema_join.py） #
# --------------------------------------------------------------------------- #
_CREATE_ARTICLES_SQL = """
CREATE TABLE IF NOT EXISTS public.articles (
    id BIGSERIAL PRIMARY KEY,
    title VARCHAR(500) NOT NULL,
    slug VARCHAR(500) NOT NULL UNIQUE,
    excerpt TEXT DEFAULT '',
    content TEXT NOT NULL,
    category_id BIGINT NOT NULL,
    author_id BIGINT NOT NULL,
    task_id BIGINT,
    original_keyword VARCHAR(200) DEFAULT '',
    keywords TEXT DEFAULT '',
    meta_description TEXT DEFAULT '',
    status VARCHAR(20) DEFAULT 'draft',
    review_status VARCHAR(20) DEFAULT 'pending',
    view_count INTEGER DEFAULT 0,
    is_ai_generated INTEGER DEFAULT 0,
    is_hot BOOLEAN DEFAULT FALSE,
    is_featured BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ,
    published_at TIMESTAMPTZ,
    deleted_at TIMESTAMPTZ
)
"""

_CREATE_ARTICLE_DISTRIBUTIONS_SQL = """
CREATE TABLE IF NOT EXISTS public.article_distributions (
    id BIGSERIAL PRIMARY KEY,
    article_id BIGINT NOT NULL,
    distribution_channel_id BIGINT NOT NULL,
    action VARCHAR(30) DEFAULT 'publish',
    status VARCHAR(30) DEFAULT 'queued',
    remote_id VARCHAR(120),
    remote_url VARCHAR(500),
    remote_meta JSON,
    idempotency_key VARCHAR(120) UNIQUE,
    attempt_count INTEGER DEFAULT 0,
    next_retry_at TIMESTAMPTZ,
    last_attempt_at TIMESTAMPTZ,
    last_error_message TEXT,
    payload_hash VARCHAR(64),
    created_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ
)
"""

_DROP_ARTICLE_DISTRIBUTIONS_SQL = "DROP TABLE IF EXISTS public.article_distributions"
_DROP_ARTICLES_SQL = "DROP TABLE IF EXISTS public.articles"


@pytest.fixture(scope="module", autouse=True)
def geoflow_mock_tables():
    """Module 级 sync fixture：在 public schema 创建 GEOFlow mock 表，结束 DROP。

    用 ``psycopg2`` 同步连接（独立于 asyncio 事件循环），避免 strict 模式下
    模块级 async fixture 与 per-test 事件循环冲突。DDL 用 ``autocommit`` 提交，
    不会被 per-test 事务回滚影响。
    """
    import psycopg2

    conn = psycopg2.connect(
        host=settings.POSTGRES_HOST,
        port=settings.POSTGRES_PORT,
        dbname=settings.POSTGRES_DB,
        user=settings.POSTGRES_USER,
        password=settings.POSTGRES_PASSWORD,
    )
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(_CREATE_ARTICLES_SQL)
            cur.execute(_CREATE_ARTICLE_DISTRIBUTIONS_SQL)
        yield conn
    finally:
        with conn.cursor() as cur:
            cur.execute(_DROP_ARTICLE_DISTRIBUTIONS_SQL)
            cur.execute(_DROP_ARTICLES_SQL)
        conn.close()


@pytest_asyncio.fixture(autouse=True)
async def _override_app_db():
    """为每个测试 override ``get_db`` 依赖，使用当前事件循环的全新 engine。

    pytest-asyncio strict 模式为每个测试创建独立事件循环。``app.core.database.engine``
    是模块级单例，其连接池里的 asyncpg 连接绑定到首次 import 时的事件循环，
    跨测试复用会触发 "Future attached to a different loop" /
    "another operation is in progress"。

    用 FastAPI ``app.dependency_overrides`` 把 ``get_db`` 替换为闭包，
    闭包内用本测试事件循环新建的 engine → session_factory → session。
    测试结束 dispose 这个临时 engine，不污染模块级 engine。
    """
    from app.main import app
    from app.core.database import get_db
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async def _get_db_override():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _get_db_override
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


def _admin_headers() -> dict:
    payload = {
        "sub": "1", "name": "测试管理员", "role": "admin", "type": "admin",
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        "iat": datetime.now(timezone.utc),
    }
    return {"Authorization": f"Bearer {jwt.encode(payload, settings.SSO_JWT_SECRET, algorithm='HS256')}"}


@pytest.mark.asyncio
async def test_manual_create_requires_admin_auth(client):
    """未鉴权返回 401。"""
    resp = await client.post("/api/v1/distributions", json={"remote_url": "https://example.com"})
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_manual_create_with_unregistered_domain_returns_400(client):
    """domain 未登记返回 400。"""
    resp = await client.post(
        "/api/v1/distributions",
        json={"remote_url": "https://unregistered-domain-xyz.com/article"},
        headers=_admin_headers(),
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_list_distributions_endpoint(client, db_session):
    """GET /api/v1/admin/distributions 返回分发列表。"""
    resp = await client.get("/api/v1/admin/distributions", headers=_admin_headers())
    assert resp.status_code == 200
    assert "items" in resp.json()
