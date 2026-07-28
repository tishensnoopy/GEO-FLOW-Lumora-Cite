"""question_generation.py 单元测试：多策略 JSON 清洗 + prompt 微调。

设计规格第 5 节。覆盖目标：
- parse_purpose_response 对带 markdown 围栏的输入能解析
- parse_purpose_response 对 trailing 逗号能解析
- parse_purpose_response 对嵌套文本中的 JSON 能提取
- parse_purpose_response 全部清洗失败时抛 ValueError
- parse_candidate_response 同样鲁棒
- build_purpose_prompt / build_candidate_prompt 含"不要使用 ```json 围栏"提示
"""
import json

import pytest

from app.services.citation_check.question_generation import (
    ArticlePurpose,
    build_purpose_prompt,
    build_candidate_prompt,
    parse_purpose_response,
    parse_candidate_response,
    _candidate_cleanings,
    _candidate_array_cleanings,
)


VALID_PURPOSE = {
    "content_type": "技术教程/方法指南",
    "primary_purpose": "教育市场并建立方法认知",
    "secondary_purposes": ["建立品牌或产品认知"],
    "target_audience": "开发者",
    "desired_takeaway": "理解方法",
    "desired_action": "形成认知",
    "query_territories": ["方向1"],
    "evidence_assets": ["数据1"],
}


def _make_purpose_json():
    return json.dumps(VALID_PURPOSE, ensure_ascii=False)


# --------------------------------------------------------------------------- #
# parse_purpose_response 多策略清洗                                            #
# --------------------------------------------------------------------------- #

def test_parse_purpose_response_plain_json():
    """纯 JSON 字符串应直接解析。"""
    result = parse_purpose_response(_make_purpose_json())
    assert isinstance(result, ArticlePurpose)
    assert result.content_type == "技术教程/方法指南"


def test_parse_purpose_response_markdown_fence():
    """带 ```json 围栏的输入应能解析。"""
    raw = f"```json\n{_make_purpose_json()}\n```"
    result = parse_purpose_response(raw)
    assert result.primary_purpose == "教育市场并建立方法认知"


def test_parse_purpose_response_with_prefix_text():
    """LLM 在 JSON 前后加了解释文本，应能提取 {...}。"""
    raw = f"好的，这是分析结果：\n{_make_purpose_json()}\n以上是分析。"
    result = parse_purpose_response(raw)
    assert result.target_audience == "开发者"


def test_parse_purpose_response_trailing_comma():
    """trailing 逗号应被清洗掉。"""
    raw = '{"content_type":"x","primary_purpose":"y","target_audience":"z","desired_takeaway":"a","desired_action":"b",}'
    result = parse_purpose_response(raw)
    assert result.content_type == "x"


def test_parse_purpose_response_all_cleanings_fail():
    """所有清洗策略都失败时应抛 ValueError。"""
    raw = "这不是 JSON，只是普通文本。"
    with pytest.raises(ValueError, match="无法解析"):
        parse_purpose_response(raw)


def test_parse_purpose_response_missing_required_field():
    """缺少必要字段时应抛 ValueError。"""
    raw = '{"content_type":"x"}'  # 缺 primary_purpose 等
    with pytest.raises(ValueError):
        parse_purpose_response(raw)


# --------------------------------------------------------------------------- #
# parse_candidate_response 多策略清洗                                          #
# --------------------------------------------------------------------------- #

def test_parse_candidate_response_plain_json():
    """纯 JSON 数组应直接解析。"""
    raw = json.dumps([
        {
            "question": "问题1",
            "selection_reason": "理由",
            "purpose_alignment": 0.9,
            "content_support": 0.9,
            "natural_intent": 0.8,
            "citation_need": 0.8,
            "distinctiveness": 0.7,
            "freshness": 0.5,
        }
    ], ensure_ascii=False)
    candidates = parse_candidate_response(raw)
    assert len(candidates) == 1
    assert candidates[0].question == "问题1"


def test_parse_candidate_response_markdown_fence():
    """带 ```json 围栏的数组应能解析。"""
    raw = "```json\n" + json.dumps([
        {
            "question": "Q1", "selection_reason": "r",
            "content_support": 0.9, "natural_intent": 0.8,
            "citation_need": 0.7, "distinctiveness": 0.6, "freshness": 0.5,
        }
    ], ensure_ascii=False) + "\n```"
    candidates = parse_candidate_response(raw)
    assert len(candidates) == 1


def test_parse_candidate_response_with_prefix_text():
    """LLM 在数组前后加了文本，应能提取 [...]。"""
    raw = '以下是生成的候选问题：\n[{"question":"Q1","selection_reason":"r","content_support":0.9,"natural_intent":0.8,"citation_need":0.7,"distinctiveness":0.6,"freshness":0.5}]\n希望对你有帮助。'
    candidates = parse_candidate_response(raw)
    assert len(candidates) == 1
    assert candidates[0].question == "Q1"


def test_parse_candidate_response_all_cleanings_fail():
    """所有清洗策略都失败时应抛 ValueError。"""
    raw = "这不是 JSON 数组"
    with pytest.raises(ValueError, match="无法解析"):
        parse_candidate_response(raw)


# --------------------------------------------------------------------------- #
# 清洗策略函数直接测试                                                         #
# --------------------------------------------------------------------------- #

def test_candidate_cleanings_returns_multiple_strategies():
    """_candidate_cleanings 应返回多个候选清洗结果。"""
    cleanings = list(_candidate_cleanings('{"a":1}'))
    assert len(cleanings) >= 3, "应至少返回 3 种清洗策略"


def test_candidate_array_cleanings_returns_multiple_strategies():
    """_candidate_array_cleanings 应返回多个候选清洗结果。"""
    cleanings = list(_candidate_array_cleanings('[1,2]'))
    assert len(cleanings) >= 3, "应至少返回 3 种清洗策略"


# --------------------------------------------------------------------------- #
# prompt 微调                                                                  #
# --------------------------------------------------------------------------- #

def test_build_purpose_prompt_warns_against_markdown_fence():
    """build_purpose_prompt 应提示不要使用 ```json 围栏。"""
    prompt = build_purpose_prompt("标题", "正文")
    assert "```json" in prompt or "代码块围栏" in prompt, (
        "prompt 应明确提示不要使用 markdown 围栏"
    )


def test_build_candidate_prompt_warns_against_markdown_fence():
    """build_candidate_prompt 应提示不要使用 ```json 围栏。"""
    purpose = ArticlePurpose(
        content_type="x", primary_purpose="y", secondary_purposes=[],
        target_audience="z", desired_takeaway="a", desired_action="b",
        query_territories=[], evidence_assets=[],
    )
    prompt = build_candidate_prompt("标题", "正文", purpose)
    assert "```json" in prompt or "代码块围栏" in prompt, (
        "prompt 应明确提示不要使用 markdown 围栏"
    )
