"""citation_checker.py 单元测试：catalog 过滤 + 阶段标签 + 失败汇总。

设计规格第 4 节。覆盖目标：
- selected_ids 含已下线 id（如 deepseek）时过滤并告警，不直接报错
- 单条 URL 检测失败时异常带阶段标签 [N/5 阶段名]
- check_all_pending 的 failures 项含 {url, stage, error} 结构
- _extract_stage 能从异常消息中提取阶段标签
- on_config_changed 调用 invalidate_probe_cache
"""
import asyncio
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

from app.services.citation_checker import CitationChecker
from app.services.citation_checker import _extract_stage


# --------------------------------------------------------------------------- #
# _extract_stage 阶段标签提取                                                  #
# --------------------------------------------------------------------------- #

def test_extract_stage_normal():
    """应从异常消息中提取 [N/5 阶段名] 前缀。"""
    msg = "[2/5 目的推断] DeepSeek API 调用失败：401 Unauthorized"
    assert _extract_stage(msg) == "2/5 目的推断"


def test_extract_stage_no_label():
    """无阶段标签时返回 'unknown'。"""
    msg = "DeepSeek API 调用失败：401 Unauthorized"
    assert _extract_stage(msg) == "unknown"


def test_extract_stage_all_stages():
    """应支持所有 5 个阶段标签格式。"""
    cases = [
        ("[1/5 抓取] 内容不可访问", "1/5 抓取"),
        ("[2/5 目的推断] JSON 解析失败", "2/5 目的推断"),
        ("[3/5 问题生成] 候选不足", "3/5 问题生成"),
        ("[4/5 模型探测] 全部失败", "4/5 模型探测"),
        ("[5/5 引用检测] 超时", "5/5 引用检测"),
    ]
    for msg, expected in cases:
        assert _extract_stage(msg) == expected


# --------------------------------------------------------------------------- #
# catalog 过滤（步骤 4）                                                       #
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_check_url_filters_dropped_model_ids(monkeypatch):
    """selected_ids 含已下线 id 时应过滤并告警，不直接报错。

    策略：mock check_url 的前 3 步让流程快速走到步骤 4 的 catalog 过滤。
    关键断言：传给 default_adapters 的 selected_ids 应已过滤掉 deepseek。
    """
    checker = CitationChecker(db=MagicMock())

    async def mock_load_ai_config():
        return {
            "ai_deepseek_api_key": "fake-key",
            "ai_question_model": "deepseek-chat",
            "ai_citation_models": "qwen,deepseek",  # deepseek 已下线
        }
    checker._load_ai_config = mock_load_ai_config
    checker._set_provider_env = MagicMock()

    # mock 步骤 1：fetch_public_content 返回可用内容
    mock_content = MagicMock()
    mock_content.suitability.suitable = True
    mock_content.title = "标题"
    mock_content.text = "正文"
    mock_content.requested_url = "https://example.com/a"
    mock_content.resolved_url = None
    mock_content.canonical_url = None
    mock_content.extraction_method = "test"
    monkeypatch.setattr(
        "app.services.citation_checker.fetch_public_content",
        lambda url: mock_content,
    )

    # mock 步骤 2：call_deepseek_with_parse_retry 返回 fake purpose
    from app.services.citation_check.question_generation import ArticlePurpose
    fake_purpose = ArticlePurpose(
        content_type="x", primary_purpose="y", secondary_purposes=[],
        target_audience="z", desired_takeaway="a", desired_action="b",
        query_territories=[], evidence_assets=[],
    )
    # 它是同步函数，被 asyncio.to_thread 调用
    monkeypatch.setattr(
        "app.services.citation_checker.call_deepseek_with_parse_retry",
        lambda *args, **kw: fake_purpose,
    )

    # mock 步骤 3：generate_candidates 返回足够候选
    from app.services.citation_check.questions import QuestionCandidate
    fake_candidates = [
        QuestionCandidate(
            question=f"Q{i}", selection_reason="r",
            content_support=0.9, natural_intent=0.8, citation_need=0.7,
            distinctiveness=0.6, freshness=0.5,
            metadata={},
        )
        for i in range(5)
    ]
    monkeypatch.setattr(
        "app.services.citation_checker.generate_candidates",
        lambda **kw: fake_candidates,
    )
    monkeypatch.setattr(
        "app.services.citation_checker.make_parse_retry_generator",
        lambda *a, **kw: (lambda prompt: ""),
    )

    # 关键：捕获传给 default_adapters 的 selected_ids
    captured_selected_ids = []

    def fake_default_adapters(selected_ids):
        captured_selected_ids.append(list(selected_ids) if selected_ids else selected_ids)
        from app.services.citation_check.providers import default_adapters as real_default_adapters
        return real_default_adapters(selected_ids)

    monkeypatch.setattr(
        "app.services.citation_checker.default_adapters",
        fake_default_adapters,
    )

    # mock 步骤 4 后续 + 步骤 5，让流程完成
    monkeypatch.setattr(
        "app.services.citation_checker.probe_adapter_capabilities",
        lambda adapters: [{"provider_id": "qwen", "model": "千问", "model_id": "qwen3.6-plus", "status": "verified", "web_search": True, "sources_returned": True, "sample_sources": [], "error": None}],
    )
    monkeypatch.setattr(
        "app.services.citation_checker.run_citation_check",
        lambda **kw: {"results": [], "summary": {}, "questions": []},
    )
    checker._store_results = AsyncMock(return_value=None)

    # 执行 check_url
    await checker.check_url("https://example.com/a", "client-1")

    # 关键断言：传给 default_adapters 的 selected_ids 应已过滤掉 deepseek
    assert len(captured_selected_ids) == 1, "default_adapters 应被调用 1 次"
    selected = captured_selected_ids[0]
    assert selected is not None, "应有非空 selected_ids（含 qwen）"
    assert "deepseek" not in selected, "已下线的 deepseek 应被过滤掉"
    assert "qwen" in selected, "有效 id 应保留"


