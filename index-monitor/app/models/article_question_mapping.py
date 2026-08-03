# index-monitor/app/models/article_question_mapping.py
"""文章→客户问题关联模型（AI 自动推断）。

每篇发稿通过 DeepSeek 分析内容后，自动关联 1-3 个最相关的客户问题。
引用检测时只检测关联的问题，避免组合爆炸。
"""
from sqlalchemy import Column, Float, DateTime, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.models.base import Base, monitor_table_args
import uuid


class ArticleQuestionMapping(Base):
    __tablename__ = "article_question_mappings"
    __table_args__ = monitor_table_args(
        UniqueConstraint(
            "distribution_id", "client_question_id",
            name="uq_article_question",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    distribution_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    client_question_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    relevance_score = Column(Float, nullable=False, default=0.0)
    inferred_at = Column(DateTime(timezone=True), server_default=func.now())
    created_at = Column(DateTime(timezone=True), server_default=func.now())
