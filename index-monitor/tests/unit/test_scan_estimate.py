# index-monitor/tests/unit/test_scan_estimate.py
"""GET /admin/scan/estimate 预估消耗接口测试。

验证接口返回结构与各类型 pending 数量 + 已配置模型 + per-model 调用次数。
mock 各 checker 的 get_pending_urls / _get_configured_models，避免依赖真实 DB 数据。
"""
import pytest
import pytest_asyncio
import jwt
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, AsyncMock

from app.core.config import settings


@pytest_asyncio.fixture(autouse=True)
async def _override_app_db():
    """为每个测试 override get_db 依赖，使用当前事件循环的全新 engine。

    与 test_batch_scan.py::_override_app_db 一致，解决 pytest-asyncio strict
    模式下模块级 engine 跨事件循环复用问题。
    """
    from app.main import app
    from app.core.database import get_db
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
    from sqlalchemy.pool import NullPool

    engine = create_async_engine(settings.DATABASE_URL, echo=False, poolclass=NullPool)
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
async def test_scan_estimate_returns_structure(client):
    """接口返回 index/ai_index/citation 三段，含 count/models/model_counts。"""
    # mock IndexChecker.get_pending_urls 返回 2 个 URL
    with patch(
        "app.services.index_checker.IndexChecker.get_pending_urls",
        new_callable=AsyncMock,
        return_value=[("https://a.com", "c1"), ("https://b.com", "c2")],
    ), patch(
        "app.services.ai_index_checker.AIIndexChecker.get_pending_urls",
        new_callable=AsyncMock,
        return_value=[
            ("https://a.com", "c1", "qwen"),
            ("https://a.com", "c1", "doubao"),
            ("https://b.com", "c2", "qwen"),
        ],
    ), patch(
        "app.services.ai_index_checker.AIIndexChecker._get_configured_models",
        return_value=["qwen", "doubao"],
    ), patch(
        "app.services.citation_checker.CitationChecker.get_pending_urls",
        new_callable=AsyncMock,
        return_value=[("https://a.com", "c1")],
    ):
        resp = await client.get("/api/v1/admin/scan/estimate", headers=_admin_headers())

    assert resp.status_code == 200
    data = resp.json()

    # index 段
    assert "index" in data
    assert data["index"]["count"] == 2

    # ai_index 段：含 count + models + model_counts
    assert data["ai_index"]["count"] == 3
    assert set(data["ai_index"]["models"]) == {"qwen", "doubao"}
    # model_counts 按 model 聚合：qwen=2, doubao=1
    assert data["ai_index"]["model_counts"]["qwen"] == 2
    assert data["ai_index"]["model_counts"]["doubao"] == 1

    # citation 段
    assert data["citation"]["count"] == 1
    assert set(data["citation"]["models"]) == {"qwen", "doubao"}


@pytest.mark.asyncio
async def test_scan_estimate_empty_pending(client):
    """无待扫描数据时，各 count 为 0，接口仍返回 200。"""
    with patch(
        "app.services.index_checker.IndexChecker.get_pending_urls",
        new_callable=AsyncMock,
        return_value=[],
    ), patch(
        "app.services.ai_index_checker.AIIndexChecker.get_pending_urls",
        new_callable=AsyncMock,
        return_value=[],
    ), patch(
        "app.services.ai_index_checker.AIIndexChecker._get_configured_models",
        return_value=[],
    ), patch(
        "app.services.citation_checker.CitationChecker.get_pending_urls",
        new_callable=AsyncMock,
        return_value=[],
    ):
        resp = await client.get("/api/v1/admin/scan/estimate", headers=_admin_headers())

    assert resp.status_code == 200
    data = resp.json()
    assert data["index"]["count"] == 0
    assert data["ai_index"]["count"] == 0
    assert data["ai_index"]["model_counts"] == {}
    assert data["citation"]["count"] == 0


@pytest.mark.asyncio
async def test_scan_estimate_checker_error_isolated(client):
    """单个 checker 抛异常时，接口仍返回 200，该段含 error 标志，不影响其他段。"""
    with patch(
        "app.services.index_checker.IndexChecker.get_pending_urls",
        new_callable=AsyncMock,
        side_effect=RuntimeError("GEOFlow 不可用"),
    ), patch(
        "app.services.ai_index_checker.AIIndexChecker.get_pending_urls",
        new_callable=AsyncMock,
        return_value=[("https://a.com", "c1", "qwen")],
    ), patch(
        "app.services.ai_index_checker.AIIndexChecker._get_configured_models",
        return_value=["qwen"],
    ), patch(
        "app.services.citation_checker.CitationChecker.get_pending_urls",
        new_callable=AsyncMock,
        return_value=[],
    ):
        resp = await client.get("/api/v1/admin/scan/estimate", headers=_admin_headers())

    assert resp.status_code == 200
    data = resp.json()
    # index 段失败：count=0 + error 标志
    assert data["index"]["count"] == 0
    assert "error" in data["index"]
    # ai_index 段不受影响
    assert data["ai_index"]["count"] == 1
    # citation 段不受影响
    assert data["citation"]["count"] == 0
