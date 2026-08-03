# index-monitor/tests/unit/test_citation_checker_no_index_dep.py
"""CitationChecker 移除收录检测前置依赖的单元测试。

任务 4 背景：原 check_url 在阶段 1/3 准备中调用 _get_indexed_models(url)，
若无已收录模型则抛 ValueError 中断流程，导致引用检测被收录检测阻塞。

本文件覆盖目标：
- test_check_url_no_indexed_models_required：无收录数据时引用检测仍可执行
- test_check_url_uses_all_configured_models：使用所有已配置模型，不受 indexed 限制

设计原则：模型筛选源从 ai_index_results（收录检测产物）改为 adapter_catalog()
中 configured=True 的项（API Key 已配置），引用检测不再依赖收录检测结果。
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.citation_checker import CitationChecker


def _make_fake_adapter(provider_id: str):
    """构造最小 fake adapter，仅暴露 check_url 访问的字段。"""
    adapter = MagicMock()
    adapter.provider_id = provider_id
    adapter.name = provider_id
    adapter.model_id = f"{provider_id}-model"
    return adapter


def _wire_check_url_mocks(checker, monkeypatch, *, indexed_models, configured_models):
    """统一注入 check_url 阶段 1/2/3 的 mock，让测试聚焦被测行为。

    - indexed_models: _get_indexed_models 返回值（收录检测结果）
    - configured_models: _get_configured_models 返回值（已配置 API Key 的模型 id）
    """
    # 阶段 0：配置加载
    async def mock_load_ai_config():
        return {"ai_citation_models": ",".join(configured_models) or "qwen"}

    checker._load_ai_config = mock_load_ai_config
    checker._set_provider_env = MagicMock()

    # 阶段 1a：抓取内容（返回可用内容）
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

    # 阶段 1b：客户问题
    checker._get_client_questions = AsyncMock(return_value=["测试问题"])

    # 阶段 1c：收录模型（旧依赖，保留为参考指标）
    checker._get_indexed_models = AsyncMock(return_value=indexed_models)

    # 阶段 1c'：已配置模型（新依赖，替代 indexed 作为模型筛选源）
    checker._get_configured_models = AsyncMock(return_value=configured_models)

    return mock_content


# --------------------------------------------------------------------------- #
# 测试 1：无收录数据时引用检测仍可执行                                          #
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_check_url_no_indexed_models_required(monkeypatch):
    """无收录数据（_get_indexed_models 返回空）时引用检测仍可执行。

    旧行为：indexed_models 为空 → 抛 ValueError("未被任何 AI 模型收录")。
    新行为：indexed_models 为空不影响流程，使用 configured_models 继续检测。
    """
    checker = CitationChecker(db=MagicMock())

    _wire_check_url_mocks(
        checker, monkeypatch,
        indexed_models=[],  # 无收录数据
        configured_models=["qwen"],  # 但有已配置模型
    )

    # mock 阶段 2：default_adapters + probe
    fake_adapters = [_make_fake_adapter("qwen")]
    monkeypatch.setattr(
        "app.services.citation_checker.default_adapters",
        lambda selected_ids: fake_adapters,
    )
    monkeypatch.setattr(
        "app.services.citation_checker.probe_adapter_capabilities",
        lambda adapters: [
            {"provider_id": "qwen", "model": "千问", "model_id": "qwen3", "status": "verified", "error": None},
        ],
    )

    # mock 阶段 3：run_citation_check
    captured = {}

    def fake_run_citation_check(**kw):
        captured.update(kw)
        return {"results": [], "summary": {}, "questions": []}

    monkeypatch.setattr(
        "app.services.citation_checker.run_citation_check",
        fake_run_citation_check,
    )
    checker._store_results = AsyncMock(return_value=None)

    # 执行：不应抛"未被任何 AI 模型收录"错误
    result = await checker.check_url("https://example.com/a", "client-1")

    # 关键断言：流程走完阶段 3，run_citation_check 被调用且收到 adapters
    assert "adapters" in captured, "无收录数据时应继续到阶段 3 调用 run_citation_check"
    assert len(captured["adapters"]) == 1, "应使用 1 个已配置模型继续检测"
    assert result is not None


# --------------------------------------------------------------------------- #
# 测试 2：使用所有已配置模型，不受 indexed 限制                                 #
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_check_url_uses_all_configured_models(monkeypatch):
    """使用所有已配置模型执行引用检测，不受 indexed_models 限制。

    场景：indexed 只有 qwen，但 configured 有 qwen + doubao。
    旧行为：selected_ids 仅取 indexed ∩ catalog ∩ configured = {qwen}。
    新行为：selected_ids 取 configured ∩ catalog = {qwen, doubao}，
            indexed 不再作为筛选门槛。
    """
    checker = CitationChecker(db=MagicMock())

    _wire_check_url_mocks(
        checker, monkeypatch,
        indexed_models=["qwen"],  # 收录检测只有 qwen
        configured_models=["qwen", "doubao"],  # 但已配置 2 个模型
    )

    # 捕获传给 default_adapters 的 selected_ids
    captured_selected_ids = []
    fake_adapters_map = {
        "qwen": _make_fake_adapter("qwen"),
        "doubao": _make_fake_adapter("doubao"),
    }

    def fake_default_adapters(selected_ids):
        captured_selected_ids.append(list(selected_ids) if selected_ids else [])
        return [fake_adapters_map[i] for i in selected_ids if i in fake_adapters_map]

    monkeypatch.setattr(
        "app.services.citation_checker.default_adapters",
        fake_default_adapters,
    )
    monkeypatch.setattr(
        "app.services.citation_checker.probe_adapter_capabilities",
        lambda adapters: [
            {"provider_id": a.provider_id, "model": a.name, "model_id": a.model_id, "status": "verified", "error": None}
            for a in adapters
        ],
    )

    captured_run = {}

    def fake_run_citation_check(**kw):
        captured_run.update(kw)
        return {"results": [], "summary": {}, "questions": []}

    monkeypatch.setattr(
        "app.services.citation_checker.run_citation_check",
        fake_run_citation_check,
    )
    checker._store_results = AsyncMock(return_value=None)

    await checker.check_url("https://example.com/a", "client-1")

    # 关键断言 1：selected_ids 包含所有已配置模型，不只是 indexed 的
    assert len(captured_selected_ids) == 1, "default_adapters 应被调用 1 次"
    selected = captured_selected_ids[0]
    assert set(selected) == {"qwen", "doubao"}, (
        f"应使用所有已配置模型 {{qwen, doubao}}，实际 {set(selected)}"
    )

    # 关键断言 2：阶段 3 收到 2 个 adapter（不只是 indexed 的 1 个）
    passed_adapters = captured_run.get("adapters", [])
    assert len(passed_adapters) == 2, (
        f"run_citation_check 应收到 2 个 adapter，实际 {len(passed_adapters)}"
    )
    passed_ids = {a.provider_id for a in passed_adapters}
    assert passed_ids == {"qwen", "doubao"}
