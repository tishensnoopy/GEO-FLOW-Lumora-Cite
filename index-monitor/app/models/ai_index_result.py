# index-monitor/app/models/ai_index_result.py
"""AI 收录检测结果模型。

记录每个 URL × AI 模型 的收录检测状态。
收录检测在问题监测之前执行：仅对 index_status='indexed' 的组合做问题监测。

状态流转：pending → indexed / not_indexed
- pending：尚未检测或检测失败（可重试）
- indexed：AI 回复中包含对该 URL 内容的实质描述
- not_indexed：AI 回复"不了解"/"不知道"等否定短语
"""
from sqlalchemy import Column, String, Text, DateTime, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.models.base import Base, monitor_table_args
import uuid


class AIIndexResult(Base):
    __tablename__ = "ai_index_results"
    __table_args__ = monitor_table_args(
        UniqueConstraint("url", "model", name="uq_ai_index_url_model"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    url = Column(String(512), nullable=False, index=True)
    model = Column(String(64), nullable=False, index=True)
    index_status = Column(String(32), nullable=False, default="pending", index=True)
    ai_response = Column(Text, nullable=True)
    checked_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
