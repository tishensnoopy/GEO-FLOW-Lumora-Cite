"""Phase 2: CitationChecker 改造后的测试。"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy import delete

from app.services.citation_checker import CitationChecker
from app.models.client_question import ClientQuestion
from app.models.ai_index_result import AIIndexResult


async def _cleanup_test_data(db_session):
    """删除本文件测试用到的 client_id / URL 的残留数据，保证测试可重复运行。

    db_session fixture 不做事务回滚（已知隔离问题，见 conftest.py 注释与
    Phase 1 task6 的同类修复）。client_questions 插入非幂等（无唯一约束），
    ai_index_results 有 UNIQUE(url, model)，二次运行会冲突。这里在插入前统一
    清理本测试自己用到的数据，使测试单独运行与套件运行都通过。
    """
    await db_session.execute(
        delete(ClientQuestion).where(ClientQuestion.client_id == "client_a")
    )
    await db_session.execute(
        delete(AIIndexResult).where(
            AIIndexResult.url == "https://example.com/test"
        )
    )
    await db_session.commit()


@pytest.mark.asyncio
async def test_get_client_questions_returns_active_sorted(db_session):
    """_get_client_questions 返回 active 问题，按 sort_order 排序。"""
    await _cleanup_test_data(db_session)
    db_session.add(ClientQuestion(
        client_id="client_a",
        question="第三个问题",
        sort_order=3,
        status="active",
    ))
    db_session.add(ClientQuestion(
        client_id="client_a",
        question="第一个问题",
        sort_order=1,
        status="active",
    ))
    db_session.add(ClientQuestion(
        client_id="client_a",
        question="inactive 问题",
        sort_order=2,
        status="inactive",
    ))
    await db_session.commit()

    checker = CitationChecker(db_session)
    questions = await checker._get_client_questions("client_a")
    assert questions == ["第一个问题", "第三个问题"]


@pytest.mark.asyncio
async def test_get_client_questions_empty(db_session):
    """客户无 active 问题时返回空列表。"""
    checker = CitationChecker(db_session)
    questions = await checker._get_client_questions("no_such_client")
    assert questions == []


@pytest.mark.asyncio
async def test_get_indexed_models(db_session):
    """_get_indexed_models 返回 index_status='indexed' 的模型列表。"""
    await _cleanup_test_data(db_session)
    db_session.add(AIIndexResult(
        url="https://example.com/test",
        model="qwen",
        index_status="indexed",
    ))
    db_session.add(AIIndexResult(
        url="https://example.com/test",
        model="doubao",
        index_status="not_indexed",
    ))
    db_session.add(AIIndexResult(
        url="https://example.com/test",
        model="gemini",
        index_status="indexed",
    ))
    await db_session.commit()

    checker = CitationChecker(db_session)
    models = await checker._get_indexed_models("https://example.com/test")
    assert set(models) == {"qwen", "gemini"}


@pytest.mark.asyncio
async def test_get_indexed_models_empty(db_session):
    """URL 无已收录模型时返回空列表。"""
    checker = CitationChecker(db_session)
    models = await checker._get_indexed_models("https://example.com/no-record")
    assert models == []
