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

        # 审计日志断言：create_client 已写入
        from app.models.admin_audit_log import AdminAuditLog
        from sqlalchemy import select
        audit_result = await db_session.execute(
            select(AdminAuditLog).where(
                AdminAuditLog.action == "create_client",
                AdminAuditLog.target_id == "test_create_endpoint",
            )
        )
        assert audit_result.scalar_one_or_none() is not None, "审计日志未写入"
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

        # 审计日志断言：deactivate_client 已写入
        from app.models.admin_audit_log import AdminAuditLog
        from sqlalchemy import select
        audit_result = await db_session.execute(
            select(AdminAuditLog).where(
                AdminAuditLog.action == "deactivate_client",
                AdminAuditLog.target_id == "deactivate_test",
            )
        )
        assert audit_result.scalar_one_or_none() is not None, "审计日志未写入"

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


@pytest.mark.asyncio
async def test_list_clients_pagination_and_include_deleted(client, db_session):
    """客户列表分页 + include_deleted 过滤。"""
    from app.models.client import Client

    active_c = Client(
        client_id="list_active_1", username="list_active_1",
        password_hash="x", status="active",
    )
    deleted_c = Client(
        client_id="list_deleted_1", username="list_deleted_1",
        password_hash="x", status="deleted",
    )
    db_session.add_all([active_c, deleted_c])
    await db_session.commit()

    try:
        # include_deleted=false → 只返回 active（deleted 不在结果中）
        resp = await client.get(
            "/api/v1/admin/clients?include_deleted=false",
            headers=_admin_headers(),
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        client_ids = {it["client_id"] for it in items}
        assert "list_active_1" in client_ids
        assert "list_deleted_1" not in client_ids

        # include_deleted=true → 两个都返回
        resp = await client.get(
            "/api/v1/admin/clients?include_deleted=true",
            headers=_admin_headers(),
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        client_ids = {it["client_id"] for it in items}
        assert "list_active_1" in client_ids
        assert "list_deleted_1" in client_ids

        # page=1&page_size=1 → 返回 1 个
        resp = await client.get(
            "/api/v1/admin/clients?page=1&page_size=1",
            headers=_admin_headers(),
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 1
    finally:
        await db_session.delete(active_c)
        await db_session.delete(deleted_c)
        await db_session.commit()


@pytest.mark.asyncio
async def test_delete_client_soft_delete(client, db_session):
    """DELETE 软删除客户（status=deleted，不真删）。"""
    from app.models.client import Client
    from app.models.admin_audit_log import AdminAuditLog
    from sqlalchemy import select, delete

    c = Client(
        client_id="del_soft_test", username="del_soft",
        password_hash="x", status="active",
    )
    db_session.add(c)
    await db_session.commit()

    try:
        # DELETE → 200, status=deleted
        resp = await client.delete(
            f"/api/v1/admin/clients/{c.client_id}",
            headers=_admin_headers(),
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "deleted"

        # 查 DB 确认软删除（status=deleted，记录仍在）
        # refresh 以获取 HTTP 请求通过另一 session 写入的最新状态
        await db_session.refresh(c)
        assert c.status == "deleted", "客户未被软删除"

        # 审计日志断言：delete_client 已写入
        audit_result = await db_session.execute(
            select(AdminAuditLog).where(
                AdminAuditLog.action == "delete_client",
                AdminAuditLog.target_id == "del_soft_test",
            )
        )
        assert audit_result.scalar_one_or_none() is not None, "审计日志未写入"

        # DELETE 不存在的 client_id → 404
        resp = await client.delete(
            "/api/v1/admin/clients/non_existent_del_test",
            headers=_admin_headers(),
        )
        assert resp.status_code == 404
    finally:
        await db_session.delete(c)
        await db_session.execute(
            delete(AdminAuditLog).where(AdminAuditLog.target_id == "del_soft_test")
        )
        await db_session.commit()


@pytest.mark.asyncio
async def test_create_client_site_normalizes_domain(client, db_session):
    """POST /client_sites 标准化 domain（去 www）+ 唯一性检查。"""
    from app.models.client import Client, ClientSite
    from app.models.admin_audit_log import AdminAuditLog
    from sqlalchemy import select, delete

    # 先创建一个 client（client_site.client_id 是字符串引用）
    c = Client(
        client_id="site_norm_test", username="site_norm",
        password_hash="x", status="active",
    )
    db_session.add(c)
    await db_session.commit()

    site_id = None
    try:
        # POST domain="www.test-site.example.com" → 201, domain="test-site.example.com"
        resp = await client.post(
            "/api/v1/admin/client_sites",
            json={
                "client_id": "site_norm_test",
                "site_name": "测试站点",
                "domain": "www.test-site.example.com",
            },
            headers=_admin_headers(),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["domain"] == "test-site.example.com"
        site_id = data["id"]

        # 查 DB 确认 domain 已标准化
        result = await db_session.execute(
            select(ClientSite).where(ClientSite.domain == "test-site.example.com")
        )
        site = result.scalar_one_or_none()
        assert site is not None
        assert site.domain == "test-site.example.com"

        # 审计日志断言：create_client_site 已写入
        audit_result = await db_session.execute(
            select(AdminAuditLog).where(
                AdminAuditLog.action == "create_client_site",
                AdminAuditLog.target_id == site_id,
            )
        )
        assert audit_result.scalar_one_or_none() is not None, "审计日志未写入"

        # POST 同一 domain → 409（标准化后相同，唯一性冲突）
        resp = await client.post(
            "/api/v1/admin/client_sites",
            json={
                "client_id": "site_norm_test",
                "site_name": "重复站点",
                "domain": "www.test-site.example.com",
            },
            headers=_admin_headers(),
        )
        assert resp.status_code == 409
    finally:
        # 清理：site + client + 审计日志
        result = await db_session.execute(
            select(ClientSite).where(ClientSite.domain == "test-site.example.com")
        )
        s = result.scalar_one_or_none()
        if s is not None:
            await db_session.delete(s)
        await db_session.delete(c)
        if site_id is not None:
            await db_session.execute(
                delete(AdminAuditLog).where(AdminAuditLog.target_id == site_id)
            )
        await db_session.commit()


@pytest.mark.asyncio
async def test_update_client_reset_password_and_info(client, db_session):
    """PUT /clients 重置密码 + 编辑信息 + 校验。"""
    from app.models.client import Client
    from app.models.admin_audit_log import AdminAuditLog
    from app.core.security import hash_password, verify_password
    from sqlalchemy import select, delete

    c = Client(
        client_id="upd_pw_test", username="upd_pw",
        password_hash=hash_password("Pass1234"), status="active",
        company_name="旧公司",
    )
    db_session.add(c)
    await db_session.commit()

    try:
        # PUT 重置密码 + 改公司名
        resp = await client.put(
            f"/api/v1/admin/clients/{c.client_id}",
            json={"password": "NewPass5678", "company_name": "新公司"},
            headers=_admin_headers(),
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "active"  # status 未变

        # 查 DB 确认密码已重置 + 公司名已更新
        # refresh 以获取 HTTP 请求通过另一 session 写入的最新状态
        await db_session.refresh(c)
        assert verify_password("NewPass5678", c.password_hash), "密码未重置"
        assert not verify_password("Pass1234", c.password_hash), "旧密码仍可用"
        assert c.company_name == "新公司"

        # 审计日志断言：update_client 已写入
        audit_result = await db_session.execute(
            select(AdminAuditLog).where(
                AdminAuditLog.action == "update_client",
                AdminAuditLog.target_id == "upd_pw_test",
            )
        )
        assert audit_result.scalar_one_or_none() is not None, "审计日志未写入"

        # PUT 无效 status → 400
        resp = await client.put(
            f"/api/v1/admin/clients/{c.client_id}",
            json={"status": "invalid_status"},
            headers=_admin_headers(),
        )
        assert resp.status_code == 400

        # PUT 不存在的 client_id → 404
        resp = await client.put(
            "/api/v1/admin/clients/non_existent_upd_test",
            json={"company_name": "不存在"},
            headers=_admin_headers(),
        )
        assert resp.status_code == 404
    finally:
        await db_session.delete(c)
        await db_session.execute(
            delete(AdminAuditLog).where(AdminAuditLog.target_id == "upd_pw_test")
        )
        await db_session.commit()
