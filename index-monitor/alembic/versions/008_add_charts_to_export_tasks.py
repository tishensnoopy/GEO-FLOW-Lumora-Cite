# index-monitor/alembic/versions/008_add_charts_to_export_tasks.py
"""add charts column to export_tasks

Revision ID: 008
Revises: 007
Create Date: 2026-07-25

M4 补全：ExportTask 加 charts JSONB 列，存储前端 ECharts getDataURL()
生成的 base64 数据 URL 字典。设计文档第 12.4 节。
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "export_tasks",
        sa.Column("charts", JSONB, nullable=True),
        schema="monitor",
    )


def downgrade():
    op.drop_column("export_tasks", "charts", schema="monitor")