# --------------------------------------------------------------------------- #
# 阶段标签 + 失败汇总                                                          #
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_check_url_failure_includes_stage_label(monkeypatch):
    """步骤 1 抓取失败时异常应带 [1/5 抓取] 标签。"""
    checker = CitationChecker(db=MagicMock())

    async def mock_load_ai_config():
        return {"ai_deepseek_api_key": "fake-key", "ai_question_model": "deepseek-chat"}
    checker._load_ai_config = mock_load_ai_config

    # mock fetch_public_content 抛错
    def fake_fetch(url):
        raise RuntimeError("连接超时")
    monkeypatch.setattr(
        "app.services.citation_checker.fetch_public_content",
        fake_fetch,
    )

    with pytest.raises(ValueError) as exc_info:
        await checker.check_url("https://example.com/a", "client-1")
    assert "[1/5 抓取]" in str(exc_info.value), "步骤 1 失败应带阶段标签"


@pytest.mark.asyncio
async def test_check_all_pending_failure_has_stage(monkeypatch):
    """check_all_pending 的 failures 项应含 {url, stage, error} 结构。"""
    checker = CitationChecker(db=MagicMock())

    # mock get_pending_urls 返回 1 条
    async def fake_get_pending():
        return [("https://example.com/fail", "client-1")]
    checker.get_pending_urls = fake_get_pending

    # mock check_url 抛带阶段标签的错
    async def fake_check_url(url, client_id):
        raise ValueError("[2/5 目的推断] DeepSeek API 调用失败：401")
    checker.check_url = fake_check_url

    result = await checker.check_all_pending()

    assert result["total"] == 1
    assert result["success"] == 0
    assert result["failed"] == 1
    assert len(result["failures"]) == 1
    failure = result["failures"][0]
    assert failure["url"] == "https://example.com/fail"
    assert failure["stage"] == "2/5 目的推断", "failure 项应含 stage 字段"
    assert "401" in failure["error"]


# --------------------------------------------------------------------------- #
# on_config_changed 清探测缓存                                                 #
# --------------------------------------------------------------------------- #

def test_on_config_changed_invalidates_probe_cache(monkeypatch):
    """on_config_changed 应调用 invalidate_probe_cache()。"""
    checker = CitationChecker(db=MagicMock())
    called = [False]

    def fake_invalidate(provider_id=None):
        called[0] = True
    monkeypatch.setattr(
        "app.services.citation_checker.invalidate_probe_cache",
        fake_invalidate,
    )

    checker.on_config_changed()
    assert called[0], "on_config_changed 应调用 invalidate_probe_cache"


def test_on_config_changed_invalidates_by_provider_id(monkeypatch):
    """on_config_changed(provider_id) 应只清指定模型。"""
    checker = CitationChecker(db=MagicMock())
    captured = []

    def fake_invalidate(provider_id=None):
        captured.append(provider_id)
    monkeypatch.setattr(
        "app.services.citation_checker.invalidate_probe_cache",
        fake_invalidate,
    )

    checker.on_config_changed(provider_id="qwen")
    assert captured == ["qwen"]
