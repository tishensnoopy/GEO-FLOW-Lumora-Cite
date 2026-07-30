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

    安全修复：共享本地 DB 已有 GEOFlow 真实表（public.articles 等，含外键依赖
    article_images/article_reviews/article_risk_scans）。创建前先查
    information_schema 判断表是否已存在——若已存在则跳过 CREATE 与 teardown DROP，
    避免误删真实 GEOFlow 表导致 DependentObjectsStillExist 错误 + 数据丢失风险。
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
            # 检查表是否已存在（GEOFlow migration 可能已创建真实表）
            cur.execute(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_schema='public' AND table_name='articles'"
            )
            articles_existed = cur.fetchone() is not None
            cur.execute(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_schema='public' AND table_name='article_distributions'"
            )
            distributions_existed = cur.fetchone() is not None

            if not articles_existed:
                cur.execute(_CREATE_ARTICLES_SQL)
            if not distributions_existed:
                cur.execute(_CREATE_ARTICLE_DISTRIBUTIONS_SQL)
        yield conn
    finally:
        with conn.cursor() as cur:
            # 只 DROP 我们创建的 mock 表，绝不 DROP 预存的 GEOFlow 真实表
            if not distributions_existed:
                cur.execute(_DROP_ARTICLE_DISTRIBUTIONS_SQL)
            if not articles_existed:
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


@pytest.mark.asyncio
async def test_manual_create_success_and_audit_log(client, db_session):
    """POST /api/v1/distributions 成功路径：返回 201 + service 结果形状 + 审计日志写入。

    覆盖核心正路径行为：
    - 已登记 domain 的 URL 录入成功返回 201
    - 响应体与 ``DistributionQueryService.create_manual_distribution`` 返回形状一致
      （action="created" / source="manual" / client_id=匹配到的客户）
    - ``manual_create_distribution`` 审计日志真的被写入 AdminAuditLog，
      detail JSON 中包含 url 与 client_id
    """
    from app.models.client import Client, ClientSite
    from app.models.manual_distribution import ManualDistribution
    from app.models.admin_audit_log import AdminAuditLog
    from sqlalchemy import select, delete

    # 前置：Client + ClientSite（domain 标准化后为 manual-ep.example.com，
    # 匹配 URL https://www.manual-ep.example.com/article/1 提取出的 domain）
    c = Client(
        client_id="test_manual_ep",
        username="manual_ep",
        password_hash="x",
        status="active",
    )
    site = ClientSite(
        client_id="test_manual_ep",
        site_name="站",
        domain="manual-ep.example.com",
        site_type="official",
        status="active",
    )
    db_session.add(c)
    db_session.add(site)
    await db_session.commit()

    try:
        resp = await client.post(
            "/api/v1/distributions",
            json={
                "remote_url": "https://www.manual-ep.example.com/article/1",
                "note": "测试录入",
            },
            headers=_admin_headers(),
        )
        assert resp.status_code == 201, (
            f"unexpected status: {resp.status_code} body: {resp.text}"
        )
        body = resp.json()
        assert body["action"] == "created"
        assert body["source"] == "manual"
        assert body["client_id"] == "test_manual_ep"

        # 审计日志断言：manual_create_distribution 已写入，detail JSON 包含 domain
        # （AuditLogService.log 把 detail 序列化为 JSON 字符串存储）
        audit_result = await db_session.execute(
            select(AdminAuditLog).where(
                AdminAuditLog.action == "manual_create_distribution",
                AdminAuditLog.target_type == "distribution",
            )
        )
        logs = audit_result.scalars().all()
        matching = [
            l for l in logs
            if l.detail and "manual-ep.example.com" in l.detail
        ]
        assert len(matching) >= 1, "审计日志未写入或 detail 不包含录入 URL 的 domain"
    finally:
        # 清理：ManualDistribution → AdminAuditLog → ClientSite → Client
        # （无 FK 约束，顺序无关，但按依赖顺序清理更直观）
        await db_session.execute(
            delete(ManualDistribution).where(
                ManualDistribution.remote_url
                == "https://www.manual-ep.example.com/article/1"
            )
        )
        await db_session.execute(
            delete(AdminAuditLog).where(
                AdminAuditLog.action == "manual_create_distribution",
                AdminAuditLog.target_type == "distribution",
            )
        )
        await db_session.execute(
            delete(ClientSite).where(ClientSite.domain == "manual-ep.example.com")
        )
        await db_session.execute(
            delete(Client).where(Client.client_id == "test_manual_ep")
        )
        await db_session.commit()


@pytest.mark.asyncio
async def test_list_distributions_returns_total_and_filters(client, db_session):
    """GET /api/v1/admin/distributions 正路径：返回 total + source/client_id 过滤生效。

    覆盖核心正路径行为：
    - 无参数返回 ``total`` 字段且 >= 1（包含我们插入的 manual 记录）
    - ``?source=manual`` 过滤：所有 item source == "manual"
    - ``?client_id=test_list_dist`` 过滤：所有 item client_id == "test_list_dist"
    """
    from app.models.client import Client, ClientSite
    from app.models.manual_distribution import ManualDistribution
    from sqlalchemy import delete

    # 前置：Client + ClientSite + ManualDistribution（status=synced 才会被查询）
    c = Client(
        client_id="test_list_dist",
        username="list_dist",
        password_hash="x",
        status="active",
    )
    site = ClientSite(
        client_id="test_list_dist",
        site_name="列表测试站点",
        domain="list-test.example.com",
        site_type="official",
        status="active",
    )
    record = ManualDistribution(
        client_id="test_list_dist",
        remote_url="https://list-test.example.com/post",
        status="synced",
        note="list filter test",
    )
    db_session.add(c)
    db_session.add(site)
    db_session.add(record)
    await db_session.commit()

    try:
        # 1) 无参数 → 200, total 字段存在, total >= 1（至少包含我们刚插入的记录）
        resp = await client.get(
            "/api/v1/admin/distributions", headers=_admin_headers()
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "total" in body, "响应缺少 total 字段"
        assert body["total"] >= 1, f"total 应 >= 1，实际: {body['total']}"

        # 2) source=manual → 200, 所有 item source == "manual"
        resp = await client.get(
            "/api/v1/admin/distributions?source=manual",
            headers=_admin_headers(),
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) >= 1, "source=manual 应至少返回 1 条（我们插入的记录）"
        for it in items:
            assert it["source"] == "manual", (
                f"source=manual 过滤失效：item source={it.get('source')}"
            )

        # 3) client_id=test_list_dist → 200, 所有 item client_id == "test_list_dist"
        resp = await client.get(
            "/api/v1/admin/distributions?client_id=test_list_dist",
            headers=_admin_headers(),
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) >= 1, "client_id 过滤应至少返回 1 条（我们插入的记录）"
        for it in items:
            assert it["client_id"] == "test_list_dist", (
                f"client_id 过滤失效：item client_id={it.get('client_id')}"
            )
    finally:
        # 清理：ManualDistribution → ClientSite → Client
        await db_session.execute(
            delete(ManualDistribution).where(
                ManualDistribution.remote_url == "https://list-test.example.com/post"
            )
        )
        await db_session.execute(
            delete(ClientSite).where(ClientSite.domain == "list-test.example.com")
        )
        await db_session.execute(
            delete(Client).where(Client.client_id == "test_list_dist")
        )
        await db_session.commit()
