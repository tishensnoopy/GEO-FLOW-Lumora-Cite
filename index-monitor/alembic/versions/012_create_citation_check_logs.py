# index-monitor/alembic/versions/012_create_citation_check_logs.py
"""create citation_check_logs table

Revision ID: 012
Revises: 011
Create Date: 2026-07-29

阶段 1 - ④a：采信检测过程日志表。
持久化单 URL 采信检测的 5 阶段执行日志，供 ScanPanel 终端面板
按 task_id 拉取实时进度，解决"采信检测黑盒"问题。

索引：
- task_id / url / created_at 单列索引
- (task_id, created_at) 组合索引：按任务拉取时序日志的主查询路径
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "012"
down_revision: Union[str, None] = "011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "citation_check_logs",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        # task_id 可空：定时任务无 task_id，手动触发才有
        sa.Column("task_id", sa.String(64), nullable=True),
        sa.Column("url", sa.String(512), nullable=False),
        sa.Column("stage", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        # model 可空：非模型阶段（抓取/目的推断/问题生成）无 model
        sa.Column("model", sa.String(64), nullable=True),
        sa.Column("detail", sa.dialects.postgresql.JSONB, nullable=True),
        sa.Column("duration_ms", sa.Integer, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        schema="monitor",
    )
    # 单列索引
    op.create_index(
        "ix_citation_check_logs_task_id",
        "citation_check_logs",
        ["task_id"],
        schema="monitor",
    )
    op.create_index(
        "ix_citation_check_logs_url",
        "citation_check_logs",
        ["url"],
        schema="monitor",
    )
    op.create_index(
        "ix_citation_check_logs_created_at",
        "citation_check_logs",
        ["created_at"],
        schema="monitor",
    )
    # 组合索引：按 task_id 拉取时序日志的主查询路径
    op.create_index(
        "ix_citation_check_logs_task_id_created_at",
        "citation_check_logs",
        ["task_id", "created_at"],
        schema="monitor",
    )


def downgrade() -> None:
    op.drop_table("citation_check_logs", schema="monitor")
