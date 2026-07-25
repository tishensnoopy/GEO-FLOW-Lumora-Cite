# index-monitor/tests/integration/test_admin_endpoints.py
"""admin 端点集成测试。设计文档第 9 节。"""
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


def _admin_headers(role: str = "admin") -> dict:
    """构造 admin JWT 请求头。"""
    payload = {
        "sub": "1", "name": "测试管理员", "role": role, "type": "admin",
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        "iat": datetime.now(timezone.utc),
    }
    token = jwt.encode(payload, settings.SSO_JWT_SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_create_client_success(client, db_session):
    """创建客户成功。"""
    try:
        resp = await client.post(
            "/api/v1/admin/clients",
            json={
                "client_id": "test_create_endpoint",
                "username": "test_create_ep",
                "password": "Pass1234",
                "company_name": "测试公司",
                "contact_name": "张三",
                "contact_email": "zhangsan@test.com",
                "contact_phone": "13800000000",
            },
            headers=_admin_headers(),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["client_id"] == "test_create_endpoint"
        assert data["status"] == "active"
    finally:
        # 清理：客户 + 关联审计日志（POST 成功时会写一条 create_client 日志）
        from app.models.client import Client
        from app.models.admin_audit_log import AdminAuditLog
        from sqlalchemy import select, delete
        result = await db_session.execute(
            select(Client).where(Client.client_id == "test_create_endpoint")
        )
        c = result.scalar_one_or_none()
        if c is not None:
            await db_session.delete(c)
        await db_session.execute(
            delete(AdminAuditLog).where(AdminAuditLog.target_id == "test_create_endpoint")
        )
        await db_session.commit()


@pytest.mark.asyncio
async def test_create_client_weak_password_returns_400(client):
    """密码强度不足返回 400。"""
    resp = await client.post(
        "/api/v1/admin/clients",
        json={
            "client_id": "weak_pw", "username": "weak",
            "password": "123",  # 太短
        },
        headers=_admin_headers(),
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_create_client_duplicate_email_returns_409(client, db_session):
    """邮箱重复返回 409。"""
    from app.models.client import Client
    existing = Client(
        client_id="dup_email_1", username="dup1",
        password_hash="x", contact_email="dup@test.com", status="active",
    )
    db_session.add(existing)
    await db_session.commit()

    try:
        resp = await client.post(
            "/api/v1/admin/clients",
            json={
                "client_id": "dup_email_2", "username": "dup2",
                "password": "Pass1234",
                "contact_email": "dup@test.com",
            },
            headers=_admin_headers(),
        )
        assert resp.status_code == 409
    finally:
        await db_session.delete(existing)
        await db_session.commit()


@pytest.mark.asyncio
async def test_deactivate_client_blocks_login(client, db_session):
    """停用客户后无法登录。"""
    from app.models.client import Client
    from app.core.security import hash_password
    c = Client(
        client_id="deactivate_test", username="deact",
        password_hash=hash_password("Pass1234"), status="active",
    )
    db_session.add(c)
    await db_session.commit()

    try:
        # 停用
        resp = await client.put(
            f"/api/v1/admin/clients/{c.client_id}",
            json={"status": "inactive"},
            headers=_admin_headers(),
        )
        assert resp.status_code == 200

        # 尝试登录应失败
        resp = await client.post(
            "/api/v1/auth/login",
            json={"username": "deact", "password": "Pass1234"},
        )
        assert resp.status_code == 401
    finally:
        # 清理：客户 + 关联审计日志（PUT 会写一条 deactivate_client 日志）
        from app.models.admin_audit_log import AdminAuditLog
        from sqlalchemy import delete
        await db_session.delete(c)
        await db_session.execute(
            delete(AdminAuditLog).where(AdminAuditLog.target_id == "deactivate_test")
        )
        await db_session.commit()
