"""Task 2：监测系统模型基类 schema 测试（TDD RED 阶段先写）。

验证目标：
1. 所有监测系统 ORM 模型的表自动归属 monitor schema；
2. 表名正确未受影响；
3. 已有 __table_args__ 复合唯一约束的模型，约束与 schema dict 共存。
"""
from app.models.citation_result import CitationResult
from app.models.client import Client, ClientSite
from app.models.index_result import IndexHistory, IndexResult
from app.models.system_config import SystemConfig


def test_client_model_has_monitor_schema():
    """验证 Client 模型的表在 monitor schema 下。"""
    assert Client.__table__.schema == "monitor"


def test_client_model_tablename():
    """验证表名正确。"""
    assert Client.__tablename__ == "clients"


# 其余模型同样必须在 monitor schema 下
# 注：ArticleDistribution 已在迁移 009 中删除，不再纳入 schema 校验
ALL_MODELS = [
    Client,
    ClientSite,
    CitationResult,
    IndexResult,
    IndexHistory,
    SystemConfig,
]


def test_all_monitor_models_have_monitor_schema():
    """所有监测系统模型的 __table__.schema 必须为 'monitor'。"""
    for model in ALL_MODELS:
        assert model.__table__.schema == "monitor", (
            f"{model.__name__}.__table__.schema={model.__table__.schema!r}"
            f" 期望 'monitor'"
        )


def test_existing_table_args_preserved_with_schema():
    """已有复合唯一约束的模型，约束与 schema dict 共存于 __table_args__ 元组。"""
    from sqlalchemy import UniqueConstraint

    cases = [
        (ClientSite, ("client_id", "domain"), "client_sites_client_id_domain_key"),
        (CitationResult, ("url", "model", "question"), "citation_results_url_model_question_key"),
        (IndexHistory, ("url", "check_date"), "index_history_url_check_date_key"),
    ]
    for model, cols, name in cases:
        table_args = getattr(model, "__table_args__", None)
        assert isinstance(table_args, tuple), (
            f"{model.__name__}.__table_args__ 应为 tuple（含 schema dict），"
            f"实际 {type(table_args).__name__}"
        )
        # schema dict 必须在元组末尾
        assert table_args[-1] == {"schema": "monitor"}, (
            f"{model.__name__}.__table_args__ 末尾应为 {{'schema': 'monitor'}}，"
            f"实际 {table_args[-1]!r}"
        )
        # 原有 UniqueConstraint 仍在
        uq_found = False
        for item in table_args[:-1]:
            if isinstance(item, UniqueConstraint):
                col_names = tuple(c.name for c in item.columns)
                if tuple(sorted(col_names)) == tuple(sorted(cols)):
                    assert item.name == name, (
                        f"{model.__name__}: 约束名期望 {name}，实际 {item.name}"
                    )
                    uq_found = True
                    break
        assert uq_found, (
            f"{model.__name__}: 未在 __table_args__ 中找到列组合 {cols} 的 UniqueConstraint"
        )
