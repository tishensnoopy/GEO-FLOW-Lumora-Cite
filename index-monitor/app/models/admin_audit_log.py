# index-monitor/app/models/admin_audit_log.py
"""管理员操作审计日志。

记录 admin 在监测系统的所有操作（创建客户/录入 URL/触发检测/导出等），
用于合规追溯。设计文档第 10 节。

字段说明：
- admin_user_id：GEOFlow admins.id（SSO 传递）
- admin_name：操作时 admin 显示名（冗余存储，避免 admin 改名后日志失联）
- action：操作类型（见设计文档第 10.2 节 action 清单）
- target_type/target_id：操作对象（client/distribution/client_site/export_task）
- detail：JSON 字符串，操作详情（如 {"url": "...", "client_id": "..."}）
- ip_address/user_agent：请求来源（合规留痕）
"""
from sqlalchemy import Column, String, DateTime, Text, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.models.base import Base, monitor_table_args
import uuid


class AdminAuditLog(Base):
    __tablename__ = "admin_audit_logs"
    __table_args__ = monitor_table_args()

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    admin_user_id = Column(Integer, nullable=False, index=True)
    admin_name = Column(String(128), nullable=False)
    action = Column(String(64), nullable=False, index=True)
    target_type = Column(String(32), nullable=True)
    target_id = Column(String(64), nullable=True)
    detail = Column(Text, nullable=True)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(512), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
