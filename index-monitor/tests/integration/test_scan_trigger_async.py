# index-monitor/tests/integration/test_scan_trigger_async.py
"""POST /scan/trigger/{type} 异步化测试（阶段 4 - ⑤/①）。

验证目标：
1. 有待检测 URL 时返回 task_id，HTTP 立即响应（不阻塞）
2. 无待检测 URL 时返回 task_id=None
3. 不支持的 scan_type 返回 400
4. 后台任务透传 task_id 给 check_all_pending

解决痛点 1：原同步实现阻塞事件循环（检测耗时数分钟 → HTTP 超时）。
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio


@pytest_asyncio.fixture(autouse=True)
async def _override_app_db():
    """override get_db，避免跨事件循环复用模块级 engine。"""
    from app.main import app
    from app.core.database import get_db
    from app.core.config import settings
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


def _admin_headers():
    """构造 admin JWT 请求头。"""
    from datetime import datetime, timedelta, timezone
    import jwt
    from app.core.config import settings
    payload = {
        "sub": "1", "name": "触发测试员", "role": "admin", "type": "admin",
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        "iat": datetime.now(timezone.utc),
    }
    token = jwt.encode(payload, settings.SSO_JWT_SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_trigger_citation_returns_task_id(client, monkeypatch):
    """有待检测 URL 时，/scan/trigger/citation 应立即返回 task_id。"""
    fake_pending = [("https://example.com/a", "client-1")]

    # mock CitationChecker.get_pending_urls 返回待检测列表
    async def fake_get_pending(self):
        return fake_pending
    monkeypatch.setattr(
        "app.services.citation_checker.CitationChecker.get_pending_urls",
        fake_get_pending,
    )
    # mock 后台执行（不真正跑检测，只验证透传 task_id）
    captured = {}

    async def fake_run_background(scan_type, task_id):
        captured["scan_type"] = scan_type
        captured["task_id"] = task_id
    monkeypatch.setattr(
        "app.api.routes._run_scan_background",
        fake_run_background,
    )
    # 阻止 asyncio.create_task 真正调度（用 fake_run_background 替换后，
    # create_task 仍会包装它，但 fake 函数立即返回，不影响测试）

    resp = await client.post("/api/v1/scan/trigger/citation", headers=_admin_headers())
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["task_id"] is not None, "应返回 task_id"
    assert data["queued"] == 1
    assert data["scan_type"] == "citation"

    # 让事件循环执行 create_task 调度的协程
    await asyncio.sleep(0.05)
    assert captured.get("scan_type") == "citation", "后台任务应收到 scan_type"
    assert captured.get("task_id") == data["task_id"], "后台任务应收到 task_id"


@pytest.mark.asyncio
async def test_trigger_citation_no_pending_returns_null_task_id(client, monkeypatch):
    """无待检测 URL 时，应返回 task_id=None 且不创建后台任务。"""
    async def fake_get_pending(self):
        return []
    monkeypatch.setattr(
        "app.services.citation_checker.CitationChecker.get_pending_urls",
        fake_get_pending,
    )

    resp = await client.post("/api/v1/scan/trigger/citation", headers=_admin_headers())
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["task_id"] is None
    assert data["queued"] == 0


@pytest.mark.asyncio
async def test_trigger_invalid_scan_type_returns_400(client):
    """不支持的 scan_type 应返回 400。"""
    resp = await client.post("/api/v1/scan/trigger/invalid", headers=_admin_headers())
    assert resp.status_code == 400
