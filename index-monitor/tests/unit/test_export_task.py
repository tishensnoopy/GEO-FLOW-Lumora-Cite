# index-monitor/tests/unit/test_export_task.py
"""ExportTask 模型测试。

验证目标：
1. __tablename__ = 'export_tasks'，schema='monitor'
2. 字段集合与设计文档第 12.6 节一致
3. 关键列类型正确（date_from/date_to 是 Date 不是 DateTime；id 是 UUID；
   file_size 是 Integer；error_message 是 Text）
4. DB 反射表结构与模型一致（含类型与索引，集成测试，需 db_session fixture）
5. status 默认 'pending'

连接 URL 从 settings 动态构造（与 conftest.py 的 db_session fixture 一致），
避免硬编码数据库名 / 密码 / 主机导致跨环境失败。
"""
import pytest
from sqlalchemy import inspect
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy import String, Date, DateTime, Text, Integer

from app.models.export_task import ExportTask


def test_export_task_tablename():
    assert ExportTask.__tablename__ == "export_tasks"


def test_export_task_schema_is_monitor():
    table_args = ExportTask.__table_args__
    schema_dict = table_args if isinstance(table_args, dict) else table_args[-1]
    assert schema_dict.get("schema") == "monitor"


def test_export_task_required_columns():
    cols = {c.name for c in ExportTask.__table__.columns}
    expected = {
        "id", "client_id", "requested_by", "requested_by_role",
        "export_type", "date_from", "date_to", "status",
        "file_path", "file_size", "error_message",
        "created_at", "completed_at",
    }
    assert cols == expected, f"缺失：{expected - cols}，多余：{cols - expected}"


def test_export_task_column_types():
    """关键列类型必须与设计文档第 12.6 节一致。

    重点：date_from / date_to 是 Date（不是 DateTime）—— 导出按日聚合，
    不需要时分秒；id 是 UUID；file_size 是 Integer；error_message 是 Text。
    """
    columns = ExportTask.__table__.columns
    assert isinstance(columns["id"].type, UUID), (
        f"id 类型应为 UUID，实际 {type(columns['id'].type).__name__}"
    )
    assert isinstance(columns["date_from"].type, Date), (
        f"date_from 类型应为 Date，实际 {type(columns['date_from'].type).__name__}"
    )
    assert not isinstance(columns["date_from"].type, DateTime), (
        "date_from 不应是 DateTime"
    )
    assert isinstance(columns["date_to"].type, Date), (
        f"date_to 类型应为 Date，实际 {type(columns['date_to'].type).__name__}"
    )
    assert not isinstance(columns["date_to"].type, DateTime), (
        "date_to 不应是 DateTime"
    )
    assert isinstance(columns["file_size"].type, Integer), (
        f"file_size 类型应为 Integer，实际 {type(columns['file_size'].type).__name__}"
    )
    assert isinstance(columns["error_message"].type, Text), (
        f"error_message 类型应为 Text，实际 {type(columns['error_message'].type).__name__}"
    )


def test_export_task_indexes():
    """client_id 和 status 两列必须有索引（高频过滤字段）。"""
    # 模型层检查：Column(index=True) 会在 Table.indexes 中生成 Index 对象
    indexed_cols = {
        idx.columns[0].name
        for idx in ExportTask.__table__.indexes
        if len(idx.columns) == 1
    }
    assert "client_id" in indexed_cols, "client_id 应有单列索引"
    assert "status" in indexed_cols, "status 应有单列索引"


def test_export_task_status_default():
    """status 默认 'pending'。"""
    status_col = ExportTask.__table__.columns["status"]
    assert status_col.default.arg == "pending"


@pytest.mark.asyncio
async def test_export_task_table_exists_in_db(db_session):
    """DB 中 monitor.export_tasks 表存在且结构与模型一致（集成测试）。

    连接 URL 从 settings 动态构造（与 conftest.py 的 db_session fixture 一致），
    避免硬编码数据库名 / 密码 / 主机导致跨环境失败。
    用 try/finally 确保 engine.dispose() 一定执行（即使断言失败也要关闭 engine）。

    除了列名集合，还验证 DB 反射的列类型与模型一致——至少验证
    date_from / date_to 在 DB 中是 DATE 类型（不是 TIMESTAMP），防止迁移
    误用 DateTime 导致类型漂移。
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
        assert "export_tasks" in db_tables, (
            "monitor.export_tasks 表不存在，请先运行 alembic upgrade head"
        )

        # 列名集合匹配
        db_cols = {c["name"]: c for c in inspector.get_columns("export_tasks", schema="monitor")}
        model_cols = {c.name for c in ExportTask.__table__.columns}
        assert set(db_cols.keys()) == model_cols, (
            f"DB 列={set(db_cols.keys())}，模型列={model_cols}"
        )

        # 关键列类型匹配：date_from / date_to 必须是 DATE，不是 TIMESTAMP
        # PG inspector 返回的 type 是字符串如 'DATE' / 'TIMESTAMP WITH TIME ZONE'
        for col_name in ("date_from", "date_to"):
            col_type_str = str(db_cols[col_name]["type"]).upper()
            assert "DATE" in col_type_str, (
                f"DB 中 {col_name} 类型应包含 DATE，实际 {col_type_str}"
            )
            assert "TIMESTAMP" not in col_type_str, (
                f"DB 中 {col_name} 不应是 TIMESTAMP 类型，实际 {col_type_str}"
            )

        # 索引验证：client_id 和 status 两列在 DB 中有索引
        db_indexes = inspector.get_indexes("export_tasks", schema="monitor")
        db_indexed_cols = {
            idx["column_names"][0]
            for idx in db_indexes
            if idx.get("column_names") and len(idx["column_names"]) == 1
        }
        assert "client_id" in db_indexed_cols, (
            f"DB 中 client_id 应有索引，实际索引列={db_indexed_cols}"
        )
        assert "status" in db_indexed_cols, (
            f"DB 中 status 应有索引，实际索引列={db_indexed_cols}"
        )
    finally:
        engine.dispose()
