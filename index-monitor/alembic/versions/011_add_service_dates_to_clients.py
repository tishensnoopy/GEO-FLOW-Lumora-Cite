"""add service_start_date and service_end_date to clients

Revision ID: 011
Revises: 010
Create Date: 2026-07-28

修复 007 迁移遗漏：Client 模型定义了 service_start_date / service_end_date
（设计文档第 6.1 节服务周期），但 007 迁移未添加这两列，导致查询 clients
表时抛出 UndefinedColumnError。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "011"
down_revision: Union[str, None] = "010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "clients",
        sa.Column("service_start_date", sa.Date, nullable=True),
        schema="monitor",
    )
    op.add_column(
        "clients",
        sa.Column("service_end_date", sa.Date, nullable=True),
        schema="monitor",
    )


def downgrade() -> None:
    op.drop_column("clients", "service_end_date", schema="monitor")
    op.drop_column("clients", "service_start_date", schema="monitor")
