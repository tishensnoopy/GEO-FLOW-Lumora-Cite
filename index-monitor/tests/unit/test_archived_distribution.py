# index-monitor/tests/unit/test_archived_distribution.py
"""ArchivedDistribution 模型测试。

GEOFlow 文章删除后，监测系统跨 schema JOIN 查不到，历史检测结果丢失。
本表保留删除时的文章快照。设计文档第 21.4 节。

验证目标：
1. __tablename__ = 'archived_distributions'，schema='monitor'
2. 字段集合与设计文档第 21.4 节一致（14 个字段）
3. 关键列类型正确（id 是 UUID；geoflow_article_id 是 Integer 不是 UUID；
   content_keywords 是 JSON 不是 Text；content_excerpt/body/meta_description 是 Text；
   published_at/archived_at 是 DateTime(timezone=True)）
4. client_id 和 remote_url 两列有索引
5. archived_reason 默认 'geoflow_deleted'
6. DB 反射表结构与模型一致（含类型与索引，集成测试，需 db_session fixture）

连接 URL 从 settings 动态构造（与 conftest.py 的 db_session fixture 一致），
避免硬编码数据库名 / 密码 / 主机导致跨环境失败。
"""
import pytest
from sqlalchemy import inspect
from sqlalchemy.dialects.postgresql import UUID, JSON
from sqlalchemy import String, DateTime, Text, Integer

from app.models.archived_distribution import ArchivedDistribution


def test_archived_distribution_tablename():
    assert ArchivedDistribution.__tablename__ == "archived_distributions"


def test_archived_distribution_schema_is_monitor():
    table_args = ArchivedDistribution.__table_args__
    schema_dict = table_args if isinstance(table_args, dict) else table_args[-1]
    assert schema_dict.get("schema") == "monitor"


def test_archived_distribution_required_columns():
    cols = {c.name for c in ArchivedDistribution.__table__.columns}
    expected = {
        "id", "client_id", "remote_url", "geoflow_article_id",
        "content_title", "content_slug", "content_excerpt", "content_body",
        "content_keywords", "meta_description", "original_keyword", "published_at",
        "archived_at", "archived_reason",
    }
    assert cols == expected, f"缺失：{expected - cols}，多余：{cols - expected}"


def test_archived_distribution_column_types():
    """关键列类型必须与设计文档第 21.4 节一致。

    易错点：
    - geoflow_article_id 是 Integer（不是 UUID，因为是跨 schema 关联 GEOFlow
      articles.id 整型主键，不是本表自己的 UUID 主键）
    - content_keywords 是 JSON（不是 Text，需要结构化查询）
    - content_excerpt / content_body / meta_description 是 Text（长文本）
    - published_at / archived_at 是 DateTime(timezone=True)
    """
    columns = ArchivedDistribution.__table__.columns

    # id 是 UUID
    assert isinstance(columns["id"].type, UUID), (
        f"id 类型应为 UUID，实际 {type(columns['id'].type).__name__}"
    )

    # geoflow_article_id 是 Integer，不是 UUID
    assert isinstance(columns["geoflow_article_id"].type, Integer), (
        f"geoflow_article_id 类型应为 Integer，实际 {type(columns['geoflow_article_id'].type).__name__}"
    )
    assert not isinstance(columns["geoflow_article_id"].type, UUID), (
        "geoflow_article_id 不应是 UUID（它是跨 schema 关联 GEOFlow articles 整型 id）"
    )

    # content_keywords 是 JSON，不是 Text
    assert isinstance(columns["content_keywords"].type, JSON), (
        f"content_keywords 类型应为 JSON，实际 {type(columns['content_keywords'].type).__name__}"
    )
    assert not isinstance(columns["content_keywords"].type, Text), (
        "content_keywords 不应是 Text（需要结构化 JSON 查询）"
    )

    # 长文本字段是 Text
    for col_name in ("content_excerpt", "content_body", "meta_description"):
        assert isinstance(columns[col_name].type, Text), (
            f"{col_name} 类型应为 Text，实际 {type(columns[col_name].type).__name__}"
        )

    # 时间字段是 DateTime 带 timezone
    for col_name in ("published_at", "archived_at"):
        assert isinstance(columns[col_name].type, DateTime), (
            f"{col_name} 类型应为 DateTime，实际 {type(columns[col_name].type).__name__}"
        )
        assert columns[col_name].type.timezone is True, (
            f"{col_name} 应带 timezone=True"
        )


