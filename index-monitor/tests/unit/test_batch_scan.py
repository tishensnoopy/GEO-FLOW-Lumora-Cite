# index-monitor/tests/unit/test_batch_scan.py
"""批量触发检测端点测试。设计文档第 9.1 节。

测试基础设施说明
================

本文件复用 ``tests/integration/test_admin_endpoints.py`` 的 ``_override_app_db``
模式：pytest-asyncio strict 模式为每个测试创建独立事件循环，
``app.core.database.engine`` 是模块级单例，其连接池里的 asyncpg 连接绑定到
首次 import 时的事件循环，跨测试复用会触发
"Future attached to a different loop"。用 FastAPI ``app.dependency_overrides``
把 ``get_db`` 替换为闭包，闭包内用本测试事件循环新建的 engine → session_factory
→ session。测试结束 dispose 这个临时 engine，不污染模块级 engine。
"""
import pytest
import pytest_asyncio
import jwt
from datetime import datetime, timedelta, timezone

from app.core.config import settings


@pytest_asyncio.fixture(autouse=True)
async def _override_app_db():
    """为每个测试 override ``get_db`` 依赖，使用当前事件循环的全新 engine。

    与 ``tests/integration/test_admin_endpoints.py::_override_app_db`` 一致，
    解决 pytest-asyncio strict 模式下模块级 engine 跨事件循环复用问题。
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


async def _cleanup_batch_scan_logs(db_session) -> None:
    """删除本测试产生的 action='batch_scan' 审计日志，避免污染其他测试。"""
    from app.models.admin_audit_log import AdminAuditLog
    from sqlalchemy import select

    leftover = await db_session.execute(
        select(AdminAuditLog).where(AdminAuditLog.action == "batch_scan")
    )
    for log in leftover.scalars().all():
        await db_session.delete(log)
    await db_session.commit()


@pytest.mark.asyncio
async def test_batch_scan_queues_index_check(client, db_session):
    """batch_scan scan_type=index 入队收录检测。"""
    try:
        resp = await client.post(
            "/api/v1/admin/distributions/batch-scan",
            json={"distribution_ids": ["id1", "id2", "id3"], "scan_type": "index"},
            headers=_admin_headers(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["queued"] == 3
        assert data["scan_type"] == "index"

        # 审计日志断言：端点在入队前必须写一条 action='batch_scan' 的日志，
        # detail 含 ids 和 type 字段。端点用的 db session 与本 fixture 不同
        # （_override_app_db 替换了 get_db），但同一 DB，且 AuditLogService.log
        # 已 commit，故 db_session 重新查询可见（READ COMMITTED）。
        from app.models.admin_audit_log import AdminAuditLog
        from sqlalchemy import select
        import json

        audit_result = await db_session.execute(
            select(AdminAuditLog).where(AdminAuditLog.action == "batch_scan")
        )
        audit_logs = audit_result.scalars().all()
        assert len(audit_logs) >= 1, "审计日志未写入"
        # 验证最新一条的 detail
        latest = audit_logs[-1]
        detail = json.loads(latest.detail) if isinstance(latest.detail, str) else latest.detail
        assert detail["ids"] == ["id1", "id2", "id3"], f"detail.ids 不匹配: {detail.get('ids')}"
        assert detail["type"] == "index", f"detail.type 不匹配: {detail.get('type')}"
    finally:
        await _cleanup_batch_scan_logs(db_session)


@pytest.mark.asyncio
async def test_batch_scan_queues_both(client, db_session):
    """scan_type=both 同时入队收录+采信。"""
    try:
        resp = await client.post(
            "/api/v1/admin/distributions/batch-scan",
            json={"distribution_ids": ["id1"], "scan_type": "both"},
            headers=_admin_headers(),
        )
        assert resp.status_code == 200
        assert resp.json()["queued"] == 1
    finally:
        await _cleanup_batch_scan_logs(db_session)


@pytest.mark.asyncio
async def test_batch_scan_invalid_type_returns_400(client, db_session):
    """无效 scan_type 返回 400。"""
    try:
        resp = await client.post(
            "/api/v1/admin/distributions/batch-scan",
            json={"distribution_ids": ["id1"], "scan_type": "invalid"},
            headers=_admin_headers(),
        )
        assert resp.status_code == 400
    finally:
        # invalid scan_type 不会写审计日志（端点在 log 之前 raise），但 finally 仍兜底清理
        await _cleanup_batch_scan_logs(db_session)


@pytest.mark.asyncio
async def test_batch_scan_empty_ids_returns_400(client, db_session):
    """空 distribution_ids 返回 400（端点 admin_routes.py:43-44 已实现）。"""
    try:
        resp = await client.post(
            "/api/v1/admin/distributions/batch-scan",
            json={"distribution_ids": [], "scan_type": "index"},
            headers=_admin_headers(),
        )
        assert resp.status_code == 400
    finally:
        # 400 在审计日志写入之前 raise，理论上无副作用；finally 仍兜底清理防御性
        await _cleanup_batch_scan_logs(db_session)
