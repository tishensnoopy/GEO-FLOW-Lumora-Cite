# index-monitor/alembic/versions/010_add_content_title_and_fix_model.py
"""add content_title to manual_distributions + fix ai_question_model default

Revision ID: 010
Revises: 009
Create Date: 2026-07-26

修复两个问题：

1. manual_distributions 缺 content_title 列
   003 迁移创建 manual_distributions 时未包含 content_title，导致
   admin_routes.create_manual_distribution 抓取到文章标题后写入失败
  （原代码还缺 update/ManualDistribution 导入，NameError 被 except
   静默吞掉）。本迁移补列。

2. system_config.ai_question_model 默认值 'deepseek-chat' 已被废弃
   DeepSeek API 于 2026 年废弃 deepseek-chat 模型名，当前支持
   deepseek-v4-pro / deepseek-v4-flash。init-db.sh 的 INSERT 和
   既有数据库中存的 'deepseek-chat' 会导致采信检测调用失败。
   本迁移将已存的 'deepseek-chat' 更新为 'deepseek-v4-flash'。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "010"
down_revision: Union[str, None] = "009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. manual_distributions 补 content_title 列（幂等：IF NOT EXISTS）
    op.execute(
        "ALTER TABLE monitor.manual_distributions "
        "ADD COLUMN IF NOT EXISTS content_title VARCHAR(512)"
    )

    # 2. 修正 ai_question_model：deepseek-chat → deepseek-v4-flash
    op.execute(
        "UPDATE monitor.system_config "
        "SET config_value = 'deepseek-v4-flash', updated_at = CURRENT_TIMESTAMP "
        "WHERE config_key = 'ai_question_model' AND config_value = 'deepseek-chat'"
    )


def downgrade() -> None:
    # 回滚：移除 content_title 列（数据会丢失，仅用于开发环境回滚）
    op.execute(
        "ALTER TABLE monitor.manual_distributions "
        "DROP COLUMN IF EXISTS content_title"
    )
    # 不回滚 ai_question_model 的值（deepseek-chat 已废弃，回滚会导致 API 调用失败）
