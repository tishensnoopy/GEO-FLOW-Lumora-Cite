# index-monitor/alembic/versions/009_drop_monitor_article_distributions.py
"""drop orphan monitor.article_distributions table

Revision ID: 009
Revises: 008
Create Date: 2026-07-26

C11 修复（整分支代码审查发现）：
监测系统早期在 monitor schema 下创建了 article_distributions 表（模型
``app.models.article.ArticleDistribution``），作为本地副本。但 M2 跨 schema
查询改造后，所有 GEOFlow 分发数据通过 ``GeoflowArticleDistribution``
（public schema，只读）访问，monitor.article_distributions 沦为孤儿表——

1. 无 service / route 读写它（index_checker / citation_checker / 
   distribution_query 全部使用 GeoflowArticleDistribution）；
2. 无数据迁移逻辑向其写入（init-db.sh / migrate-monitor-data.sh 均未涉及）；
3. 监测系统 schema 反射测试仅校验其存在，不校验数据。

本迁移删除该孤儿表，并删除对应 ORM 模型（见同提交的代码改动）。

安全检查
========
执行前已验证 ``SELECT COUNT(*) FROM monitor.article_distributions = 0``，
public.article_distributions 同样为空（GEOFlow 本地栈未推送数据）。
生产环境部署前需再次确认 monitor.article_distributions 为空。

回滚策略
========
downgrade 重建空表（结构与原模型一致），但已删除的数据不可恢复——
本表为孤儿表，无业务数据，回滚仅恢复结构。
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade():
    # 安全检查：若表非空，中止 upgrade（避免误删业务数据）
    bind = op.get_bind()
    result = bind.execute(
        sa.text("SELECT COUNT(*) FROM monitor.article_distributions")
    )
    count = result.scalar()
    if count and count > 0:
        raise RuntimeError(
            f"monitor.article_distributions 非空（{count} 行），"
            "请先迁移数据再执行本迁移。详见迁移 009 文档。"
        )

    op.drop_table("article_distributions", schema="monitor")


def downgrade():
    # 重建空表，结构对齐原 ArticleDistribution 模型
    op.create_table(
        "article_distributions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("article_id", sa.String(255), nullable=False),
        sa.Column("client_id", sa.String(64), nullable=False, index=True),
        sa.Column("remote_url", sa.String(512), nullable=False, index=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="synced", index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        schema="monitor",
    )
