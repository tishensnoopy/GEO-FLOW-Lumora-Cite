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


def _client_headers(client_id: str = "test_client_001") -> dict:
    """构造 client JWT 请求头。

    与 admin JWT 不同：client JWT 用 ``SECRET_KEY`` 签发（非 ``SSO_JWT_SECRET``），
    payload ``type='client'``。``get_current_user`` 先尝试用 SSO_JWT_SECRET 解码
    （会失败，签名不匹配），再走 client 分支用 SECRET_KEY 解码 + 查 DB 校验
    Client 存在且 status='active'。因此测试需先在 DB 插入对应 Client 记录。
    """
    payload = {
        "sub": client_id,
        "type": "client",
        "role": "client",
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        "iat": datetime.now(timezone.utc),
    }
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_client_create_export_returns_task_id(client, db_session):
    """client 鉴权 POST /api/v1/exports 返回 202 + task_id + status="pending"。

    覆盖 client 端点成功路径：get_current_user 校验 client JWT + DB 中 Client 存在
    且 active，路由用登录用户本身的 client_id 创建任务（忽略请求体 client_id）。
    """
    from app.models.client import Client
    from app.models.export_task import ExportTask
    from sqlalchemy import delete

    c = Client(
        client_id="test_client_001", username="test_client_001",
        password_hash="x", status="active",
    )
    db_session.add(c)
    await db_session.commit()

    task_id = None
    try:
        resp = await client.post(
            "/api/v1/exports",
            json={"export_type": "pdf"},
            headers=_client_headers("test_client_001"),
        )
        assert resp.status_code == 202
        data = resp.json()
        assert "task_id" in data
        assert data["status"] == "pending"
        task_id = data["task_id"]
    finally:
        if task_id is not None:
            await db_session.execute(
                delete(ExportTask).where(ExportTask.id == task_id)
            )
        await db_session.delete(c)
        await db_session.commit()


@pytest.mark.asyncio
async def test_client_get_other_client_export_returns_403(client, db_session):
    """client 查询其他客户的导出任务返回 403（权限隔离核心安全需求）。

    先用 admin 创建一个属于 other_client 的导出任务，再用 test_client_001 的
    client JWT 请求 GET /exports/{task_id}，断言 403。
    """
    from app.models.client import Client
    from app.models.export_task import ExportTask
    from app.models.admin_audit_log import AdminAuditLog
    from sqlalchemy import delete

    c = Client(
        client_id="test_client_001", username="test_client_001",
        password_hash="x", status="active",
    )
    db_session.add(c)
    await db_session.commit()

    task_id = None
    try:
        # admin 创建一个属于 other_client 的导出任务
        resp = await client.post(
            "/api/v1/admin/exports",
            json={"export_type": "pdf", "client_id": "other_client"},
            headers=_admin_headers(),
        )
        assert resp.status_code == 202
        task_id = resp.json()["task_id"]

        # client 查询 other_client 的任务 → 403（client_id 所有权隔离）
        resp = await client.get(
            f"/api/v1/exports/{task_id}",
            headers=_client_headers("test_client_001"),
        )
        assert resp.status_code == 403
    finally:
        if task_id is not None:
            await db_session.execute(
                delete(ExportTask).where(ExportTask.id == task_id)
            )
            await db_session.execute(
                delete(AdminAuditLog).where(AdminAuditLog.target_id == task_id)
            )
        await db_session.delete(c)
        await db_session.commit()


@pytest.mark.asyncio
async def test_client_download_other_client_export_returns_403(client, db_session):
    """client 下载其他客户的导出任务返回 403。

    权限检查（403）在状态检查（400）之前：即便任务 status=pending 未完成，
    跨客户访问也优先返回 403。这是权限隔离的关键断言。
    """
    from app.models.client import Client
    from app.models.export_task import ExportTask
    from app.models.admin_audit_log import AdminAuditLog
    from sqlalchemy import delete

    c = Client(
        client_id="test_client_001", username="test_client_001",
        password_hash="x", status="active",
    )
    db_session.add(c)
    await db_session.commit()

    task_id = None
    try:
        # admin 创建一个属于 other_client 的导出任务（status=pending，未完成）
        resp = await client.post(
            "/api/v1/admin/exports",
            json={"export_type": "pdf", "client_id": "other_client"},
            headers=_admin_headers(),
        )
        assert resp.status_code == 202
        task_id = resp.json()["task_id"]

        # client 下载 other_client 的任务 → 403（权限检查在状态检查之前）
        resp = await client.get(
            f"/api/v1/exports/{task_id}/download",
            headers=_client_headers("test_client_001"),
        )
        assert resp.status_code == 403
    finally:
        if task_id is not None:
            await db_session.execute(
                delete(ExportTask).where(ExportTask.id == task_id)
            )
            await db_session.execute(
                delete(AdminAuditLog).where(AdminAuditLog.target_id == task_id)
            )
        await db_session.delete(c)
        await db_session.commit()


@pytest.mark.asyncio
async def test_non_client_calling_client_export_returns_403(client):
    """admin 调用 client 导出端点返回 403（role != "client"）。

    admin JWT 通过 get_current_user 解码后 role='admin'，路由第一行
    ``if role != "client"`` 即返回 403。无 DB 写入，无需清理。
    """
    # admin JWT 的 role='admin'，直接 POST /api/v1/exports → 403
    resp = await client.post(
        "/api/v1/exports",
        json={"export_type": "pdf"},
        headers=_admin_headers(),
    )
    assert resp.status_code == 403
