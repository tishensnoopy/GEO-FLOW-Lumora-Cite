# index-monitor/alembic/versions/016_add_citation_calibrations.py
"""add citation_calibrations table

Revision ID: 016_citation_calibrations
Revises: 015_article_question_mappings
Create Date: 2026-08-03

引用检测校准结果表（阶段 4）。
存储网页端模拟对 API 引用检测结果的校准数据。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision: str = "016_citation_calibrations"
down_revision: Union[str, None] = "015_article_question_mappings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "citation_calibrations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("citation_result_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("platform_id", sa.String(64), nullable=False),
        sa.Column("web_answer", sa.Text),
        sa.Column("web_sources", JSONB),
        sa.Column("web_hit_type", sa.String(32)),
        sa.Column("api_hit_type", sa.String(32)),
        sa.Column("matches", sa.Boolean, nullable=False),
        sa.Column("note", sa.Text),
        sa.Column("calibrated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "citation_result_id", "platform_id",
            name="uq_calibration_result_platform",
        ),
        schema="monitor",
    )


def downgrade() -> None:
    op.drop_table("citation_calibrations", schema="monitor")
