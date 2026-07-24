"""move monitor tables from public to monitor schema

Revision ID: 002
Revises: 001
Create Date: 2026-07-25

把监测系统的 7 张业务表从 public schema 迁移到 monitor schema：

- clients
- client_sites
- article_distributions
- citation_results
- index_results
- index_history
- system_config

设计要点
========

1. **幂等性**：使用 ``ALTER TABLE IF EXISTS public.xxx SET SCHEMA monitor``。
   如果表已经在 monitor schema（不在 public），命令静默跳过，可重复执行。

2. **article_distributions 同名冲突保护**：
   GEOFlow 也有 ``article_distributions`` 表（在 public schema）。监测系统的
   ``article_distributions`` 有 ``client_id`` 列，GEOFlow 的没有（GEOFlow 的
   外键列叫 ``distribution_channel_id``）。迁移通过 DO 块检查列是否存在，
   只移动监测系统的表，绝不误伤 GEOFlow 的同名表。

3. **alembic_version 表不动**：版本表保留在 public schema，避免与 GEOFlow
   的 alembic_version 冲突（Laravel migrations 也用 public schema）。

4. **索引随表迁移**：``ALTER TABLE ... SET SCHEMA`` 会自动把表上的索引
   一起搬到目标 schema，无需单独处理。

5. **回滚（downgrade）**：把表从 monitor 搬回 public。同样使用 IF EXISTS
   保证幂等。回滚时 article_distributions 也用 DO 块保护，避免把监测系统
   的表搬回 public 后与 GEOFlow 同名表冲突（仅在合并部署场景才会冲突，
   独立监测系统 PG 不会）。
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# 监测系统的 7 张业务表（不含 alembic_version，版本表留 public）
MONITOR_TABLES = [
    "clients",
    "client_sites",
    "article_distributions",  # 特殊处理：需区分 GEOFlow 同名表
    "citation_results",
    "index_results",
    "index_history",
    "system_config",
]


def upgrade() -> None:
    # article_distributions 特殊处理：GEOFlow 也有同名表在 public schema。
    # 监测系统的 article_distributions 有 client_id 列，GEOFlow 的没有。
    # 只移动监测系统的表，避免误伤 GEOFlow。
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'article_distributions'
                  AND column_name = 'client_id'
            ) THEN
                ALTER TABLE public.article_distributions SET SCHEMA monitor;
            END IF;
        END $$;
        """
    )

    # 其余 6 张表是监测系统专属，GEOFlow 没有同名表，可直接 IF EXISTS 移动
    for table_name in MONITOR_TABLES:
        if table_name == "article_distributions":
            continue  # 已在上面特殊处理
        op.execute(
            f"ALTER TABLE IF EXISTS public.{table_name} SET SCHEMA monitor"
        )


def downgrade() -> None:
    # 回滚：把表从 monitor 搬回 public
    # article_distributions 同样需要保护：如果 public 已有 GEOFlow 同名表，不搬回
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'monitor'
                  AND table_name = 'article_distributions'
            ) AND NOT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_name = 'article_distributions'
            ) THEN
                ALTER TABLE monitor.article_distributions SET SCHEMA public;
            END IF;
        END $$;
        """
    )

    for table_name in MONITOR_TABLES:
        if table_name == "article_distributions":
            continue  # 已在上面特殊处理
        op.execute(
            f"ALTER TABLE IF EXISTS monitor.{table_name} SET SCHEMA public"
        )
