# index-monitor/app/models/citation_calibration.py
"""引用检测校准结果模型（阶段 4）。

存储网页端模拟对 API 引用检测结果的校准数据：
- 对 citation_results 中的每条记录，用网页端模拟重新检测
- 对比 API hit_type vs 网页端 hit_type
- 用于计算平台置信度
"""
from sqlalchemy import Column, String, DateTime, Text, Boolean, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func

from app.models.base import Base, monitor_table_args
import uuid


class CitationCalibration(Base):
    __tablename__ = "citation_calibrations"
    __table_args__ = monitor_table_args(
        UniqueConstraint(
            "citation_result_id", "platform_id",
            name="uq_calibration_result_platform",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    citation_result_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    platform_id = Column(String(64), nullable=False)
    web_answer = Column(Text)
    web_sources = Column(JSONB)
    web_hit_type = Column(String(32))
    api_hit_type = Column(String(32))
    matches = Column(Boolean, nullable=False)
    note = Column(Text)
    calibrated_at = Column(DateTime(timezone=True), server_default=func.now())
    created_at = Column(DateTime(timezone=True), server_default=func.now())
