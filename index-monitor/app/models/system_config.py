# index-monitor/app/models/system_config.py
# 修复任务 1 - Fix 2：映射 Task 1 init-db.sh 的 system_config 表
# 字段一一对应：id UUID, config_key, config_value, config_type, description, updated_at
from sqlalchemy import Column, String, Text, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.models.base import Base, monitor_table_args
import uuid


class SystemConfig(Base):
    __tablename__ = "system_config"
    __table_args__ = monitor_table_args()

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    config_key = Column(String(128), unique=True, nullable=False)
    config_value = Column(Text, nullable=False)
    config_type = Column(String(32), nullable=False)
    description = Column(Text)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
