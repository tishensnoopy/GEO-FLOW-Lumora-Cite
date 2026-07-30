# index-monitor/alembic/versions/014_add_client_question_id_to_citation_results.py
"""add client_question_id to citation_results

Revision ID: 014
Revises: 013
Create Date: 2026-07-30

citation_results 新增 client_question_id 外键，关联 client_questions 表。
记录每条检测结果是用哪条客户问题检测的。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "014"
down_revision: Union[str, None] = "013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "citation_results",
        sa.Column("client_question_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
        schema="monitor",
    )
    op.create_index(
        "ix_citation_results_client_question_id",
        "citation_results",
        ["client_question_id"],
        schema="monitor",
    )


def downgrade() -> None:
    op.drop_index("ix_citation_results_client_question_id", table_name="citation_results", schema="monitor")
    op.drop_column("citation_results", "client_question_id", schema="monitor")
