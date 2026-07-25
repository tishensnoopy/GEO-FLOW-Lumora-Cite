# index-monitor/app/models/archived_distribution.py
"""GEOFlow 文章删除后的归档分发记录。

当 GEOFlow 侧文章被删除（article_distributions.status != 'synced' 或记录消失），
监测系统定时任务将该分发记录的历史数据归档到本表，保留文章内容快照。
设计文档第 21.4 节。

查询时 DistributionQueryService 同时查 GEOFlow 实时表 + 本归档表，
合并结果，归档记录标注 source='archived'。
"""
from sqlalchemy import Column, String, DateTime, Text, Integer
from sqlalchemy.dialects.postgresql import UUID, JSON
from sqlalchemy.sql import func

from app.models.base import Base, monitor_table_args
import uuid


class ArchivedDistribution(Base):
    __tablename__ = "archived_distributions"
    __table_args__ = monitor_table_args()

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id = Column(String(64), nullable=False, index=True)
    remote_url = Column(String(512), nullable=False, index=True)
    geoflow_article_id = Column(Integer, nullable=True)
    # 文章快照（删除时的内容副本）
    content_title = Column(String(512), nullable=True)
    content_slug = Column(String(255), nullable=True)
    content_excerpt = Column(Text, nullable=True)
    content_body = Column(Text, nullable=True)
    content_keywords = Column(JSON, nullable=True)
    meta_description = Column(Text, nullable=True)
    original_keyword = Column(String(255), nullable=True)
    published_at = Column(DateTime(timezone=True), nullable=True)
    # 归档信息
    archived_at = Column(DateTime(timezone=True), server_default=func.now())
    archived_reason = Column(String(64), default="geoflow_deleted")
