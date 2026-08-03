# index-monitor/tests/unit/test_citation_checker_stages.py
"""citation_checker.py 单元测试：catalog 过滤 + 阶段标签 + 失败汇总（3 阶段）。

设计规格第 4 节。覆盖目标：
- selected_ids 含已下线 id（如 deepseek）时过滤并告警，不直接报错
- 单条 URL 检测失败时异常带阶段标签 [N/3 阶段名]
- check_all_pending 的 failures 项含 {url, stage, error} 结构
- _extract_stage 能从异常消息中提取阶段标签
- on_config_changed 调用 invalidate_probe_cache

Phase 2 改造：5 阶段（抓取→目的推断→问题生成→模型探测→引用检测）
→ 3 阶段（准备→模型探测→引用检测）。问题来源从 LLM 生成改为客户指定。
原 5 阶段中涉及目的推断/问题生成的测试（deepseek key fallback、无 chat provider
抛错）已删除——3 阶段流程不再有这两个步骤。
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
    """应从异常消息中提取 [N/3 阶段名] 前缀。"""
    msg = "[2/3 模型探测] 联网验证失败：401 Unauthorized"
    assert _extract_stage(msg) == "2/3 模型探测"


def test_extract_stage_no_label():
    """无阶段标签时返回 'unknown'。"""
    msg = "DeepSeek API 调用失败：401 Unauthorized"
    assert _extract_stage(msg) == "unknown"


def test_extract_stage_all_stages():
    """应支持所有 3 个阶段标签格式。"""
    cases = [
        ("[1/3 准备] 内容不可访问", "1/3 准备"),
        ("[2/3 模型探测] 全部失败", "2/3 模型探测"),
        ("[3/3 引用检测] 超时", "3/3 引用检测"),
    ]
    for msg, expected in cases:
        assert _extract_stage(msg) == expected


# --------------------------------------------------------------------------- #
# catalog 过滤（阶段 2 模型探测）                                              #
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_check_url_filters_dropped_model_ids(monkeypatch):
    """selected_ids 含已下线 id 时应过滤并告警，不直接报错。

    策略：mock check_url 的阶段 1（准备）让流程快速走到阶段 2 的 catalog 过滤。
    关键断言：传给 default_adapters 的 selected_ids 应已过滤掉 deepseek
    （deepseek 不在 adapter_catalog 中）。
    """
    checker = CitationChecker(db=MagicMock())

    async def mock_load_ai_config():
        return {
            "ai_citation_models": "qwen,deepseek",  # deepseek 已下线（不在 catalog）
        }
    checker._load_ai_config = mock_load_ai_config
    checker._set_provider_env = MagicMock()

    # mock 阶段 1a：fetch_public_content 返回可用内容
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

    # mock 阶段 1b：客户问题（替代 LLM 自动生成）
    checker._get_client_questions = AsyncMock(return_value=["测试问题"])

    # mock 阶段 1c：已收录模型含 deepseek（应被 catalog 过滤）
    checker._get_indexed_models = AsyncMock(return_value=["qwen", "deepseek"])
    # 任务 4：模型筛选源改为 _get_configured_models（含 deepseek 测试过滤）
    checker._get_configured_models = AsyncMock(return_value=["qwen", "deepseek"])

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

    # mock 阶段 2 后续 + 阶段 3，让流程完成
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
    """阶段 1 抓取失败时异常应带 [1/3 准备] 标签。"""
    checker = CitationChecker(db=MagicMock())

    async def mock_load_ai_config():
        return {"ai_citation_models": "qwen"}
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
    assert "[1/3 准备]" in str(exc_info.value), "阶段 1 失败应带阶段标签"


@pytest.mark.asyncio
async def test_check_all_pending_failure_has_stage(monkeypatch):
    """check_all_pending 的 failures 项应含 {url, stage, error} 结构。

    check_all_pending 内部为每个 URL 创建独立 CitationChecker 实例（AsyncSession
    并发安全 bugfix），实例方法 patch 不会被新实例使用，必须 patch 类方法 +
    mock async_session 避免连真实 DB。
    """
    import app.core.database as db_mod

    class _FakeSessionCM:
        async def __aenter__(self):
            return MagicMock()

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(db_mod, "async_session", lambda: _FakeSessionCM())

    checker = CitationChecker(db=MagicMock())

    # mock get_pending_urls 返回 1 条
    async def fake_get_pending():
        return [("https://example.com/fail", "client-1")]
    checker.get_pending_urls = fake_get_pending

    # mock check_url 抛带阶段标签的错（patch 类方法，让新实例也用 mock）
    async def fake_check_url(self, url, client_id, *, task_id=None, progress=None):
        raise ValueError("[2/3 模型探测] DeepSeek API 调用失败：401")
    monkeypatch.setattr(CitationChecker, "check_url", fake_check_url)

    result = await checker.check_all_pending()

    assert result["total"] == 1
    assert result["success"] == 0
    assert result["failed"] == 1
    assert len(result["failures"]) == 1
    failure = result["failures"][0]
    assert failure["url"] == "https://example.com/fail"
    assert failure["stage"] == "2/3 模型探测", "failure 项应含 stage 字段"
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


# --------------------------------------------------------------------------- #
# 阶段 1 - ③：去 probe 淘汰（保留标注不淘汰）                                   #
# --------------------------------------------------------------------------- #
# 规格：probe_adapter_capabilities 仍调用（结果上报日志展示），但不再用作
# 淘汰门槛。即使所有模型 probe 失败，stage 3 也用全量 adapters 执行引用检测，
# 由 _is_verifiable + classify_citation_hit 在 answer 级判定 unverifiable。
# 仅当 adapters 为空（零模型）时保留硬错误。


def _make_fake_adapter(provider_id: str):
    """构造一个最小 fake adapter，仅暴露 provider_id（check_url 唯一访问字段）。"""
    return MagicMock(provider_id=provider_id)


@pytest.mark.asyncio
async def test_check_url_probe_all_failed_does_not_eliminate(monkeypatch):
    """probe 全部失败时不应在 stage 2 抛错，应继续到 stage 3 用全量 adapters。

    阶段 1 - ③ 核心：probe 降级为标注，不再淘汰模型。
    """
    checker = CitationChecker(db=MagicMock())

    async def mock_load_ai_config():
        return {
            "ai_citation_models": "qwen,doubao",
        }
    checker._load_ai_config = mock_load_ai_config
    checker._set_provider_env = MagicMock()

    # mock 阶段 1a：可用内容
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

    # mock 阶段 1b：客户问题（替代 LLM 自动生成）
    checker._get_client_questions = AsyncMock(return_value=["测试问题"])

    # mock 阶段 1c：已收录模型
    checker._get_indexed_models = AsyncMock(return_value=["qwen", "doubao"])
    # 任务 4：模型筛选源改为 _get_configured_models
    checker._get_configured_models = AsyncMock(return_value=["qwen", "doubao"])

    # 关键 mock：default_adapters 返回 2 个 fake adapter（不走真实网络）
    fake_adapters = [_make_fake_adapter("qwen"), _make_fake_adapter("doubao")]
    monkeypatch.setattr(
        "app.services.citation_checker.default_adapters",
        lambda selected_ids: fake_adapters,
    )

    # 关键 mock：probe 全部失败（无 verified）
    monkeypatch.setattr(
        "app.services.citation_checker.probe_adapter_capabilities",
        lambda adapters: [
            {"provider_id": "qwen", "model": "千问", "model_id": "qwen3", "status": "error", "error": "401"},
            {"provider_id": "doubao", "model": "豆包", "model_id": "doubao1", "status": "no_search", "error": None},
        ],
    )

    # 关键：捕获传给 run_citation_check 的 adapters
    captured_kwargs = {}

    def fake_run_citation_check(**kw):
        captured_kwargs.update(kw)
        return {"results": [], "summary": {}, "questions": []}
    monkeypatch.setattr(
        "app.services.citation_checker.run_citation_check",
        fake_run_citation_check,
    )
    checker._store_results = AsyncMock(return_value=None)

    # 执行：不应抛错（旧 5 阶段实现会在此抛 [4/5 模型探测] 错）
    await checker.check_url("https://example.com/a", "client-1")

    # 关键断言：stage 3 收到的是全量 adapters（2 个），而非空列表
    passed_adapters = captured_kwargs.get("adapters", [])
    assert len(passed_adapters) == 2, (
        f"probe 全失败时 stage 3 应使用全量 adapters（期望 2，实际 {len(passed_adapters)}）"
    )
    passed_ids = {a.provider_id for a in passed_adapters}
    assert passed_ids == {"qwen", "doubao"}


@pytest.mark.asyncio
async def test_check_url_zero_adapters_still_raises_stage2_model_probe(monkeypatch):
    """adapters 为空（零模型）时仍应在 stage 2 抛硬错误。

    阶段 1 - ③ 保留：if not adapters: raise（零模型是配置错误，不可降级）。
    原 5 阶段测试名 test_check_url_zero_adapters_still_raises_stage4 →
    3 阶段重命名为 stage2_model_probe。
    """
    checker = CitationChecker(db=MagicMock())

    async def mock_load_ai_config():
        return {
            "ai_citation_models": "qwen",
        }
    checker._load_ai_config = mock_load_ai_config
    checker._set_provider_env = MagicMock()

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

    # mock 阶段 1b/1c：客户问题 + 已收录模型
    checker._get_client_questions = AsyncMock(return_value=["测试问题"])
    checker._get_indexed_models = AsyncMock(return_value=["qwen"])
    # 任务 4：configured_models 非空以通过阶段 1，让阶段 2 的 default_adapters
    # 返回空列表触发 [2/3 模型探测] 硬错误（零模型不可降级）
    checker._get_configured_models = AsyncMock(return_value=["qwen"])

    # 关键 mock：default_adapters 返回空列表（无任何可用模型）
    monkeypatch.setattr(
        "app.services.citation_checker.default_adapters",
        lambda selected_ids: [],
    )

    with pytest.raises(ValueError) as exc_info:
        await checker.check_url("https://example.com/a", "client-1")
    assert "[2/3 模型探测]" in str(exc_info.value), (
        "零模型硬错误应带 [2/3 模型探测] 标签"
    )
