# index-monitor/tests/integration/test_admin_stats.py
"""admin 统计端点集成测试。

C7 修复（整分支代码审查发现）：新增 GET /admin/stats/citation 端点。
原有 /stats/citation 使用 client JWT 鉴权（get_current_client_id），admin JWT
用 SSO_JWT_SECRET 签发 → decode_token 必抛 InvalidTokenError → 401 → 
Dashboard.vue 静默回退 citation_count=0。本端点用 admin 鉴权解决。
"""
import pytest
import pytest_asyncio
import jwt
from datetime import datetime, timedelta, timezone

from app.core.config import settings


@pytest_asyncio.fixture(autouse=True)
async def _override_app_db():
    """为每个测试 override get_db 依赖，使用当前事件循环的全新 engine。"""
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
    """构造 admin JWT 请求头。"""
    payload = {
        "sub": "1", "name": "测试管理员", "role": "admin", "type": "admin",
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        "iat": datetime.now(timezone.utc),
    }
    return {"Authorization": f"Bearer {jwt.encode(payload, settings.SSO_JWT_SECRET, algorithm='HS256')}"}


_TEST_URLS = [
    "https://test-admin-stats.example.com/page1",
    "https://test-admin-stats.example.com/page2",
]


async def _seed_citation_data(db_session):
    """插入测试数据：2 个 URL（不同 client），3 条采信记录。

    - page1 (client_a)：1 exact + 1 none = 2 条
    - page2 (client_b)：1 domain = 1 条
    全量聚合：total=3, cited=2（exact + domain，排除 none）
    client_a 过滤：total=2, cited=1

    必须 commit：HTTP 请求通过另一连接查 DB，未 commit 的事务对其它连接不可见
    （PostgreSQL 默认 READ COMMITTED 隔离级别）。
    """
    from app.models.index_result import IndexResult
    from app.models.citation_result import CitationResult

    ir1 = IndexResult(url=_TEST_URLS[0], client_id="test_stats_client_a", site_type="wordpress")
    ir2 = IndexResult(url=_TEST_URLS[1], client_id="test_stats_client_b", site_type="wordpress")
    db_session.add_all([ir1, ir2])
    await db_session.flush()

    cr1 = CitationResult(url=_TEST_URLS[0], model="qwen", question="问题1", hit_type="exact")
    cr2 = CitationResult(url=_TEST_URLS[0], model="doubao", question="问题2", hit_type="none")
    cr3 = CitationResult(url=_TEST_URLS[1], model="qwen", question="问题1", hit_type="domain")
    db_session.add_all([cr1, cr2, cr3])
    await db_session.commit()


async def _cleanup_citation_data(db_session):
    """清理测试数据。"""
    from app.models.index_result import IndexResult
    from app.models.citation_result import CitationResult
    from sqlalchemy import delete

    await db_session.execute(
        delete(CitationResult).where(CitationResult.url.in_(_TEST_URLS))
    )
    await db_session.execute(
        delete(IndexResult).where(IndexResult.url.in_(_TEST_URLS))
    )
    await db_session.commit()


@pytest.mark.asyncio
async def test_admin_citation_stats_returns_aggregated_count(client, db_session):
    """admin 获取全量采信统计：新增 3 条（total +3, cited +2，exact + domain，排除 none）。

    共享本地测试 DB 已有预存采信数据（5 条），无法断言绝对总数。改用 delta 方式：
    记录 seeding 前的全量基线，断言 seeding 后 total/cited 的增量符合预期。
    """
    try:
        # 记录基线（共享 DB 可能有预存数据）
        resp_before = await client.get("/api/v1/admin/stats/citation", headers=_admin_headers())
        assert resp_before.status_code == 200
        before = resp_before.json()

        await _seed_citation_data(db_session)

        resp = await client.get("/api/v1/admin/stats/citation", headers=_admin_headers())
        assert resp.status_code == 200
        data = resp.json()
        # 增量断言：seeding 新增 3 条 total（2 exact/none + 1 domain）、2 条 cited（exact + domain）
        assert data["total"] == before["total"] + 3
        assert data["cited"] == before["cited"] + 2
    finally:
        await _cleanup_citation_data(db_session)


@pytest.mark.asyncio
async def test_admin_citation_stats_without_auth_returns_401(client):
    """无鉴权调用返回 401。"""
    resp = await client.get("/api/v1/admin/stats/citation")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_admin_citation_stats_filter_by_client_id(client, db_session):
    """admin 按 client_id 过滤：只统计该客户的 URL。"""
    try:
        await _seed_citation_data(db_session)

        resp = await client.get(
            "/api/v1/admin/stats/citation?client_id=test_stats_client_a",
            headers=_admin_headers(),
        )
        assert resp.status_code == 200
        data = resp.json()
        # client_a 只有 page1，2 条采信记录，其中 1 条 exact
        assert data["total"] == 2
        assert data["cited"] == 1
    finally:
        await _cleanup_citation_data(db_session)


@pytest.mark.asyncio
async def test_admin_citation_stats_empty_when_no_data(client):
    """无数据时返回 total=0, cited=0。

    共享本地测试 DB 已有预存采信数据，无法断言全局为空。改用不存在的 client_id
    过滤，确保该客户维度下无任何记录，验证空数据分支返回 0。
    """
    resp = await client.get(
        "/api/v1/admin/stats/citation?client_id=nonexistent_empty_client_xyz",
        headers=_admin_headers(),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["cited"] == 0
