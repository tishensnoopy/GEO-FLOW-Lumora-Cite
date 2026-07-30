# index-monitor/tests/unit/test_audit_log_service.py
"""AuditLogService 测试。设计文档第 10 节。"""
import json
import pytest

from app.services.audit_log import AuditLogService


@pytest.mark.asyncio
async def test_log_creates_audit_record(db_session):
    """log 方法创建审计日志记录。"""
    await AuditLogService.log(
        db_session,
        admin_user_id=1,
        admin_name="测试管理员",
        action="create_client",
        target_type="client",
        target_id="client_001",
        detail={"client_id": "client_001", "company_name": "测试公司"},
    )

    from app.models.admin_audit_log import AdminAuditLog
    from sqlalchemy import select
    try:
        result = await db_session.execute(
            select(AdminAuditLog).where(AdminAuditLog.action == "create_client")
        )
        log = result.scalar_one()
        assert log.admin_user_id == 1
        assert log.admin_name == "测试管理员"
        assert log.target_type == "client"
        assert log.target_id == "client_001"
        detail = json.loads(log.detail)
        assert detail["client_id"] == "client_001"

        # 清理
        await db_session.delete(log)
        await db_session.commit()
    finally:
        # 断言失败也确保清理：再查一次，若记录仍在则删除
        leftover = await db_session.execute(
            select(AdminAuditLog).where(AdminAuditLog.action == "create_client")
        )
        leftover_log = leftover.scalar_one_or_none()
        if leftover_log is not None:
            await db_session.delete(leftover_log)
            await db_session.commit()


@pytest.mark.asyncio
async def test_log_with_minimal_fields(db_session):
    """只传必填字段（action + admin_user_id + admin_name）也能创建。"""
    await AuditLogService.log(
        db_session,
        admin_user_id=2,
        admin_name="管理员B",
        action="sso_login",
    )

    from app.models.admin_audit_log import AdminAuditLog
    from sqlalchemy import select
    try:
        result = await db_session.execute(
            select(AdminAuditLog).where(
                AdminAuditLog.admin_user_id == 2,
                AdminAuditLog.action == "sso_login",
            )
        )
        log = result.scalar_one()
        assert log.target_type is None
        assert log.detail is None

        await db_session.delete(log)
        await db_session.commit()
    finally:
        # 断言失败也确保清理：再查一次，若记录仍在则删除
        leftover = await db_session.execute(
            select(AdminAuditLog).where(
                AdminAuditLog.admin_user_id == 2,
                AdminAuditLog.action == "sso_login",
            )
        )
        leftover_log = leftover.scalar_one_or_none()
        if leftover_log is not None:
            await db_session.delete(leftover_log)
            await db_session.commit()
