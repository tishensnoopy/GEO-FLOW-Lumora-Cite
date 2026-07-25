# index-monitor/tests/integration/test_distribution_endpoint.py
"""client GET /distributions 端点测试（D04 修复）。"""
import pytest
import pytest_asyncio
import jwt
from datetime import datetime, timedelta, timezone

from app.core.config import settings


@pytest.fixture(autouse=True, scope="module")
def ensure_geoflow_tables():
    """Module 级 autouse fixture：确保 GEOFlow public schema 表存在。

    ``tests/integration/test_cross_schema_join.py`` 和
    ``test_manual_distribution_endpoint.py`` 的 module fixture teardown
    会 DROP ``public.articles`` + ``public.article_distributions``。
    本 fixture 在模块开始时用 ``GeoflowBase.metadata.create_all`` 建表
    （IF NOT EXISTS 幂等），保证本模块测试可运行。

    参考 ``test_checker_geoflow_read.py`` 的同类处理。
    """
    from sqlalchemy import create_engine
    from app.models.geoflow_models import GeoflowBase

    url = (
        f"postgresql+psycopg2://{settings.POSTGRES_USER}:{settings.POSTGRES_PASSWORD}"
        f"@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}"
    )
    engine = create_engine(url)
    try:
        GeoflowBase.metadata.create_all(engine)
    finally:
        engine.dispose()


@pytest_asyncio.fixture(autouse=True)
async def _override_app_db():
    """为每个测试 override ``get_db`` 依赖，使用当前事件循环的全新 engine。

    与 ``test_admin_endpoints.py`` 中同名 fixture 一致：避免模块级 engine
    跨事件循环复用导致 "Future attached to a different loop"。
    """
    from app.main import app
    from app.core.database import get_db
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _get_db_override():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _get_db_override
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


def _client_headers(client_id: str = "test_dist_client") -> dict:
    """构造 client JWT 请求头（用 SECRET_KEY 签发，对应 get_current_user 的 client 分支）。"""
    payload = {
        "sub": client_id, "type": "client", "role": "client",
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
    }
    return {"Authorization": f"Bearer {jwt.encode(payload, settings.SECRET_KEY, algorithm='HS256')}"}


@pytest.mark.asyncio
async def test_client_list_distributions_returns_own_records(client, db_session):
    """client GET /distributions 返回自己的分发记录（按 client_id 过滤）。"""
    from app.models.client import Client
    from app.models.manual_distribution import ManualDistribution
    from sqlalchemy import delete

    c = Client(client_id="test_dist_client", username="dist", password_hash="x", status="active")
    db_session.add(c)
    md = ManualDistribution(
        client_id="test_dist_client",
        remote_url="https://dist.example.com/page",
        status="synced",
    )
    db_session.add(md)
    await db_session.commit()

    try:
        resp = await client.get("/api/v1/distributions", headers=_client_headers())
        assert resp.status_code == 200
        items = resp.json()["items"]
        # 至少包含刚插入的记录
        urls = [it["remote_url"] for it in items]
        assert "https://dist.example.com/page" in urls
    finally:
        await db_session.execute(delete(ManualDistribution).where(
            ManualDistribution.remote_url == "https://dist.example.com/page"
        ))
        await db_session.delete(c)
        await db_session.commit()


@pytest.mark.asyncio
async def test_client_distributions_isolated_by_client_id(client, db_session):
    """client A 看不到 client B 的分发记录（403/隔离验证）。"""
    from app.models.client import Client
    from app.models.manual_distribution import ManualDistribution
    from sqlalchemy import delete

    c_a = Client(client_id="test_dist_client_a", username="dist_a", password_hash="x", status="active")
    c_b = Client(client_id="test_dist_client_b", username="dist_b", password_hash="x", status="active")
    db_session.add_all([c_a, c_b])
    md_b = ManualDistribution(
        client_id="test_dist_client_b",
        remote_url="https://secret-b.example.com/page",
        status="synced",
    )
    db_session.add(md_b)
    await db_session.commit()

    try:
        resp = await client.get("/api/v1/distributions", headers=_client_headers("test_dist_client_a"))
        assert resp.status_code == 200
        items = resp.json()["items"]
        urls = [it["remote_url"] for it in items]
        # client A 看不到 client B 的记录
        assert "https://secret-b.example.com/page" not in urls
    finally:
        await db_session.execute(delete(ManualDistribution).where(
            ManualDistribution.remote_url == "https://secret-b.example.com/page"
        ))
        await db_session.delete(c_a)
        await db_session.delete(c_b)
        await db_session.commit()


@pytest.mark.asyncio
async def test_admin_token_rejected_with_403(client, db_session):
    """admin token 调用 GET /distributions 应返回 403（引导走 /admin/distributions）。"""
    import jwt as _jwt
    payload = {
        "sub": "1", "name": "测试管理员", "role": "admin", "type": "admin",
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        "iat": datetime.now(timezone.utc),
    }
    token = _jwt.encode(payload, settings.SSO_JWT_SECRET, algorithm="HS256")
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.get("/api/v1/distributions", headers=headers)
    assert resp.status_code == 403
