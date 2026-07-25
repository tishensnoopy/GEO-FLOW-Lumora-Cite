# index-monitor/alembic/versions/006_create_archived_distributions.py
"""create archived_distributions table

Revision ID: 006
Revises: 005
Create Date: 2026-07-25
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "archived_distributions",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("client_id", sa.String(64), nullable=False, index=True),
        sa.Column("remote_url", sa.String(512), nullable=False, index=True),
        sa.Column("geoflow_article_id", sa.Integer, nullable=True),
        sa.Column("content_title", sa.String(512), nullable=True),
        sa.Column("content_slug", sa.String(255), nullable=True),
        sa.Column("content_excerpt", sa.Text, nullable=True),
        sa.Column("content_body", sa.Text, nullable=True),
        sa.Column("content_keywords", sa.dialects.postgresql.JSON, nullable=True),
        sa.Column("meta_description", sa.Text, nullable=True),
        sa.Column("original_keyword", sa.String(255), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("archived_reason", sa.String(64), server_default="geoflow_deleted"),
        schema="monitor",
    )


def downgrade() -> None:
    op.drop_table("archived_distributions", schema="monitor")
