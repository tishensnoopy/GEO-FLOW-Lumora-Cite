"""Task 3：模型与数据库表结构对应关系测试（TDD RED 阶段先写）。

验证目标（验收标准：与数据库表结构一一对应）：
1. 每个 ORM 模型 ``__tablename__`` 在反射出的 DB 表名集合中；
2. 每个模型列名集合 == DB 反射表列名集合（set 相等）；
3. ``IndexHistory.check_date`` 模型列类型为 ``Date``（控制者裁定 1）；
4. 3 个复合唯一约束在 DB 中存在且名称正确（控制者裁定 2）。

依赖：Task 1 启动的 ``geo-postgres-local`` 容器（localhost:5432），
表结构由 ``deploy/scripts/init-db.sh`` 创建。

Task 4 变更：监测系统表已从 public schema 迁移到 monitor schema。
反射时必须指定 schema='monitor'，否则 inspector 默认只看 public/search_path。
"""
import pytest
from sqlalchemy import create_engine, inspect, Date

from app.core.config import settings
from app.models.article import ArticleDistribution
from app.models.index_result import IndexResult, IndexHistory
from app.models.citation_result import CitationResult
from app.models.client import Client, ClientSite
from app.models.manual_distribution import ManualDistribution
from app.models.admin_audit_log import AdminAuditLog
from app.models.export_task import ExportTask
from app.models.archived_distribution import ArchivedDistribution


# 监测系统表所在的 schema（Task 4 起为 monitor，GEOFlow 表在 public）
MONITOR_SCHEMA = "monitor"

# 用同步 engine 反射 DB schema（async engine 的 inspect 需 run_sync，简化起见用 psycopg2）。
# DATABASE URL 与 conftest.py 一致，基于 POSTGRES_* 连接本地 PG。
SYNC_DATABASE_URL = (
    f"postgresql+psycopg2://{settings.POSTGRES_USER}:{settings.POSTGRES_PASSWORD}"
    f"@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}"
)


@pytest.fixture(scope="module")
def db_inspector():
    sync_engine = create_engine(SYNC_DATABASE_URL)
    inspector = inspect(sync_engine)
    yield inspector
    sync_engine.dispose()


# 所有应映射的 ORM 模型类
MODELS = [
    ArticleDistribution,
    IndexResult,
    IndexHistory,
    CitationResult,
    Client,
    ClientSite,
    ManualDistribution,
    AdminAuditLog,
    ExportTask,
    ArchivedDistribution,
]


def test_tablenames_exist_in_db(db_inspector):
    """每个模型的 __tablename__ 必须存在于 DB 的 monitor schema 中。"""
    db_tables = set(db_inspector.get_table_names(schema=MONITOR_SCHEMA))
    for model in MODELS:
        assert model.__tablename__ in db_tables, (
            f"{model.__name__}.__tablename__={model.__tablename__!r} 不在 DB "
            f"schema={MONITOR_SCHEMA!r} 表集合中"
        )


@pytest.mark.parametrize("model", MODELS)
def test_model_columns_match_db(db_inspector, model):
    """模型列名集合 == DB 表列名集合（set 相等）。"""
    db_cols = {
        c["name"] for c in db_inspector.get_columns(model.__tablename__, schema=MONITOR_SCHEMA)
    }
    model_cols = {c.name for c in model.__table__.columns}
    assert model_cols == db_cols, (
        f"{model.__name__}（表 {model.__tablename__}）列不一致："
        f"仅在模型={model_cols - db_cols}，仅在 DB={db_cols - model_cols}"
    )


def test_index_history_check_date_is_date_type():
    """控制者裁定 1：IndexHistory.check_date 必须是 Date 类型（DB 是 DATE，非 DateTime）。"""
    check_date_col = IndexHistory.__table__.columns["check_date"]
    assert isinstance(check_date_col.type, Date), (
        f"期望 Date，实际 {type(check_date_col.type).__name__}"
    )


# 控制者裁定 2：3 个复合唯一约束（DB 中已存在，模型须用 __table_args__ 声明同名约束）
EXPECTED_COMPOSITE_UNIQUES = [
    ("index_history", ("url", "check_date"), "index_history_url_check_date_key"),
    ("citation_results", ("url", "model", "question"), "citation_results_url_model_question_key"),
    ("client_sites", ("client_id", "domain"), "client_sites_client_id_domain_key"),
]


@pytest.mark.parametrize(
    "table_name,cols,constraint_name",
    EXPECTED_COMPOSITE_UNIQUES,
    ids=[t for t, _, _ in EXPECTED_COMPOSITE_UNIQUES],
)
def test_composite_unique_in_db(db_inspector, table_name, cols, constraint_name):
    """DB 中存在对应的复合唯一约束且名称正确（monitor schema）。"""
    db_uniques = db_inspector.get_unique_constraints(table_name, schema=MONITOR_SCHEMA)
    expected_sorted = tuple(sorted(cols))
    found = False
    for uq in db_uniques:
        if tuple(sorted(uq["column_names"])) == expected_sorted:
            assert uq.get("name") == constraint_name, (
                f"{table_name}: 列组合 {cols} 的约束名不匹配"
                f"（期望 {constraint_name}，实际 {uq.get('name')}）"
            )
            found = True
            break
    assert found, f"{table_name}: 未在 DB 中找到列组合 {cols} 的复合唯一约束"


@pytest.mark.parametrize(
    "model,cols,constraint_name",
    [
        (IndexHistory, ("url", "check_date"), "index_history_url_check_date_key"),
        (CitationResult, ("url", "model", "question"), "citation_results_url_model_question_key"),
        (ClientSite, ("client_id", "domain"), "client_sites_client_id_domain_key"),
    ],
    ids=["IndexHistory", "CitationResult", "ClientSite"],
)
def test_composite_unique_in_model(model, cols, constraint_name):
    """模型 __table_args__ 中声明了同名复合唯一约束（控制者裁定 2 的模型侧落实）。"""
    table_args = getattr(model, "__table_args__", None)
    constraints = table_args if isinstance(table_args, (list, tuple)) else (table_args,)
    # __table_args__ 可能是 (Constraint, ...) 或 (Constraint, dict)
    found = False
    for item in constraints:
        from sqlalchemy import UniqueConstraint
        if isinstance(item, UniqueConstraint):
            col_names = tuple(c.name for c in item.columns)
            if tuple(sorted(col_names)) == tuple(sorted(cols)):
                assert item.name == constraint_name, (
                    f"{model.__name__}: 列组合 {cols} 约束名不匹配"
                    f"（期望 {constraint_name}，实际 {item.name}）"
                )
                found = True
                break
    assert found, f"{model.__name__}: 未在 __table_args__ 找到列组合 {cols} 的 UniqueConstraint"
