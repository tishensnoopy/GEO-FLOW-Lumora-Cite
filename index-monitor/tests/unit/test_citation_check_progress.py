# index-monitor/tests/unit/test_citation_check_progress.py
"""check_url progress 回调测试（阶段 2 - ④b）。

验证目标：
1. check_url 在每个 stage 开始/结束调用 progress 回调
2. stage 失败时 progress 收到 "error" 状态
3. stage 4 probe 结果按模型逐条上报
4. 默认 progress 回调持久化 CitationCheckLog 到 db
5. 默认 progress 回调同步写 scan_task_manager.add_log（供 ScanPanel 实时轮询）

解决用户问题 3：采信检测黑盒，只报成功/失败，不知道失败在哪。
"""
import asyncio
import time
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

from app.services.citation_checker import CitationChecker


def _setup_success_mocks(monkeypatch, checker):
    """配置 check_url 全流程成功的 mock，返回捕获 run_citation_check 入参的 dict。"""

    async def mock_load_ai_config():
        return {
            "ai_deepseek_api_key": "ds-key",
            "ai_question_model": "deepseek-chat",
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

    from app.services.citation_check.question_generation import ArticlePurpose
    fake_purpose = ArticlePurpose(
        content_type="x", primary_purpose="y", secondary_purposes=[],
        target_audience="z", desired_takeaway="a", desired_action="b",
        query_territories=[], evidence_assets=[],
    )
    monkeypatch.setattr(
        "app.services.citation_checker.call_llm_with_parse_retry_fallback",
        lambda providers, prompt, *, parser, **kw: "raw purpose text",
    )
    monkeypatch.setattr(
        "app.services.citation_checker.parse_purpose_response",
        lambda text: fake_purpose,
    )

    from app.services.citation_check.questions import QuestionCandidate
    fake_candidates = [
        QuestionCandidate(
            question=f"Q{i}", selection_reason="r",
            content_support=0.9, natural_intent=0.8, citation_need=0.7,
            distinctiveness=0.6, freshness=0.5, metadata={},
        )
        for i in range(5)
    ]
    monkeypatch.setattr(
        "app.services.citation_checker.generate_candidates",
        lambda **kw: fake_candidates,
    )
    monkeypatch.setattr(
        "app.services.citation_checker.make_fallback_parse_retry_generator",
        lambda providers, *, parser, **kw: (lambda prompt: ""),
    )

    monkeypatch.setattr(
        "app.services.citation_checker.default_adapters",
        lambda selected_ids: [MagicMock(provider_id="qwen")],
    )
    monkeypatch.setattr(
        "app.services.citation_checker.probe_adapter_capabilities",
        lambda adapters: [
            {"provider_id": "qwen", "model": "千问", "model_id": "qwen3", "status": "verified"},
        ],
    )

    captured = {}

    def fake_run_citation_check(**kw):
        captured.update(kw)
        return {"results": [], "summary": {}, "questions": []}
    monkeypatch.setattr(
        "app.services.citation_checker.run_citation_check",
        fake_run_citation_check,
    )
    checker._store_results = AsyncMock(return_value=None)
    return captured


def _make_recording_progress():
    """构造一个记录所有调用的 async progress 回调。"""
    calls = []

    async def progress(stage, status, message, *, detail=None, model=None, duration_ms=None):
        calls.append({
            "stage": stage, "status": status, "message": message,
            "detail": detail, "model": model, "duration_ms": duration_ms,
        })

    return progress, calls


# --------------------------------------------------------------------------- #
# 每个 stage 调用 progress                                                     #
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_progress_called_for_each_stage(monkeypatch):
    """check_url 应为 5 个 stage 各调用 progress（至少 start + success）。"""
    checker = CitationChecker(db=MagicMock())
    _setup_success_mocks(monkeypatch, checker)
    progress, calls = _make_recording_progress()

    await checker.check_url("https://example.com/a", "client-1", progress=progress)

    stages_reported = {c["stage"] for c in calls}
    # 5 个阶段都应被上报
    assert "1/5 抓取" in stages_reported
    assert "2/5 目的推断" in stages_reported
    assert "3/5 问题生成" in stages_reported
    assert "4/5 模型探测" in stages_reported
    assert "5/5 引用检测" in stages_reported

    # 每个 stage 应有 success 状态
    success_stages = {c["stage"] for c in calls if c["status"] == "success"}
    assert success_stages == {"1/5 抓取", "2/5 目的推断", "3/5 问题生成", "4/5 模型探测", "5/5 引用检测"}


# --------------------------------------------------------------------------- #
# stage 失败时 progress 收到 error                                             #
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_progress_error_on_stage1_failure(monkeypatch):
    """stage 1 抓取失败时，progress 应收到 '1/5 抓取' + 'error' 状态。"""
    checker = CitationChecker(db=MagicMock())

    async def mock_load_ai_config():
        return {"ai_deepseek_api_key": "ds-key", "ai_question_model": "deepseek-chat"}
    checker._load_ai_config = mock_load_ai_config
    checker._set_provider_env = MagicMock()

    monkeypatch.setattr(
        "app.services.citation_checker.fetch_public_content",
        lambda url: (_ for _ in ()).throw(RuntimeError("连接超时")),
    )

    progress, calls = _make_recording_progress()

    with pytest.raises(ValueError):
        await checker.check_url("https://example.com/a", "client-1", progress=progress)

    error_calls = [c for c in calls if c["status"] == "error"]
    assert len(error_calls) >= 1, "stage 1 失败应上报 error"
    assert error_calls[0]["stage"] == "1/5 抓取"
    assert "超时" in error_calls[0]["message"]


# --------------------------------------------------------------------------- #
# stage 4 probe 按模型逐条上报                                                  #
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_progress_reports_probe_per_model(monkeypatch):
    """stage 4 应按模型逐条上报 probe 结果（千问: verified / 豆包: error）。"""
    checker = CitationChecker(db=MagicMock())
    _setup_success_mocks(monkeypatch, checker)

    # 覆盖 probe：返回 2 个模型，状态不同
    monkeypatch.setattr(
        "app.services.citation_checker.probe_adapter_capabilities",
        lambda adapters: [
            {"provider_id": "qwen", "model": "千问", "model_id": "qwen3", "status": "verified"},
            {"provider_id": "doubao", "model": "豆包", "model_id": "doubao1", "status": "error", "error": "401"},
        ],
    )
    monkeypatch.setattr(
        "app.services.citation_checker.default_adapters",
        lambda selected_ids: [MagicMock(provider_id="qwen"), MagicMock(provider_id="doubao")],
    )

    progress, calls = _make_recording_progress()
    await checker.check_url("https://example.com/a", "client-1", progress=progress)

    # 找到 stage 4 的模型级上报（model 字段非空）
    probe_model_calls = [c for c in calls if c["stage"] == "4/5 模型探测" and c["model"]]
    models_reported = {c["model"] for c in probe_model_calls}
    assert "千问" in models_reported, "应上报千问的 probe 结果"
    assert "豆包" in models_reported, "应上报豆包的 probe 结果"

    # 千问应标记为 verified
    qwen_call = next(c for c in probe_model_calls if c["model"] == "千问")
    assert "verified" in qwen_call["message"] or qwen_call["status"] == "success"


# --------------------------------------------------------------------------- #
# 默认 progress 持久化 CitationCheckLog                                        #
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_default_progress_persists_citation_check_log(monkeypatch):
    """不传 progress 时，默认回调应把 CitationCheckLog 写入 db。"""
    from app.models.citation_check_log import CitationCheckLog

    added_logs = []
    db = MagicMock()
    db.add = MagicMock(side_effect=lambda obj: added_logs.append(obj))
    db.commit = AsyncMock()

    checker = CitationChecker(db=db)
    _setup_success_mocks(monkeypatch, checker)

    await checker.check_url("https://example.com/a", "client-1", task_id="task-xyz")

    # 应至少有 5 条 CitationCheckLog（每 stage 至少一条）
    assert len(added_logs) >= 5, f"应持久化至少 5 条日志，实际 {len(added_logs)}"
    assert all(isinstance(log, CitationCheckLog) for log in added_logs)
    # task_id 和 url 应正确填充
    assert all(log.task_id == "task-xyz" for log in added_logs)
    assert all(log.url == "https://example.com/a" for log in added_logs)


# --------------------------------------------------------------------------- #
# 默认 progress 调用 scan_task_manager.add_log                                 #
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_default_progress_calls_task_manager_add_log(monkeypatch):
    """有 task_id 时，默认回调应同步写 scan_task_manager.add_log（供 ScanPanel 轮询）。"""
    checker = CitationChecker(db=MagicMock())
    db = MagicMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    checker.db = db
    _setup_success_mocks(monkeypatch, checker)

    add_log_calls = []

    def fake_add_log(task_id, level, message):
        add_log_calls.append((task_id, level, message))

    monkeypatch.setattr(
        "app.services.citation_checker.add_log",
        fake_add_log,
    )

    await checker.check_url("https://example.com/a", "client-1", task_id="task-abc")

    # 应至少调用一次 add_log（stage 1 start）
    assert len(add_log_calls) >= 1, "默认 progress 应调用 scan_task_manager.add_log"
    assert all(tid == "task-abc" for tid, _, _ in add_log_calls), "add_log 的 task_id 应正确"


@pytest.mark.asyncio
async def test_default_progress_no_task_id_skips_add_log(monkeypatch):
    """无 task_id（定时任务）时，默认回调不调 add_log，但仍写 CitationCheckLog。"""
    from app.models.citation_check_log import CitationCheckLog

    db = MagicMock()
    added_logs = []
    db.add = MagicMock(side_effect=lambda obj: added_logs.append(obj))
    db.commit = AsyncMock()

    checker = CitationChecker(db=db)
    _setup_success_mocks(monkeypatch, checker)

    add_log_calls = []
    monkeypatch.setattr(
        "app.services.citation_checker.add_log",
        lambda tid, lvl, msg: add_log_calls.append((tid, lvl, msg)),
    )

    # 不传 task_id
    await checker.check_url("https://example.com/a", "client-1")

    assert add_log_calls == [], "无 task_id 时不应调用 add_log"
    assert len(added_logs) >= 5, "无 task_id 时仍应持久化 CitationCheckLog"
    assert all(log.task_id is None for log in added_logs)


# --------------------------------------------------------------------------- #
# check_all_pending 透传 task_id                                               #
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_check_all_pending_passes_task_id_to_check_url(monkeypatch):
    """check_all_pending(task_id=...) 应把 task_id 透传给 check_url。"""
    # check_all_pending 内部为每个 URL 创建独立 CitationChecker 实例（AsyncSession
    # 并发安全 bugfix），实例方法 patch 不会被新实例使用，必须 patch 类方法 +
    # mock async_session 避免连真实 DB。
    import app.core.database as db_mod

    class _FakeSessionCM:
        async def __aenter__(self):
            return MagicMock()

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(db_mod, "async_session", lambda: _FakeSessionCM())

    checker = CitationChecker(db=MagicMock())

    async def fake_get_pending():
        return [("https://example.com/a", "client-1")]
    checker.get_pending_urls = fake_get_pending

    received_task_ids = []

    async def fake_check_url(self, url, client_id, *, task_id=None, progress=None):
        received_task_ids.append(task_id)
    monkeypatch.setattr(CitationChecker, "check_url", fake_check_url)

    await checker.check_all_pending(task_id="batch-task-1")

    assert received_task_ids == ["batch-task-1"], (
        f"check_all_pending 应透传 task_id，实际收到 {received_task_ids}"
    )


# --------------------------------------------------------------------------- #
# 默认 progress 在 stage 4 调用 update_citation_model（结构化模型状态）        #
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_default_progress_updates_citation_model_in_stage4(monkeypatch):
    """stage 4 模型级上报时，默认回调应调用 update_citation_model（结构化存储）。

    阶段 4 - ⑤：让 ScanPanel 模型状态卡片直接读 task.citation_models，
    而非从日志文本脆弱解析。
    """
    checker = CitationChecker(db=MagicMock())
    _setup_success_mocks(monkeypatch, checker)

    # 覆盖 probe：返回 2 个模型
    monkeypatch.setattr(
        "app.services.citation_checker.probe_adapter_capabilities",
        lambda adapters: [
            {"provider_id": "qwen", "model": "千问", "model_id": "qwen3", "status": "verified"},
            {"provider_id": "doubao", "model": "豆包", "model_id": "doubao1", "status": "error", "error": "401"},
        ],
    )
    monkeypatch.setattr(
        "app.services.citation_checker.default_adapters",
        lambda selected_ids: [MagicMock(provider_id="qwen"), MagicMock(provider_id="doubao")],
    )

    update_calls = []
    monkeypatch.setattr(
        "app.services.citation_checker.update_citation_model",
        lambda tid, model, status, error=None: update_calls.append((tid, model, status, error)),
    )

    await checker.check_url("https://example.com/a", "client-1", task_id="task-models")

    # 应为每个模型调用一次 update_citation_model
    assert len(update_calls) == 2, f"应为 2 个模型调用 update_citation_model，实际 {len(update_calls)}"
    models_updated = {(c[1], c[2]) for c in update_calls}
    assert ("千问", "verified") in models_updated
    assert ("豆包", "error") in models_updated
    # task_id 正确
    assert all(c[0] == "task-models" for c in update_calls)
    # 豆包的 error 应传递
    doubao_call = next(c for c in update_calls if c[1] == "豆包")
    assert doubao_call[3] == "401"


@pytest.mark.asyncio
async def test_default_progress_no_task_id_skips_update_citation_model(monkeypatch):
    """无 task_id 时，默认回调不调 update_citation_model（无活动窗口）。"""
    checker = CitationChecker(db=MagicMock())
    _setup_success_mocks(monkeypatch, checker)

    update_calls = []
    monkeypatch.setattr(
        "app.services.citation_checker.update_citation_model",
        lambda tid, model, status, error=None: update_calls.append((tid, model, status, error)),
    )

    # 不传 task_id
    await checker.check_url("https://example.com/a", "client-1")

    assert update_calls == [], "无 task_id 时不应调用 update_citation_model"
