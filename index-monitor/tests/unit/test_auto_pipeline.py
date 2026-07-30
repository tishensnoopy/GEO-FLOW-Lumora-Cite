"""AutoPipeline 自动联动管道单元测试。"""
import pytest
import pytest_asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.auto_pipeline import AutoPipeline


@pytest_asyncio.fixture(autouse=True)
async def _cleanup_test_data(db_session):
    """每个测试前清理本文件用到的 ai_index_results / client_questions 残留数据。

    db_session fixture 不做事务回滚（见 conftest.py 注释），ai_index_results 有
    UNIQUE(url, model) 约束，client_questions 无唯一约束——二次运行会冲突或污染。
    这里在测试前统一清理本文件用到的 URL / client_id，使单独运行与套件运行都通过。
    """
    from sqlalchemy import delete
    from app.models.ai_index_result import AIIndexResult
    from app.models.client_question import ClientQuestion

    await db_session.execute(
        delete(AIIndexResult).where(
            AIIndexResult.url == "https://example.com/test"
        )
    )
    await db_session.execute(
        delete(ClientQuestion).where(
            ClientQuestion.client_id.in_(["client_a", "no_questions_client"])
        )
    )
    await db_session.commit()
    yield


@pytest_asyncio.fixture(autouse=True)
async def _patch_async_session(db_session, monkeypatch):
    """将 auto_pipeline 模块级 ``async_session`` 替换为返回当前测试 ``db_session`` 的上下文管理器。

    背景：``app.services.auto_pipeline`` import 的 ``async_session`` 是
    ``app.core.database`` 模块级 ``async_sessionmaker``，首次使用时绑定到首个测试
    的事件循环。pytest-asyncio strict 模式每个测试独立事件循环 → 跨用例复用会触发
    "Future attached to a different loop"。

    替换为 yield 当前测试 ``db_session``（绑定到当前循环）的 async context manager，
    使 ``trigger_for_url`` 内部的 ``async with async_session() as db`` 拿到正确的
    session。需要自定义 fake_session 的测试（如 no_indexed_models/no_client_questions）
    可在测试体内再次 ``monkeypatch.setattr`` 覆盖本 fixture 的设置（后设置的生效）。
    """

    @asynccontextmanager
    async def fake_session():
        yield db_session

    monkeypatch.setattr(
        "app.services.auto_pipeline.async_session",
        lambda: fake_session(),
    )
    yield


@pytest.mark.asyncio
async def test_trigger_for_url_no_models(db_session, monkeypatch):
    """无配置模型时，跳过收录检测，不执行问题监测。"""
    pipeline = AutoPipeline()

    # mock 无配置模型
    monkeypatch.setattr(
        "app.services.auto_pipeline.AIIndexChecker._get_configured_models",
        lambda self: [],
    )
    mock_citation = AsyncMock()
    monkeypatch.setattr(
        "app.services.auto_pipeline.CitationChecker.check_url",
        mock_citation,
    )

    await pipeline.trigger_for_url("https://example.com/test", "client_a")

    mock_citation.assert_not_called()


@pytest.mark.asyncio
async def test_trigger_for_url_no_indexed_models(db_session, monkeypatch):
    """收录检测完成但无 indexed 模型时，跳过问题监测。"""
    pipeline = AutoPipeline()

    # mock 有配置模型
    monkeypatch.setattr(
        "app.services.auto_pipeline.AIIndexChecker._get_configured_models",
        lambda self: ["qwen"],
    )
    # mock check_url 成功但返回 not_indexed
    async def fake_check_url(self, url, model, **kw):
        return {"index_status": "not_indexed"}
    monkeypatch.setattr(
        "app.services.auto_pipeline.AIIndexChecker.check_url",
        fake_check_url,
    )

    # mock 查询 indexed 模型返回空
    async def fake_execute(stmt):
        result = MagicMock()
        result.fetchall = lambda: []
        return result
    monkeypatch.setattr(
        "app.services.auto_pipeline.async_session",
        MagicMock(return_value=MagicMock(__aenter__=AsyncMock(return_value=db_session), __aexit__=AsyncMock(return_value=None))),
    )

    mock_citation = AsyncMock()
    monkeypatch.setattr(
        "app.services.auto_pipeline.CitationChecker.check_url",
        mock_citation,
    )

    await pipeline.trigger_for_url("https://example.com/test", "client_a")

    mock_citation.assert_not_called()


@pytest.mark.asyncio
async def test_trigger_for_url_no_client_questions(db_session, monkeypatch):
    """有 indexed 模型但客户无 active 问题时，跳过问题监测。"""
    pipeline = AutoPipeline()

    monkeypatch.setattr(
        "app.services.auto_pipeline.AIIndexChecker._get_configured_models",
        lambda self: ["qwen"],
    )
    async def fake_check_url(self, url, model, **kw):
        return {"index_status": "indexed"}
    monkeypatch.setattr(
        "app.services.auto_pipeline.AIIndexChecker.check_url",
        fake_check_url,
    )

    # mock 查询 indexed 模型返回 qwen
    from app.models.ai_index_result import AIIndexResult
    db_session.add(AIIndexResult(
        url="https://example.com/test", model="qwen", index_status="indexed",
    ))
    await db_session.commit()

    # mock async_session 返回 db_session
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def fake_session():
        yield db_session

    monkeypatch.setattr(
        "app.services.auto_pipeline.async_session",
        lambda: fake_session(),
    )

    mock_citation = AsyncMock()
    monkeypatch.setattr(
        "app.services.auto_pipeline.CitationChecker.check_url",
        mock_citation,
    )

    await pipeline.trigger_for_url("https://example.com/test", "no_questions_client")

    mock_citation.assert_not_called()


@pytest.mark.asyncio
async def test_trigger_for_url_error_isolation(db_session, monkeypatch):
    """收录检测失败不阻塞流程，问题监测仍可执行。"""
    pipeline = AutoPipeline()

    monkeypatch.setattr(
        "app.services.auto_pipeline.AIIndexChecker._get_configured_models",
        lambda self: ["qwen", "doubao"],
    )

    call_log = []

    async def fake_check_url(self, url, model, **kw):
        call_log.append(model)
        if model == "qwen":
            raise RuntimeError("模拟 API 失败")
        return {"index_status": "indexed"}

    monkeypatch.setattr(
        "app.services.auto_pipeline.AIIndexChecker.check_url",
        fake_check_url,
    )

    # mock 查询 indexed 模型返回 doubao
    from app.models.ai_index_result import AIIndexResult
    from app.models.client_question import ClientQuestion
    db_session.add(AIIndexResult(
        url="https://example.com/test", model="doubao", index_status="indexed",
    ))
    db_session.add(ClientQuestion(
        client_id="client_a", question="问题", sort_order=1, status="active",
    ))
    await db_session.commit()

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def fake_session():
        yield db_session

    monkeypatch.setattr(
        "app.services.auto_pipeline.async_session",
        lambda: fake_session(),
    )

    mock_citation = AsyncMock()
    monkeypatch.setattr(
        "app.services.auto_pipeline.CitationChecker.check_url",
        mock_citation,
    )

    await pipeline.trigger_for_url("https://example.com/test", "client_a")

    # 两个模型都被调用
    assert set(call_log) == {"qwen", "doubao"}
    # 问题监测被执行
    mock_citation.assert_called_once()
