"""extend clients and client_sites tables

Revision ID: 007
Revises: 006
Create Date: 2026-07-25

扩展 monitor.clients：
- contact_name / contact_email（UNIQUE）/ contact_phone（设计文档第 6.1 节）
- agreed_terms_at / agreed_privacy_at（设计文档第 21.6 节合规）
- last_login_at（客户最后登录时间）

扩展 monitor.client_sites：
- has_wordpress 字段（设计文档第 6.2 节）
- domain UNIQUE 约束（client_sites_domain_unique_key）
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 扩展 clients 表
    op.add_column("clients", sa.Column("contact_name", sa.String(128), nullable=True), schema="monitor")
    op.add_column("clients", sa.Column("contact_email", sa.String(255), nullable=True), schema="monitor")
    op.add_column("clients", sa.Column("contact_phone", sa.String(32), nullable=True), schema="monitor")
    op.add_column("clients", sa.Column("agreed_terms_at", sa.DateTime(timezone=True), nullable=True), schema="monitor")
    op.add_column("clients", sa.Column("agreed_privacy_at", sa.DateTime(timezone=True), nullable=True), schema="monitor")
    op.add_column("clients", sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True), schema="monitor")
    op.create_unique_constraint("clients_contact_email_key", "clients", ["contact_email"], schema="monitor")

    # 扩展 client_sites 表
    op.add_column("client_sites", sa.Column("has_wordpress", sa.Boolean, server_default="false"), schema="monitor")
    op.create_unique_constraint("client_sites_domain_unique_key", "client_sites", ["domain"], schema="monitor")


def downgrade() -> None:
    op.drop_constraint("client_sites_domain_unique_key", "client_sites", schema="monitor")
    op.drop_column("client_sites", "has_wordpress", schema="monitor")

    op.drop_constraint("clients_contact_email_key", "clients", schema="monitor")
    op.drop_column("clients", "last_login_at", schema="monitor")
    op.drop_column("clients", "agreed_privacy_at", schema="monitor")
    op.drop_column("clients", "agreed_terms_at", schema="monitor")
    op.drop_column("clients", "contact_phone", schema="monitor")
    op.drop_column("clients", "contact_email", schema="monitor")
    op.drop_column("clients", "contact_name", schema="monitor")
