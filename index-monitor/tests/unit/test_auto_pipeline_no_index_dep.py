# index-monitor/tests/unit/test_auto_pipeline_no_index_dep.py
"""AutoPipeline 引用检测移除收录检测前置依赖的单元测试。

任务 5 背景：原 ``_auto_trigger_citation_check`` 查询
``AIIndexResult.index_status == "indexed"`` 来决定是否执行引用检测，
若无 indexed 模型则 ``return`` 跳过。修改后引用检测直接执行，
不再依赖收录检测结果，仅保留客户 active 问题检查作为前置门槛。

本文件覆盖目标：
- test_citation_check_runs_without_index：无 indexed 模型时引用检测仍可执行
- test_index_check_failure_does_not_block_citation：收录检测抛异常时引用检测仍可执行

设计原则：与 ``test_auto_pipeline.py`` 共用 mock 模式（async_session 替换、
AIIndexChecker/CitationChecker mock），但使用独立的 client_id / URL 隔离数据，
避免与既有用例的清理逻辑冲突。
"""
import pytest
import pytest_asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

from app.services.auto_pipeline import AutoPipeline


TEST_URL = "https://example.com/cite-test"
TEST_CLIENT = "cite_client"


@pytest_asyncio.fixture(autouse=True)
async def _cleanup_test_data(db_session):
    """每个测试前清理本文件用到的 ai_index_results / client_questions 残留数据。

    db_session fixture 不做事务回滚（见 conftest.py 注释），client_questions
    无唯一约束——二次运行会污染。这里在测试前统一清理本文件用到的
    URL / client_id，使单独运行与套件运行都通过。
    """
    from sqlalchemy import delete
    from app.models.ai_index_result import AIIndexResult
    from app.models.client_question import ClientQuestion

    await db_session.execute(
        delete(AIIndexResult).where(AIIndexResult.url == TEST_URL)
    )
    await db_session.execute(
        delete(ClientQuestion).where(ClientQuestion.client_id == TEST_CLIENT)
    )
    await db_session.commit()
    yield


@pytest_asyncio.fixture(autouse=True)
async def _patch_async_session(db_session, monkeypatch):
    """将 auto_pipeline 模块级 ``async_session`` 替换为返回当前测试 ``db_session`` 的上下文管理器。

    与 ``test_auto_pipeline.py`` 同名 fixture 同理：避免跨用例事件循环复用
    触发 "Future attached to a different loop"。
    """

    @asynccontextmanager
    async def fake_session():
        yield db_session

    monkeypatch.setattr(
        "app.services.auto_pipeline.async_session",
        lambda: fake_session(),
    )
    yield


async def _seed_active_client_question(db_session):
    """插入客户 active 问题，确保通过客户问题检查门槛。

    修改后的 ``_auto_trigger_citation_check`` 保留客户 active 问题检查——
    无 active 问题仍会跳过引用检测。本文件两个用例都需要引用检测被执行，
    故统一预置一条 active 问题。
    """
    from app.models.client_question import ClientQuestion

    db_session.add(
        ClientQuestion(
            client_id=TEST_CLIENT,
            question="引用是否准确",
            sort_order=1,
            status="active",
        )
    )
    await db_session.commit()


# --------------------------------------------------------------------------- #
# 测试 1：无 indexed 模型时，引用检测仍可执行                                   #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_citation_check_runs_without_index(db_session, monkeypatch):
    """无 indexed 模型时，引用检测仍可执行。

    旧行为：无 indexed 模型 → ``if not indexed_models: return`` → 跳过引用检测。
    新行为：不再查询 indexed 模型，只要客户有 active 问题就执行引用检测。
    """
    pipeline = AutoPipeline()

    # 无配置模型 → 收录检测阶段直接跳过，DB 中不会有任何 indexed 记录
    monkeypatch.setattr(
        "app.services.auto_pipeline.AIIndexChecker._get_configured_models",
        lambda self: [],
    )

    # 预置客户 active 问题，通过客户问题检查门槛
    await _seed_active_client_question(db_session)

    mock_citation = AsyncMock()
    monkeypatch.setattr(
        "app.services.auto_pipeline.CitationChecker.check_url",
        mock_citation,
    )

    await pipeline.trigger_for_url(TEST_URL, TEST_CLIENT)

    # 关键断言：无 indexed 模型时引用检测仍执行
    mock_citation.assert_called_once()


# --------------------------------------------------------------------------- #
# 测试 2：收录检测抛异常时，引用检测仍可执行                                    #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_index_check_failure_does_not_block_citation(db_session, monkeypatch):
    """收录检测抛异常时，引用检测仍可执行。

    旧行为：收录检测 check_url 抛异常 → _run_ai_index_check 内部捕获 →
    DB 中无 indexed 记录 → _auto_trigger_citation_check 查询 indexed 为空 →
    跳过引用检测。
    新行为：不再查询 indexed 模型，收录检测失败不影响引用检测执行。
    """
    pipeline = AutoPipeline()

    # 有配置模型，但 check_url 抛异常（模拟收录检测 API 失败）
    monkeypatch.setattr(
        "app.services.auto_pipeline.AIIndexChecker._get_configured_models",
        lambda self: ["qwen"],
    )

    async def fake_check_url(self, url, model, **kw):
        raise RuntimeError("模拟收录检测 API 失败")

    monkeypatch.setattr(
        "app.services.auto_pipeline.AIIndexChecker.check_url",
        fake_check_url,
    )

    # 预置客户 active 问题，通过客户问题检查门槛
    await _seed_active_client_question(db_session)

    mock_citation = AsyncMock()
    monkeypatch.setattr(
        "app.services.auto_pipeline.CitationChecker.check_url",
        mock_citation,
    )

    await pipeline.trigger_for_url(TEST_URL, TEST_CLIENT)

    # 关键断言：收录检测失败时引用检测仍执行
    mock_citation.assert_called_once()
