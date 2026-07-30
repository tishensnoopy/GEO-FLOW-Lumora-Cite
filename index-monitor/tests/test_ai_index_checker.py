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


@pytest.mark.asyncio
async def test_check_url_stores_indexed_result(db_session, monkeypatch):
    """check_url 调用 adapter.ask 后存储收录结果。"""
    # mock adapter
    class FakeAdapter:
        provider_id = "qwen"
        name = "千问"
        model_id = "qwen3.6-plus"
        def ask(self, question):
            # 返回类似 ModelAnswer 的对象（只需要 text 属性）
            class FakeAnswer:
                text = "该网页介绍了 XXX 公司的 YYY 产品，主要面向中小企业。"
                sources = []
                search_used = False
                error = None
            return FakeAnswer()

    monkeypatch.setattr(
        "app.services.ai_index_checker.AIIndexChecker._build_adapter",
        lambda self, model: FakeAdapter(),
    )

    checker = AIIndexChecker(db_session)
    result = await checker.check_url(
        "https://example.com/test-article", "qwen",
    )

    assert result["index_status"] == "indexed"
    assert "XXX 公司" in result["ai_response"]

    # 验证已写入数据库
    db_result = await db_session.execute(
        select(AIIndexResult).where(
            AIIndexResult.url == "https://example.com/test-article",
            AIIndexResult.model == "qwen",
        )
    )
    record = db_result.scalar_one_or_none()
    assert record is not None
    assert record.index_status == "indexed"


@pytest.mark.asyncio
async def test_check_url_stores_not_indexed_result(db_session, monkeypatch):
    """AI 回答'不了解'时存储 not_indexed。"""
    class FakeAdapter:
        provider_id = "doubao"
        name = "豆包"
        model_id = "doubao-seed-2-0-lite-260428"
        def ask(self, question):
            class FakeAnswer:
                text = "不了解"
                sources = []
                search_used = False
                error = None
            return FakeAnswer()

    monkeypatch.setattr(
        "app.services.ai_index_checker.AIIndexChecker._build_adapter",
        lambda self, model: FakeAdapter(),
    )

    checker = AIIndexChecker(db_session)
    result = await checker.check_url(
        "https://example.com/unknown-article", "doubao",
    )

    assert result["index_status"] == "not_indexed"


@pytest.mark.asyncio
async def test_check_url_api_failure_keeps_pending(db_session, monkeypatch):
    """adapter 抛异常时 index_status 保持 pending（可重试）。"""
    class FailingAdapter:
        provider_id = "qwen"
        name = "千问"
        model_id = "qwen3.6-plus"
        def ask(self, question):
            raise RuntimeError("API 超时")

    monkeypatch.setattr(
        "app.services.ai_index_checker.AIIndexChecker._build_adapter",
        lambda self, model: FailingAdapter(),
    )

    checker = AIIndexChecker(db_session)
    result = await checker.check_url(
        "https://example.com/fail-article", "qwen",
    )

    # API 失败时保持 pending（不是 not_indexed）
    assert result["index_status"] == "pending"
    assert "API 超时" in result["error"]
