# index-monitor/app/services/audit_log.py
"""操作审计日志服务。

设计文档第 10 节。记录 admin 的所有操作，用于合规追溯。

action 清单（设计文档第 10.2 节）：
- sso_login: admin SSO 登录
- create_client / update_client / deactivate_client / delete_client / restore_client
- create_client_site / update_client_site / delete_client_site
- manual_create_distribution / delete_distribution
- trigger_index_scan / trigger_citation_scan / batch_scan
- reset_client_password
- create_export
"""
import json
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admin_audit_log import AdminAuditLog


class AuditLogService:
    @staticmethod
    async def log(
        db: AsyncSession,
        admin_user_id: int,
        admin_name: str,
        action: str,
        target_type: Optional[str] = None,
        target_id: Optional[str] = None,
        detail: Optional[dict] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> AdminAuditLog:
        """记录一条审计日志并提交。

        Parameters
        ----------
        db : AsyncSession
            数据库会话。
        admin_user_id : int
            GEOFlow admins.id。
        admin_name : str
            操作时 admin 显示名（冗余存储）。
        action : str
            操作类型（见模块 docstring 清单）。
        target_type : str | None
            操作对象类型（client/distribution/client_site/export_task）。
        target_id : str | None
            操作对象 ID。
        detail : dict | None
            操作详情，序列化为 JSON 字符串存储。
        ip_address : str | None
            请求来源 IP。
        user_agent : str | None
            请求 User-Agent。

        Returns
        -------
        AdminAuditLog
            已创建的日志记录。
        """
        log_entry = AdminAuditLog(
            admin_user_id=admin_user_id,
            admin_name=admin_name,
            action=action,
            target_type=target_type,
            target_id=target_id,
            detail=json.dumps(detail, ensure_ascii=False) if detail else None,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        db.add(log_entry)
        await db.commit()
        return log_entry