def test_archived_distribution_indexes():
    """client_id 和 remote_url 两列必须有索引（高频过滤字段）。"""
    indexed_cols = {
        idx.columns[0].name
        for idx in ArchivedDistribution.__table__.indexes
        if len(idx.columns) == 1
    }
    assert "client_id" in indexed_cols, "client_id 应有单列索引"
    assert "remote_url" in indexed_cols, "remote_url 应有单列索引"


def test_archived_distribution_archived_reason_default():
    """archived_reason 默认 'geoflow_deleted'。"""
    reason_col = ArchivedDistribution.__table__.columns["archived_reason"]
    assert reason_col.default.arg == "geoflow_deleted"


@pytest.mark.asyncio
async def test_archived_distribution_table_exists_in_db(db_session):
    """DB 中 monitor.archived_distributions 表存在且结构与模型一致（集成测试）。

    连接 URL 从 settings 动态构造（与 conftest.py 的 db_session fixture 一致），
    避免硬编码数据库名 / 密码 / 主机导致跨环境失败。
    用 try/finally 确保 engine.dispose() 一定执行（即使断言失败也要关闭 engine）。

    除了列名集合，还验证 DB 反射的列类型与模型一致——重点验证：
    - content_keywords 在 DB 中是 JSON 类型（不是 TEXT），防止迁移误用 Text
    - geoflow_article_id 在 DB 中是 integer 类型（不是 uuid），防止迁移误用 UUID
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
        assert "archived_distributions" in db_tables, (
            "monitor.archived_distributions 表不存在，请先运行 alembic upgrade head"
        )

        # 列名集合匹配
        db_cols = {c["name"]: c for c in inspector.get_columns("archived_distributions", schema="monitor")}
        model_cols = {c.name for c in ArchivedDistribution.__table__.columns}
        assert set(db_cols.keys()) == model_cols, (
            f"DB 列={set(db_cols.keys())}，模型列={model_cols}"
        )

        # content_keywords 在 DB 中是 JSON，不是 TEXT
        keywords_type = str(db_cols["content_keywords"]["type"]).upper()
        assert "JSON" in keywords_type, (
            f"DB 中 content_keywords 类型应包含 JSON，实际 {keywords_type}"
        )
        assert "TEXT" not in keywords_type, (
            f"DB 中 content_keywords 不应是 TEXT 类型，实际 {keywords_type}"
        )

        # geoflow_article_id 在 DB 中是 integer，不是 uuid
        article_id_type = str(db_cols["geoflow_article_id"]["type"]).upper()
        assert "INTEGER" in article_id_type, (
            f"DB 中 geoflow_article_id 类型应包含 INTEGER，实际 {article_id_type}"
        )
        assert "UUID" not in article_id_type, (
            f"DB 中 geoflow_article_id 不应是 UUID 类型，实际 {article_id_type}"
        )

        # 索引验证：client_id 和 remote_url 两列在 DB 中有索引
        db_indexes = inspector.get_indexes("archived_distributions", schema="monitor")
        db_indexed_cols = {
            idx["column_names"][0]
            for idx in db_indexes
            if idx.get("column_names") and len(idx["column_names"]) == 1
        }
        assert "client_id" in db_indexed_cols, (
            f"DB 中 client_id 应有索引，实际索引列={db_indexed_cols}"
        )
        assert "remote_url" in db_indexed_cols, (
            f"DB 中 remote_url 应有索引，实际索引列={db_indexed_cols}"
        )
    finally:
        engine.dispose()
