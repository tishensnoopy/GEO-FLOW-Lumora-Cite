# index-monitor/app/models/article.py
from sqlalchemy import Column, String, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.models.base import Base, monitor_table_args
import uuid


class ArticleDistribution(Base):
    __tablename__ = "article_distributions"
    __table_args__ = monitor_table_args()

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    article_id = Column(String(255), nullable=False)
    client_id = Column(String(64), nullable=False, index=True)
    remote_url = Column(String(512), nullable=False, index=True)
    status = Column(String(32), nullable=False, default="synced", index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
