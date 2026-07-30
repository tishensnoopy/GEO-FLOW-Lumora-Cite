# index-monitor/tests/unit/test_questions_forbidden.py
"""forbidden_terms 行为测试（阶段 1 - ⑥a）。

验证 citation_checker 传入 forbidden_terms=[*target_urls]（只禁 URL，允许标题词）
后，select_best_questions 的过滤行为：
- 含目标 URL 的候选问题被过滤（避免问题直接泄露答案链接）
- 含标题词的候选问题不被过滤（允许问题提及文章主题词，更贴近真实用户提问）
"""
import pytest

from app.services.citation_check.questions import QuestionCandidate, select_best_questions


def _candidate(question: str, score_boost: float = 0.8) -> QuestionCandidate:
    """构造一个各维度均合格、分数可调的候选问题。"""
    return QuestionCandidate(
        question=question,
        content_support=score_boost,
        natural_intent=score_boost,
        citation_need=score_boost,
        distinctiveness=score_boost,
        freshness=score_boost,
    )


def test_question_containing_target_url_is_filtered():
    """含目标 URL 的候选问题应被过滤。"""
    target_url = "https://example.com/article/geo-strategy"
    candidates = [
        _candidate(f"请访问 {target_url} 了解详情"),
        _candidate("什么是 GEO 策略？"),
    ]
    selected = select_best_questions(candidates, count=2, forbidden_terms=[target_url])
    questions = [c.question for c in selected]
    assert all(target_url not in q for q in questions)
    assert "什么是 GEO 策略？" in questions


def test_question_containing_title_words_is_not_filtered():
    """含标题词的候选问题不应被过滤（标题不在 forbidden_terms 时）。

    场景：文章标题《GEO 策略白皮书》，问题" GEO 策略有哪些核心要素？"
    应被保留——真实用户提问本就会提及主题词。"""
    title = "GEO 策略白皮书"
    target_url = "https://example.com/article/geo"
    candidates = [
        _candidate(f"{title} 的核心要素有哪些？"),
        _candidate("如何评估内容营销效果？"),
    ]
    # 关键：forbidden_terms 只含 URL，不含 title
    selected = select_best_questions(candidates, count=2, forbidden_terms=[target_url])
    questions = [c.question for c in selected]
    assert f"{title} 的核心要素有哪些？" in questions


def test_empty_forbidden_terms_keeps_all():
    """forbidden_terms 为空时不过滤任何候选。"""
    candidates = [_candidate("问题一"), _candidate("问题二")]
    selected = select_best_questions(candidates, count=2, forbidden_terms=[])
    assert len(selected) == 2
