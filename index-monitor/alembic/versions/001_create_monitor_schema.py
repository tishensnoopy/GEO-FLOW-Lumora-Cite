"""create monitor schema

Revision ID: 001
Revises:
Create Date: 2026-07-25

为监测系统建立独立的 monitor schema 命名空间：
- GEOFlow 的表保留在 public schema（不受影响）
- 监测系统的所有表将位于 monitor schema
- 监测系统对 public schema 只读（SELECT）
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # IF NOT EXISTS 让迁移幂等——已存在时不会报错
    op.execute("CREATE SCHEMA IF NOT EXISTS monitor")


def downgrade() -> None:
    # CASCADE 同时删除 schema 下所有表，回滚需谨慎
    op.execute("DROP SCHEMA IF EXISTS monitor CASCADE")
