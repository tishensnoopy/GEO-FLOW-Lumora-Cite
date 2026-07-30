"""Client 表扩展字段测试（Task 5）。

验证目标（设计文档第 6.1 节 + 第 6.2 节 + 第 21.6 节）：
1. Client 模型有 contact_name/contact_email/contact_phone 字段
2. Client 模型有 agreed_terms_at/agreed_privacy_at 字段
3. Client 模型有 last_login_at 字段
4. contact_email 在模型层 unique=True
5. 各扩展字段类型正确（String / DateTime(timezone=True)）
6. ClientSite 模型有 has_wordpress Boolean 字段
7. ClientSite 模型声明了 domain 单列 UNIQUE 约束（client_sites_domain_unique_key）
8. DB 反射表结构与模型一致（列存在 + contact_email UNIQUE + domain UNIQUE）

裁定 3：DB URL 用 settings.POSTGRES_* 动态构造，try/finally 确保 engine.dispose()。
裁定 4：在简报基线测试上强化——增加类型断言、ClientSite 字段断言、
        模型层 UniqueConstraint 断言、DB 层 UNIQUE 约束断言。
"""
import pytest
from sqlalchemy import Boolean, DateTime, String, create_engine, inspect

from app.core.config import settings
from app.models.client import Client, ClientSite


# ----------------------------------------------------------------------
# 模型层字段存在性
# ----------------------------------------------------------------------

def test_client_has_contact_fields():
    cols = {c.name for c in Client.__table__.columns}
    assert "contact_name" in cols, "Client 缺 contact_name 字段"
    assert "contact_email" in cols, "Client 缺 contact_email 字段"
    assert "contact_phone" in cols, "Client 缺 contact_phone 字段"


def test_client_has_agreed_fields():
    cols = {c.name for c in Client.__table__.columns}
    assert "agreed_terms_at" in cols, "Client 缺 agreed_terms_at 字段"
    assert "agreed_privacy_at" in cols, "Client 缺 agreed_privacy_at 字段"


def test_client_has_last_login_at():
    cols = {c.name for c in Client.__table__.columns}
    assert "last_login_at" in cols, "Client 缺 last_login_at 字段"


def test_client_contact_email_is_unique():
    """contact_email 必须 UNIQUE（设计文档第 6.1 节）。"""
    email_col = Client.__table__.columns["contact_email"]
    assert email_col.unique is True, "contact_email 必须有 UNIQUE 约束"


# ----------------------------------------------------------------------
# 裁定 4 强化：模型层字段类型
# ----------------------------------------------------------------------

def test_client_extended_column_types():
    """扩展字段类型严格匹配设计文档。"""
    contact_name = Client.__table__.columns["contact_name"]
    contact_email = Client.__table__.columns["contact_email"]
    contact_phone = Client.__table__.columns["contact_phone"]
    agreed_terms_at = Client.__table__.columns["agreed_terms_at"]
    agreed_privacy_at = Client.__table__.columns["agreed_privacy_at"]
    last_login_at = Client.__table__.columns["last_login_at"]

    assert isinstance(contact_name.type, String), (
        f"contact_name 期望 String，实际 {type(contact_name.type).__name__}"
    )
    assert isinstance(contact_email.type, String), (
        f"contact_email 期望 String，实际 {type(contact_email.type).__name__}"
    )
    assert isinstance(contact_phone.type, String), (
        f"contact_phone 期望 String，实际 {type(contact_phone.type).__name__}"
    )
    # 三个时间戳必须是 DateTime 且 timezone=True（合规留痕需要带时区）
    for col in (agreed_terms_at, agreed_privacy_at, last_login_at):
        assert isinstance(col.type, DateTime), (
            f"{col.name} 期望 DateTime，实际 {type(col.type).__name__}"
        )
        assert col.type.timezone is True, (
            f"{col.name} 必须 timezone=True（合规留痕需带时区）"
        )


# ----------------------------------------------------------------------
# 裁定 4 强化：ClientSite 模型层
# ----------------------------------------------------------------------

