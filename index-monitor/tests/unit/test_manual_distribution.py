# index-monitor/tests/unit/test_manual_distribution.py
"""ManualDistribution 模型测试。

验证目标：
1. 模型 __tablename__ = 'manual_distributions'，schema='monitor'
2. 字段集合与设计文档第 4.1 节一致
3. UniqueConstraint(client_id, remote_url) 存在且命名正确
4. DB 反射表结构与模型一致（集成测试，需 db_session fixture）
"""
import pytest
from sqlalchemy import inspect, UniqueConstraint

from app.models.manual_distribution import ManualDistribution


def test_manual_distribution_tablename():
    assert ManualDistribution.__tablename__ == "manual_distributions"


def test_manual_distribution_schema_is_monitor():
    """表必须归属 monitor schema（通过 monitor_table_args）。"""
    table_args = ManualDistribution.__table_args__
    # monitor_table_args 返回 (UniqueConstraint, {"schema": "monitor"})
    schema_dict = table_args[-1] if isinstance(table_args, tuple) else table_args
    assert schema_dict.get("schema") == "monitor"


def test_manual_distribution_required_columns():
    """字段集合与设计文档第 4.1 节一致。"""
    cols = {c.name for c in ManualDistribution.__table__.columns}
    expected = {
        "id", "client_id", "remote_url", "status", "note",
        "created_by_admin_id", "created_at", "updated_at",
    }
    assert cols == expected, f"缺失字段：{expected - cols}，多余字段：{cols - expected}"


def test_manual_distribution_unique_constraint():
    """UniqueConstraint(client_id, remote_url) 必须存在且命名为 uq_manual_client_url。"""
    table_args = ManualDistribution.__table_args__
    constraints = [a for a in table_args if isinstance(a, UniqueConstraint)] if isinstance(table_args, tuple) else []
    assert len(constraints) == 1, f"期望 1 个 UniqueConstraint，实际 {len(constraints)}"
    uc = constraints[0]
    col_names = tuple(sorted(c.name for c in uc.columns))
    assert col_names == ("client_id", "remote_url")
    assert uc.name == "uq_manual_client_url"


@pytest.mark.asyncio
async def test_manual_distribution_table_exists_in_db(db_session):
    """DB 中 monitor.manual_distributions 表存在且列匹配（集成测试）。

    连接 URL 从 settings 动态构造（与 conftest.py 的 db_session fixture 一致），
    避免硬编码数据库名 / 密码 / 主机导致跨环境失败。
    """
    from app.core.config import settings
    from sqlalchemy import create_engine

    sync_url = (
        f"postgresql+psycopg2://{settings.POSTGRES_USER}:{settings.POSTGRES_PASSWORD}"
        f"@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}"
    )
    engine = create_engine(sync_url)
    try:
        inspector = inspect(engine)
        db_tables = set(inspector.get_table_names(schema="monitor"))
        assert "manual_distributions" in db_tables, (
            "monitor.manual_distributions 表不存在，请先运行 alembic upgrade head"
        )
        db_cols = {c["name"] for c in inspector.get_columns("manual_distributions", schema="monitor")}
        model_cols = {c.name for c in ManualDistribution.__table__.columns}
        assert db_cols == model_cols, f"DB 列={db_cols}，模型列={model_cols}"
    finally:
        engine.dispose()
