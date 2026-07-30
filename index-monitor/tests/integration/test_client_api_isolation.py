# index-monitor/tests/integration/test_client_api_isolation.py
"""客户端只读 API 数据隔离集成测试（设计文档 Phase 3 任务 7）。

验证目标
========
1. GET  /api/v1/ai-index/overview —— 客户仅看到自己名下 URL 的收录概览
2. GET  /api/v1/citations/evidence —— 客户仅看到自己名下被引用的 Q&A 证据
   （hit_type != 'none'）
3. GET  /api/v1/stats —— 客户统计卡片（AI 收录数 / AI 提及数 / 提及率）

数据隔离
========
所有端点用 ``get_current_client_id`` 从 JWT 取 client_id，admin JWT 拒绝（403）。
仅返回该客户自己的数据（``_get_client_urls`` 取手动录入 + GEOFlow 分发匹配
ClientSite 的 URL 并集）。

适配说明
========
简报原稿用 ``starlette.testclient.TestClient``（同步），但在 pytest-asyncio strict
模式 + ``db_session`` 异步 fixture 下会触发事件循环冲突。本文件改用项目既有的
``client`` fixture（httpx.AsyncClient + ASGITransport，定义于 ``tests/conftest.py``），
请求改为 ``await client.get(...)``，断言不变。

参考 ``tests/integration/test_ai_index_api.py`` 的 ``_override_app_db`` autouse
fixture：pytest-asyncio strict 模式每测试独立事件循环，模块级
``app.core.database.engine`` 绑定 import 时的事件循环，跨测试复用会触发
"Future attached to a different loop"。本文件沿用同款 override。

数据清理
========
``db_session`` 不回滚，测试向 ``monitor.manual_distributions`` /
``monitor.ai_index_results`` / ``monitor.citation_results`` 插数据。本文件加
autouse fixture 在每个测试前后清理这三张表，避免跨测试 / 跨运行累积污染。
测试用 URL（a/b/evidence/stats.example.com）具备唯一性，断言用 ``>= 1`` 与
集合成员判定进一步隔离。
"""
import pytest
import pytest_asyncio


@pytest_asyncio.fixture(autouse=True)
async def _override_app_db():
    """为每个测试 override ``get_db`` 依赖，使用当前事件循环的全新 engine。

    pytest-asyncio strict 模式为每个测试创建独立事件循环。``app.core.database.engine``
    是模块级单例，其连接池里的 asyncpg 连接绑定到首次 import 时的事件循环，
    跨测试复用会触发 "Future attached to a different loop" /
    "another operation is in progress"。

    用 FastAPI ``app.dependency_overrides`` 把 ``get_db`` 替换为闭包，
    闭包内用本测试事件循环新建的 engine → session_factory → session。
    测试结束 dispose 这个临时 engine，不污染模块级 engine。
    """
    from app.main import app
    from app.core.database import get_db
    from app.core.config import settings
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async def _get_db_override():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _get_db_override
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest_asyncio.fixture(autouse=True)
async def _clean_client_api_tables(db_session):
    """每个测试前后清理本文件涉及的表，保证数据隔离。

    ``db_session`` fixture 仅做事件循环隔离（每测试新建 engine），不做数据回滚；
    本文件所有测试都向 ``manual_distributions`` / ``ai_index_results`` /
    ``citation_results`` 插数据，若不清理会跨测试 / 跨运行累积，导致
    UniqueConstraint(client_id, remote_url) 冲突或弱断言失真。

    autouse + 前后双删：前删清历史残留，后删清本测试产生的数据，避免污染后续测试。
    """
    from sqlalchemy import text

    await db_session.execute(text("DELETE FROM monitor.citation_results"))
    await db_session.execute(text("DELETE FROM monitor.ai_index_results"))
    await db_session.execute(text("DELETE FROM monitor.manual_distributions"))
    await db_session.commit()
    yield
    await db_session.execute(text("DELETE FROM monitor.citation_results"))
    await db_session.execute(text("DELETE FROM monitor.ai_index_results"))
    await db_session.execute(text("DELETE FROM monitor.manual_distributions"))
    await db_session.commit()


@pytest.mark.asyncio
async def test_client_ai_index_overview_only_own(
    db_session, client, client_a_headers, client_b_headers
):
    """客户只能看到自己的收录概览。"""
    from app.models.ai_index_result import AIIndexResult
    from app.models.manual_distribution import ManualDistribution

    # 客户 A 的文章
    db_session.add(ManualDistribution(
        client_id="DEMO001", remote_url="https://a.example.com/article",
        status="synced",
    ))
    db_session.add(AIIndexResult(
        url="https://a.example.com/article", model="qwen", index_status="indexed",
    ))
    # 客户 B 的文章
    db_session.add(ManualDistribution(
        client_id="DEMO002", remote_url="https://b.example.com/article",
        status="synced",
    ))
    db_session.add(AIIndexResult(
        url="https://b.example.com/article", model="qwen", index_status="indexed",
    ))
    await db_session.commit()

    # 客户 A 查看概览
    response_a = await client.get(
        "/api/v1/ai-index/overview", headers=client_a_headers
    )
    assert response_a.status_code == 200
    data_a = response_a.json()
    urls_a = {item["url"] for item in data_a["articles"]}
    assert "https://a.example.com/article" in urls_a
    assert "https://b.example.com/article" not in urls_a


@pytest.mark.asyncio
async def test_client_citation_evidence_only_cited(
    db_session, client, client_a_headers
):
    """客户引用证据仅返回被引用的（hit_type != 'none'）。"""
    from app.models.citation_result import CitationResult
    from app.models.manual_distribution import ManualDistribution

    db_session.add(ManualDistribution(
        client_id="DEMO001", remote_url="https://evidence.example.com/article",
        status="synced",
    ))
    db_session.add(CitationResult(
        url="https://evidence.example.com/article", model="qwen",
        question="问题1", answer="回答1", hit_type="domain", sources=[],
    ))
    db_session.add(CitationResult(
        url="https://evidence.example.com/article", model="qwen",
        question="问题2", answer="回答2", hit_type="none", sources=[],
    ))
    await db_session.commit()

    response = await client.get(
        "/api/v1/citations/evidence", headers=client_a_headers
    )
    assert response.status_code == 200
    data = response.json()
    # 仅返回 hit_type != 'none' 的记录
    assert all(item["hit_type"] != "none" for item in data)
    assert len(data) == 1
    assert data[0]["question"] == "问题1"


@pytest.mark.asyncio
async def test_client_stats(db_session, client, client_a_headers):
    """客户统计卡片数据。"""
    from app.models.ai_index_result import AIIndexResult
    from app.models.citation_result import CitationResult
    from app.models.manual_distribution import ManualDistribution

    db_session.add(ManualDistribution(
        client_id="DEMO001", remote_url="https://stats.example.com/article",
        status="synced",
    ))
    db_session.add(AIIndexResult(
        url="https://stats.example.com/article", model="qwen", index_status="indexed",
    ))
    db_session.add(CitationResult(
        url="https://stats.example.com/article", model="qwen",
        question="问题", answer="回答", hit_type="domain", sources=[],
    ))
    await db_session.commit()

    response = await client.get("/api/v1/stats", headers=client_a_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["ai_indexed_count"] >= 1
    assert data["ai_cited_count"] >= 1
    assert "ai_mention_rate" in data