def test_client_site_has_wordpress_field():
    """ClientSite 有 has_wordpress 字段且类型是 Boolean（设计文档第 6.2 节）。"""
    cols = {c.name for c in ClientSite.__table__.columns}
    assert "has_wordpress" in cols, "ClientSite 缺 has_wordpress 字段"
    has_wp_col = ClientSite.__table__.columns["has_wordpress"]
    assert isinstance(has_wp_col.type, Boolean), (
        f"has_wordpress 期望 Boolean，实际 {type(has_wp_col.type).__name__}"
    )


def test_client_site_domain_unique_in_model():
    """ClientSite 模型声明了 domain 单列 UNIQUE 约束（client_sites_domain_unique_key）。"""
    from sqlalchemy import UniqueConstraint

    table_args = getattr(ClientSite, "__table_args__", None)
    constraints = table_args if isinstance(table_args, (list, tuple)) else (table_args,)
    found = False
    for item in constraints:
        if isinstance(item, UniqueConstraint):
            col_names = tuple(c.name for c in item.columns)
            if col_names == ("domain",):
                assert item.name == "client_sites_domain_unique_key", (
                    f"domain 单列 UNIQUE 约束名不匹配"
                    f"（期望 client_sites_domain_unique_key，实际 {item.name}）"
                )
                found = True
                break
    assert found, (
        "ClientSite __table_args__ 未声明 UniqueConstraint('domain', "
        "name='client_sites_domain_unique_key')"
    )


# ----------------------------------------------------------------------
# DB 层反射
# ----------------------------------------------------------------------

def test_client_extended_columns_in_db():
    """DB monitor.clients 表有所有扩展列 + contact_email UNIQUE 约束 +
    DB monitor.client_sites 表有 domain 单列 UNIQUE 约束。

    裁定 3：用 settings.POSTGRES_* 动态构造 URL，try/finally dispose。
    """
    sync_url = (
        f"postgresql+psycopg2://{settings.POSTGRES_USER}:{settings.POSTGRES_PASSWORD}"
        f"@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}"
    )
    engine = create_engine(sync_url)
    try:
        inspector = inspect(engine)

        # 1) clients 扩展列全部存在于 DB
        db_client_cols = {
            c["name"] for c in inspector.get_columns("clients", schema="monitor")
        }
        for col in (
            "contact_name",
            "contact_email",
            "contact_phone",
            "agreed_terms_at",
            "agreed_privacy_at",
            "last_login_at",
        ):
            assert col in db_client_cols, f"DB monitor.clients 缺 {col}"

        # 2) clients.contact_email 在 DB 层有单列 UNIQUE 约束
        client_uniques = inspector.get_unique_constraints("clients", schema="monitor")
        contact_email_unique = [
            uq for uq in client_uniques
            if uq.get("column_names") == ["contact_email"]
        ]
        assert contact_email_unique, (
            "DB monitor.clients 未找到 contact_email 单列 UNIQUE 约束"
        )

        # 3) client_sites 有 domain 单列 UNIQUE 约束 client_sites_domain_unique_key
        site_uniques = inspector.get_unique_constraints("client_sites", schema="monitor")
        domain_unique = [
            uq for uq in site_uniques
            if uq.get("column_names") == ["domain"]
        ]
        assert domain_unique, (
            "DB monitor.client_sites 未找到 domain 单列 UNIQUE 约束"
        )
        assert domain_unique[0].get("name") == "client_sites_domain_unique_key", (
            f"domain UNIQUE 约束名不匹配"
            f"（期望 client_sites_domain_unique_key，"
            f"实际 {domain_unique[0].get('name')!r}）"
        )

        # 4) client_sites.has_wordpress 列存在于 DB
        db_site_cols = {
            c["name"] for c in inspector.get_columns("client_sites", schema="monitor")
        }
        assert "has_wordpress" in db_site_cols, "DB monitor.client_sites 缺 has_wordpress"
    finally:
        engine.dispose()
