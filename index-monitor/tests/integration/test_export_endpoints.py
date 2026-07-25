# index-monitor/tests/integration/test_export_endpoints.py
"""导出端点集成测试。设计文档第 12.3 节。

测试基础设施说明
================

复用 ``test_admin_endpoints.py`` / ``test_manual_distribution_endpoint.py`` 的既有模式：

``_override_app_db`` (autouse)：为每个测试 override ``get_db`` 依赖，使用当前
事件循环的全新 engine。pytest-asyncio strict 模式为每个测试创建独立事件循环，
复用模块级 ``app.core.database.engine`` 会触发 "Future attached to a different loop"。
"""
import pytest
import pytest_asyncio
import jwt
from datetime import datetime, timedelta, timezone

from app.core.config import settings


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
async def test_admin_export_pdf_returns_task_id(client):
    """admin 触发 PDF 导出，返回 task_id。"""
    resp = await client.post(
        "/api/v1/admin/exports",
        json={"export_type": "pdf", "date_from": "2026-07-01", "date_to": "2026-07-25"},
        headers=_admin_headers(),
    )
    assert resp.status_code == 202
    data = resp.json()
    assert "task_id" in data
    assert data["status"] == "pending"


@pytest.mark.asyncio
async def test_admin_export_excel_returns_task_id(client):
    """admin 触发 Excel 导出。"""
    resp = await client.post(
        "/api/v1/admin/exports",
        json={"export_type": "excel"},
        headers=_admin_headers(),
    )
    assert resp.status_code == 202
    assert "task_id" in resp.json()


@pytest.mark.asyncio
async def test_export_requires_admin_auth(client):
    """未鉴权返回 401。"""
    resp = await client.post("/api/v1/admin/exports", json={"export_type": "pdf"})
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_export_invalid_type_returns_400(client):
    """无效 export_type 返回 400。"""
    resp = await client.post(
        "/api/v1/admin/exports",
        json={"export_type": "word"},
        headers=_admin_headers(),
    )
    assert resp.status_code == 400
