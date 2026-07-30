# index-monitor/tests/test_ai_index_checker.py
"""AIIndexChecker 单元测试。"""
import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.ai_index_result import AIIndexResult
from app.models.manual_distribution import ManualDistribution
from app.models.client_question import ClientQuestion
from app.services.ai_index_checker import AIIndexChecker


def _patch_async_session_to_test_loop(monkeypatch):
    """让 check_all_pending 内部的 ``async_session`` 绑定到当前测试的事件循环。

    背景：pytest-asyncio strict 模式为每个测试创建独立事件循环；
    ``app.core.database.async_session`` 是模块级 ``async_sessionmaker``，
    首次使用时绑定到首个测试的事件循环，后续测试在新循环上复用会触发
    "Future attached to a different loop"（conftest.py 注释已记录此问题）。

    check_all_pending 通过 ``async_session()`` 为每个并发任务创建独立 session
    （AsyncSession 并发不安全）。这里就地构造绑定到当前循环的 engine +
    sessionmaker 替换之，使每个 ``_check_one`` 仍拿到独立 session（保留并发隔离），
    同时跨用例不再跨循环。不影响实现代码与断言。
    """
    from app.core.config import settings

    url = (
        f"postgresql+asyncpg://{settings.POSTGRES_USER}:{settings.POSTGRES_PASSWORD}"
        f"@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}"
    )
    engine = create_async_engine(url, echo=False)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr("app.core.database.async_session", factory)


async def _cleanup_example_urls(db_session):
    """删除所有 example.com 测试 URL 的 ManualDistribution 与 AIIndexResult 残留。

    db_session fixture 不做事务回滚（已知隔离问题，见 conftest.py 注释与任务 6 报告）。
    check_all_pending 通过 get_pending_urls 查询全部 synced 的 manual_distributions，
    若 DB 残留其他用例写入的 example.com 记录，会使 total 偏离预期；同时
    ManualDistribution 插入非幂等（UNIQUE(client_id, remote_url)），二次运行会冲突。
    这里在插入前统一清理 example.com 测试数据，使测试可重复运行且 total 可预期。
    """
    await db_session.execute(
        delete(AIIndexResult).where(AIIndexResult.url.like("https://example.com/%"))
    )
    await db_session.execute(
        delete(ManualDistribution).where(
            ManualDistribution.remote_url.like("https://example.com/%")
        )
    )
    await db_session.commit()


@pytest.mark.asyncio
async def test_get_pending_urls_returns_unchecked_combinations(db_session, monkeypatch):
    """get_pending_urls 返回 synced URL × 已配置模型 中 ai_index_results 无记录的组合。"""
    # 1. 插入一条手动分发记录
    await _cleanup_example_urls(db_session)
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
    await _cleanup_example_urls(db_session)
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


@pytest.mark.asyncio
async def test_check_all_pending_concurrent(db_session, monkeypatch):
    """check_all_pending 并发检测多个 URL×模型组合，返回汇总。"""
    # 2 个 URL × 1 个模型 = 2 个组合
    await _cleanup_example_urls(db_session)
    db_session.add(ManualDistribution(
        client_id="test_client",
        remote_url="https://example.com/batch-1",
        status="synced",
    ))
    db_session.add(ManualDistribution(
        client_id="test_client",
        remote_url="https://example.com/batch-2",
        status="synced",
    ))
    await db_session.commit()

    # mock 模型列表只返回 qwen
    monkeypatch.setattr(
        "app.services.ai_index_checker.AIIndexChecker._get_configured_models",
        staticmethod(lambda: ["qwen"]),
    )

    # mock check_url 不实际调 AI，直接存 indexed
    async def fake_check_url(self, url, model, *, task_id=None, progress=None):
        await self._store_result(url, model, "indexed", "mock response")
        return {"url": url, "model": model, "index_status": "indexed", "error": None}

    monkeypatch.setattr(AIIndexChecker, "check_url", fake_check_url)
    _patch_async_session_to_test_loop(monkeypatch)

    checker = AIIndexChecker(db_session)
    result = await checker.check_all_pending(concurrency=2)

    assert result["total"] == 2
    assert result["success"] == 2
    assert result["failed"] == 0
    assert len(result["failures"]) == 0


@pytest.mark.asyncio
async def test_check_all_pending_with_failure(db_session, monkeypatch):
    """部分组合失败时不影响其他，记入 failures。"""
    await _cleanup_example_urls(db_session)
    db_session.add(ManualDistribution(
        client_id="test_client",
        remote_url="https://example.com/ok-url",
        status="synced",
    ))
    db_session.add(ManualDistribution(
        client_id="test_client",
        remote_url="https://example.com/fail-url",
        status="synced",
    ))
    await db_session.commit()

    monkeypatch.setattr(
        "app.services.ai_index_checker.AIIndexChecker._get_configured_models",
        staticmethod(lambda: ["qwen"]),
    )

    call_count = [0]
    async def fake_check_url(self, url, model, *, task_id=None, progress=None):
        call_count[0] += 1
        if "fail-url" in url:
            raise RuntimeError("模拟 API 失败")
        await self._store_result(url, model, "indexed", "ok")
        return {"url": url, "model": model, "index_status": "indexed", "error": None}

    monkeypatch.setattr(AIIndexChecker, "check_url", fake_check_url)
    _patch_async_session_to_test_loop(monkeypatch)

    checker = AIIndexChecker(db_session)
    result = await checker.check_all_pending(concurrency=2)

    assert result["total"] == 2
    assert result["success"] == 1
    assert result["failed"] == 1
    assert len(result["failures"]) == 1
    assert "fail-url" in result["failures"][0]["url"]
