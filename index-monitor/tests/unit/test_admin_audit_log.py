# index-monitor/tests/unit/test_admin_audit_log.py
"""AdminAuditLog 模型测试。

验证目标：
1. __tablename__ = 'admin_audit_logs'，schema='monitor'
2. 字段集合与设计文档第 4.1 节一致
3. DB 反射表结构与模型一致（集成测试，需 db_session fixture）

连接 URL 从 settings 动态构造（与 conftest.py 的 db_session fixture 一致），
避免硬编码数据库名 / 密码 / 主机导致跨环境失败。
"""
import pytest
from sqlalchemy import inspect

from app.models.admin_audit_log import AdminAuditLog


def test_audit_log_tablename():
    assert AdminAuditLog.__tablename__ == "admin_audit_logs"


def test_audit_log_schema_is_monitor():
    table_args = AdminAuditLog.__table_args__
    schema_dict = table_args if isinstance(table_args, dict) else table_args[-1]
    assert schema_dict.get("schema") == "monitor"


def test_audit_log_required_columns():
    cols = {c.name for c in AdminAuditLog.__table__.columns}
    expected = {
        "id", "admin_user_id", "admin_name", "action",
        "target_type", "target_id", "detail",
        "ip_address", "user_agent", "created_at",
    }
    assert cols == expected, f"缺失：{expected - cols}，多余：{cols - expected}"


@pytest.mark.asyncio
async def test_audit_log_table_exists_in_db(db_session):
    """DB 中 monitor.admin_audit_logs 表存在且列匹配（集成测试）。

    连接 URL 从 settings 动态构造（与 conftest.py 的 db_session fixture 一致），
    避免硬编码数据库名 / 密码 / 主机导致跨环境失败。
    用 try/finally 确保 engine.dispose() 一定执行（即使断言失败也要关闭 engine）。
    """
    from sqlalchemy import create_engine
    from app.core.config import settings

    sync_url = (
        f"postgresql+psycopg2://{settings.POSTGRES_USER}:{settings.POSTGRES_PASSWORD}"
        f"@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}"
    )
    engine = create_engine(sync_url)
    try:
        inspector = inspect(engine)
        db_tables = set(inspector.get_table_names(schema="monitor"))
        assert "admin_audit_logs" in db_tables, (
            "monitor.admin_audit_logs 表不存在，请先运行 alembic upgrade head"
        )
        db_cols = {c["name"] for c in inspector.get_columns("admin_audit_logs", schema="monitor")}
        model_cols = {c.name for c in AdminAuditLog.__table__.columns}
        assert db_cols == model_cols, f"DB 列={db_cols}，模型列={model_cols}"
    finally:
        engine.dispose()
