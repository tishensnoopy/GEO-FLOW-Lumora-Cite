# index-monitor/app/models/citation_result.py
from sqlalchemy import Column, String, DateTime, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
from app.models.base import Base, monitor_table_args
import uuid


class CitationResult(Base):
    __tablename__ = "citation_results"
    # 控制者裁定 2：DB 有 UNIQUE(url, model, question)，模型须声明同名约束
    # schema dict 由 monitor_table_args 自动附加在元组末尾
    __table_args__ = monitor_table_args(
        UniqueConstraint("url", "model", "question", name="citation_results_url_model_question_key"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    url = Column(String(512), nullable=False, index=True)
    model = Column(String(64), nullable=False, index=True)
    question = Column(Text, nullable=False)
    answer = Column(Text)
    hit_type = Column(String(32), nullable=False, index=True)
    sources = Column(JSONB)
    checked_at = Column(DateTime(timezone=True), server_default=func.now())
    # AI 监测重构：关联客户问题（null 表示旧数据，由自动生成问题产生）
    client_question_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
