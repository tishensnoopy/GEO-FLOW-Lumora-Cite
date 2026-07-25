# index-monitor/alembic/versions/005_create_export_tasks.py
"""create export_tasks table

Revision ID: 005
Revises: 004
Create Date: 2026-07-25
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "export_tasks",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("client_id", sa.String(64), nullable=True, index=True),
        sa.Column("requested_by", sa.String(128), nullable=False),
        sa.Column("requested_by_role", sa.String(32), nullable=False),
        sa.Column("export_type", sa.String(16), nullable=False),
        sa.Column("date_from", sa.Date, nullable=True),
        sa.Column("date_to", sa.Date, nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending", index=True),
        sa.Column("file_path", sa.String(512), nullable=True),
        sa.Column("file_size", sa.Integer, nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        schema="monitor",
    )


def downgrade() -> None:
    op.drop_table("export_tasks", schema="monitor")
