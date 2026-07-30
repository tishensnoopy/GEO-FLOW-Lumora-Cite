# index-monitor/app/models/client_question.py
"""客户监测问题模型。

每个客户维护一组 AI 监测问题，用于问题监测阶段（替代自动生成）。
启用的问题（status='active'）将用于该客户所有文章的 AI 引用检测。
运营在客户管理界面配置，客户端只读查看。
"""
from sqlalchemy import Column, String, Text, Integer, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.models.base import Base, monitor_table_args
import uuid


class ClientQuestion(Base):
    __tablename__ = "client_questions"
    __table_args__ = monitor_table_args()

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id = Column(String(64), nullable=False, index=True)
    question = Column(Text, nullable=False)
    sort_order = Column(Integer, nullable=False, default=0)
    status = Column(String(32), nullable=False, default="active", index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
