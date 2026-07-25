# index-monitor/app/models/export_task.py
"""导出任务记录。

异步导出 PDF/Excel 时先创建任务记录（status='pending'），后台处理完成后
更新 status='completed' + file_path。设计文档第 12.6 节。

状态机：pending → processing → completed / failed

charts 字段（M4 补全）：JSONB，存储前端 ECharts getDataURL() 生成的
base64 数据 URL 字典，如 {"trend": "data:image/png;base64,...", "pie": "..."}。
设计文档第 12.4 节：图表用 base64 内联。
"""
from sqlalchemy import Column, String, DateTime, Text, Integer, Date
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func

from app.models.base import Base, monitor_table_args
import uuid


class ExportTask(Base):
    __tablename__ = "export_tasks"
    __table_args__ = monitor_table_args()

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id = Column(String(64), nullable=True, index=True)  # null = 全部客户（admin 导出）
    requested_by = Column(String(128), nullable=False)  # admin username 或 client_id
    requested_by_role = Column(String(32), nullable=False)  # 'admin' | 'client'
    export_type = Column(String(16), nullable=False)  # 'pdf' | 'excel'
    date_from = Column(Date, nullable=True)
    date_to = Column(Date, nullable=True)
    status = Column(String(32), default="pending", nullable=False, index=True)
    file_path = Column(String(512), nullable=True)
    file_size = Column(Integer, nullable=True)
    error_message = Column(Text, nullable=True)
    charts = Column(JSONB, nullable=True)  # 图表 base64 数据 URL 字典（M4 补全）
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)
