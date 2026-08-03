# index-monitor/alembic/versions/015_add_article_question_mappings.py
"""add article_question_mappings table

Revision ID: 015_article_question_mappings
Revises: 014
Create Date: 2026-08-03

文章→客户问题关联表（AI 自动推断）。
每篇发稿通过 DeepSeek 分析内容后，自动关联 1-3 个最相关的客户问题。
引用检测时只检测关联的问题，避免组合爆炸。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "015_article_question_mappings"
down_revision: Union[str, None] = "014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "article_question_mappings",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("distribution_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("client_question_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("relevance_score", sa.Float, nullable=False, server_default="0"),
        sa.Column("inferred_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "distribution_id", "client_question_id",
            name="uq_article_question",
        ),
        schema="monitor",
    )


def downgrade() -> None:
    op.drop_table("article_question_mappings", schema="monitor")
