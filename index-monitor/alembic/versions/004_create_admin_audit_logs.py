# index-monitor/alembic/versions/004_create_admin_audit_logs.py
"""create admin_audit_logs table

Revision ID: 004
Revises: 003
Create Date: 2026-07-25
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "admin_audit_logs",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("admin_user_id", sa.Integer, nullable=False, index=True),
        sa.Column("admin_name", sa.String(128), nullable=False),
        sa.Column("action", sa.String(64), nullable=False, index=True),
        sa.Column("target_type", sa.String(32), nullable=True),
        sa.Column("target_id", sa.String(64), nullable=True),
        sa.Column("detail", sa.Text, nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), index=True),
        schema="monitor",
    )


def downgrade() -> None:
    op.drop_table("admin_audit_logs", schema="monitor")
