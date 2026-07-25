# index-monitor/alembic/versions/003_create_manual_distributions.py
"""create manual_distributions table

Revision ID: 003
Revises: 002
Create Date: 2026-07-25

新建 monitor.manual_distributions 表——运营手动录入的 URL 分发记录。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "manual_distributions",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("client_id", sa.String(64), nullable=False, index=True),
        sa.Column("remote_url", sa.String(512), nullable=False, index=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="synced", index=True),
        sa.Column("note", sa.Text, nullable=True),
        sa.Column("created_by_admin_id", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("client_id", "remote_url", name="uq_manual_client_url"),
        schema="monitor",
    )


def downgrade() -> None:
    op.drop_table("manual_distributions", schema="monitor")
