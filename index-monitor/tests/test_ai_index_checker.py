# index-monitor/tests/test_ai_index_checker.py
"""AIIndexChecker 单元测试。"""
import pytest
from sqlalchemy import select

from app.models.ai_index_result import AIIndexResult
from app.models.manual_distribution import ManualDistribution
from app.models.client_question import ClientQuestion
from app.services.ai_index_checker import AIIndexChecker


@pytest.mark.asyncio
async def test_get_pending_urls_returns_unchecked_combinations(db_session, monkeypatch):
    """get_pending_urls 返回 synced URL × 已配置模型 中 ai_index_results 无记录的组合。"""
    # 1. 插入一条手动分发记录
    db_session.add(ManualDistribution(
        client_id="test_client",
        remote_url="https://example.com/article-1",
        status="synced",
    ))
    await db_session.commit()

    # 2. mock 已配置模型列表
    monkeypatch.setattr(
        "app.services.ai_index_checker.AIIndexChecker._get_configured_models",
        staticmethod(lambda: ["qwen", "doubao"]),
    )

    # 3. 调用 get_pending_urls
    checker = AIIndexChecker(db_session)
    pending = await checker.get_pending_urls()

    # 4. 应返回 2 个组合：URL × qwen, URL × doubao
    assert len(pending) == 2
    urls_models = {(url, model) for url, _, model in pending}
    assert ("https://example.com/article-1", "qwen") in urls_models
    assert ("https://example.com/article-1", "doubao") in urls_models


@pytest.mark.asyncio
async def test_get_pending_urls_excludes_checked(db_session, monkeypatch):
    """已有 ai_index_results 记录的组合不返回。"""
    db_session.add(ManualDistribution(
        client_id="test_client",
        remote_url="https://example.com/article-2",
        status="synced",
    ))
    # 已检测过 qwen → indexed
    db_session.add(AIIndexResult(
        url="https://example.com/article-2",
        model="qwen",
        index_status="indexed",
        ai_response="该网页介绍了...",
    ))
    await db_session.commit()

    monkeypatch.setattr(
        "app.services.ai_index_checker.AIIndexChecker._get_configured_models",
        staticmethod(lambda: ["qwen", "doubao"]),
    )

    checker = AIIndexChecker(db_session)
    pending = await checker.get_pending_urls()

    # qwen 已检测过，只返回 doubao
    assert len(pending) == 1
    assert pending[0][2] == "doubao"
