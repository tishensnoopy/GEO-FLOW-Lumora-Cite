"""engine.run_citation_check 的 client_questions 直通模式测试。"""
from unittest.mock import MagicMock, patch
from app.services.citation_check.engine import run_citation_check


def test_client_questions_skip_selection():
    """client_questions 非 None 时跳过 select_best_questions，直通全部。"""
    client_questions = ["问题1", "问题2", "问题3"]

    fake_answer = MagicMock()
    fake_answer.sources = []
    fake_answer.model = "测试模型"
    fake_answer.model_id = "test-model"
    fake_answer.search_used = False
    fake_answer.error = None
    fake_answer.text = "测试回答"

    fake_adapter = MagicMock()
    fake_adapter.name = "测试模型"
    fake_adapter.provider_id = "test"
    fake_adapter.model_id = "test-model"
    fake_adapter.capability = "verified_citations"

    with patch("app.services.citation_check.engine.ask_with_retry", return_value=fake_answer):
        result = run_citation_check(
            target_urls=["https://example.com/test"],
            candidates=[],  # 空 candidates，正常会被 select_best_questions 过滤
            adapters=[fake_adapter],
            client_questions=client_questions,
            forbidden_terms=["https://example.com/test"],
        )

    # 3 个问题 × 1 个模型 = 3 个结果
    assert len(result["results"]) == 3
    questions_in_results = {r["question"] for r in result["results"]}
    assert questions_in_results == {"问题1", "问题2", "问题3"}


def test_client_questions_none_uses_original_logic():
    """client_questions=None 时走原逻辑（select_best_questions 评分筛选）。"""
    from app.services.citation_check.questions import QuestionCandidate

    candidate = QuestionCandidate(
        question="测试问题",
        content_support=0.8,
        natural_intent=0.8,
        citation_need=0.8,
        distinctiveness=0.8,
        freshness=0.8,
        selection_reason="测试",
    )

    fake_answer = MagicMock()
    fake_answer.sources = []
    fake_answer.model = "测试模型"
    fake_answer.model_id = "test-model"
    fake_answer.search_used = False
    fake_answer.error = None
    fake_answer.text = "测试回答"

    fake_adapter = MagicMock()
    fake_adapter.name = "测试模型"
    fake_adapter.provider_id = "test"
    fake_adapter.model_id = "test-model"
    fake_adapter.capability = "verified_citations"

    with patch("app.services.citation_check.engine.ask_with_retry", return_value=fake_answer):
        result = run_citation_check(
            target_urls=["https://example.com/test"],
            candidates=[candidate],
            adapters=[fake_adapter],
            question_count=1,
            forbidden_terms=["https://example.com/test"],
        )

    assert len(result["results"]) == 1
    assert result["results"][0]["question"] == "测试问题"
