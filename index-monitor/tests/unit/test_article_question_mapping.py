"""ArticleQuestionMapping 模型测试。"""
import pytest
from app.models.article_question_mapping import ArticleQuestionMapping


def test_model_fields():
    """模型字段完整性检查。"""
    cols = {c.name for c in ArticleQuestionMapping.__table__.columns}
    assert cols == {
        "id", "distribution_id", "client_question_id",
        "relevance_score", "inferred_at", "created_at",
    }


def test_model_schema():
    """表属于 monitor schema。"""
    assert ArticleQuestionMapping.__table__.schema == "monitor"


def test_unique_constraint():
    """(distribution_id, client_question_id) 唯一约束存在。"""
    constraints = ArticleQuestionMapping.__table__.constraints
    uq_names = [c.name for c in constraints if hasattr(c, "name") and c.name]
    assert any("uq_article_question" in name for name in uq_names)
