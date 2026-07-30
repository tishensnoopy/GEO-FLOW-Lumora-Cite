# index-monitor/tests/unit/test_citation_check_log.py
"""CitationCheckLog 模型测试（阶段 1 - ④a）。

验证目标：
1. __tablename__ = 'citation_check_logs'，schema='monitor'
2. 字段集合：id / task_id / url / stage / status / model / detail / duration_ms / created_at
3. 关键列类型：id UUID、detail JSONB、duration_ms Integer、created_at 带 timezone
4. 索引：task_id / url / created_at（单列）+ (task_id, created_at) 组合
5. DB 反射表结构匹配（集成测试，需 psycopg2 + 真实 PG）

本表用于阶段 2-④b 的 progress 回调持久化采信检测过程日志，
供 ScanPanel 终端面板按 task_id 拉取实时进度。
"""
import pytest
from sqlalchemy import inspect

from app.models.citation_check_log import CitationCheckLog


def test_tablename():
    assert CitationCheckLog.__tablename__ == "citation_check_logs"


def test_schema_is_monitor():
    table_args = CitationCheckLog.__table_args__
    schema_dict = table_args if isinstance(table_args, dict) else table_args[-1]
    assert schema_dict.get("schema") == "monitor"


def test_required_columns():
    cols = {c.name for c in CitationCheckLog.__table__.columns}
    expected = {
        "id", "task_id", "url", "stage", "status",
        "model", "detail", "duration_ms", "created_at",
    }
    assert cols == expected, f"缺失：{expected - cols}，多余：{cols - expected}"


def test_column_types():
    """验证关键列类型。"""
    from sqlalchemy import String, Integer, DateTime
    from sqlalchemy.dialects.postgresql import UUID as PGUUID, JSONB
    columns = CitationCheckLog.__table__.columns

    assert isinstance(columns["id"].type, PGUUID), "id 期望 UUID"
    assert isinstance(columns["task_id"].type, String), "task_id 期望 String"
    assert isinstance(columns["url"].type, String), "url 期望 String"
    assert isinstance(columns["stage"].type, String), "stage 期望 String"
    assert isinstance(columns["status"].type, String), "status 期望 String"
    assert isinstance(columns["model"].type, String), "model 期望 String"
    assert isinstance(columns["detail"].type, JSONB), f"detail 期望 JSONB，实际 {type(columns['detail'].type).__name__}"
    assert isinstance(columns["duration_ms"].type, Integer), "duration_ms 期望 Integer"
    assert isinstance(columns["created_at"].type, DateTime), "created_at 期望 DateTime"
    assert columns["created_at"].type.timezone is True, "created_at 必须带 timezone=True"


def test_task_id_nullable():
    """task_id 可空：定时任务无 task_id，手动触发才有。"""
    assert CitationCheckLog.__table__.columns["task_id"].nullable is True


def test_model_nullable():
    """model 可空：非模型相关阶段（抓取/目的推断）无 model。"""
    assert CitationCheckLog.__table__.columns["model"].nullable is True


def test_indexes():
    """验证单列索引 task_id / url / created_at 存在。"""
    table = CitationCheckLog.__table__
    indexed_cols = set()
    for idx in table.indexes:
        for col in idx.columns:
            indexed_cols.add(col.name)
    assert "task_id" in indexed_cols, "task_id 应有索引"
    assert "url" in indexed_cols, "url 应有索引"
    assert "created_at" in indexed_cols, "created_at 应有索引"


def test_task_id_created_at_composite_index():
    """验证 (task_id, created_at) 组合索引存在（按任务拉取时序日志）。"""
    table = CitationCheckLog.__table__
    composite_found = False
    for idx in table.indexes:
        col_names = [c.name for c in idx.columns]
        if col_names == ["task_id", "created_at"]:
            composite_found = True
            break
    assert composite_found, "应存在 (task_id, created_at) 组合索引"


@pytest.mark.asyncio
async def test_table_exists_in_db(db_session):
    """DB 中 monitor.citation_check_logs 表存在且列匹配（集成测试）。

    需先运行 alembic upgrade head（012 迁移建表）。
    psycopg2 缺失时会 error，属环境问题，非模型问题。
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
        assert "citation_check_logs" in db_tables, (
            "monitor.citation_check_logs 表不存在，请先运行 alembic upgrade head"
        )
        db_cols = {c["name"] for c in inspector.get_columns("citation_check_logs", schema="monitor")}
        model_cols = {c.name for c in CitationCheckLog.__table__.columns}
        assert db_cols == model_cols, f"DB 列={db_cols}，模型列={model_cols}"
    finally:
        engine.dispose()
