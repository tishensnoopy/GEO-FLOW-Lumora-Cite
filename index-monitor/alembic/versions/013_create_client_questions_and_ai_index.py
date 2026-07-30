# index-monitor/alembic/versions/013_create_client_questions_and_ai_index.py
"""create client_questions and ai_index_results tables

Revision ID: 013
Revises: 012
Create Date: 2026-07-30

AI 监测逻辑重构 Phase 1：
- client_questions：客户监测问题集（替代 LLM 自动生成）
- ai_index_results：AI 收录检测结果（收录检测先行，仅对已收录 URL 做问题监测）
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "013"
down_revision: Union[str, None] = "012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- client_questions ---
    op.create_table(
        "client_questions",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column("client_id", sa.String(64), nullable=False),
        sa.Column("question", sa.Text, nullable=False),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        schema="monitor",
    )
    op.create_index(
        "ix_client_questions_client_id",
        "client_questions",
        ["client_id"],
        schema="monitor",
    )
    op.create_index(
        "ix_client_questions_status",
        "client_questions",
        ["status"],
        schema="monitor",
    )

    # --- ai_index_results ---
    op.create_table(
        "ai_index_results",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column("url", sa.String(512), nullable=False),
        sa.Column("model", sa.String(64), nullable=False),
        sa.Column("index_status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("ai_response", sa.Text, nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "url", "model", name="uq_ai_index_url_model",
        ),
        schema="monitor",
    )
    op.create_index(
        "ix_ai_index_results_url",
        "ai_index_results",
        ["url"],
        schema="monitor",
    )
    op.create_index(
        "ix_ai_index_results_model",
        "ai_index_results",
        ["model"],
        schema="monitor",
    )
    op.create_index(
        "ix_ai_index_results_index_status",
        "ai_index_results",
        ["index_status"],
        schema="monitor",
    )


def downgrade() -> None:
    op.drop_table("ai_index_results", schema="monitor")
    op.drop_table("client_questions", schema="monitor")
