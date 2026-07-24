# index-monitor/app/models/index_result.py
from sqlalchemy import Column, String, DateTime, Text, ARRAY, Integer, Date, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.models.base import Base, monitor_table_args
import uuid


class IndexResult(Base):
    __tablename__ = "index_results"
    __table_args__ = monitor_table_args()

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    url = Column(String(512), nullable=False, unique=True, index=True)
    client_id = Column(String(64), nullable=False, index=True)
    site_type = Column(String(32), nullable=False, index=True)
    content_title = Column(String(512))
    content_keywords = Column(ARRAY(Text))
    content_snapshot = Column(Text)
    baidu_status = Column(String(32), default="pending")
    toutiao_status = Column(String(32), default="pending")
    sogou_status = Column(String(32), default="pending")
    so360_status = Column(String(32), default="pending")
    bing_status = Column(String(32), default="pending")
    baidu_checked_at = Column(DateTime(timezone=True))
    toutiao_checked_at = Column(DateTime(timezone=True))
    sogou_checked_at = Column(DateTime(timezone=True))
    so360_checked_at = Column(DateTime(timezone=True))
    bing_checked_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class IndexHistory(Base):
    __tablename__ = "index_history"
    # 控制者裁定 2：DB 有 UNIQUE(url, check_date)，模型须声明同名约束
    # schema dict 由 monitor_table_args 自动附加在元组末尾
    __table_args__ = monitor_table_args(
        UniqueConstraint("url", "check_date", name="index_history_url_check_date_key"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    url = Column(String(512), nullable=False, index=True)
    # 控制者裁定 1：DB 是 DATE，简报的 DateTime(timezone=True) 须改为 Date
    check_date = Column(Date, nullable=False, index=True)
    baidu_status = Column(String(32), nullable=False)
    toutiao_status = Column(String(32), nullable=False)
    sogou_status = Column(String(32), nullable=False)
    so360_status = Column(String(32), nullable=False)
    bing_status = Column(String(32), nullable=False)
    total_indexed = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
