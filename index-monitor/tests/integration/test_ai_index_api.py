# index-monitor/tests/integration/test_ai_index_api.py
"""AI 收录检测 API 集成测试。

验证目标（设计文档 Phase 3 任务 3）：
1. GET  /api/v1/admin/ai-index/results  —— 按模型过滤查询收录结果
2. GET  /api/v1/admin/ai-index/stats    —— 收录统计（总体 + 按模型维度）
3. POST /api/v1/admin/ai-index/scan     —— 批量增量 AI 收录检测（异步）

适配说明
========
简报原稿用 ``starlette.testclient.TestClient``（同步），但在 pytest-asyncio strict
模式 + ``db_session`` 异步 fixture 下会触发事件循环冲突。本文件改用项目既有的
``client`` fixture（httpx.AsyncClient + ASGITransport，定义于 ``tests/conftest.py``），
请求改为 ``await client.get/post(...)``，断言不变。

参考 ``tests/integration/test_admin_endpoints.py`` 的 ``_override_app_db`` autouse
fixture：pytest-asyncio strict 模式每测试独立事件循环，模块级
``app.core.database.engine`` 绑定 import 时的事件循环，跨测试复用会触发
"Future attached to a different loop"。本文件沿用同款 override。

数据隔离
========
``db_session`` 不回滚，测试向 ``monitor.ai_index_results`` 插数据。本文件加
autouse fixture 在每个测试前后清理该表，避免污染其他测试 / 多次运行累积。
测试用 URL（example.com/test、example.com/stats1 等）具备唯一性，断言用
``>= 1`` 与 ``any(...)`` 进一步隔离。
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
async def _clean_ai_index_results(db_session):
    """每个测试前后清理 ``monitor.ai_index_results`` 表，保证数据隔离。

    ``db_session`` fixture 仅做事件循环隔离（每测试新建 engine），不做数据回滚；
    本文件所有测试都向 ``ai_index_results`` 插数据，若不清理会跨测试 / 跨运行
    累积，导致 ``total >= 1`` 这类弱断言无法区分"本次插入"还是"历史残留"。

    autouse + 前后双删：前删清历史残留，后删清本测试产生的数据，避免污染后续测试。
    """
    from sqlalchemy import text

    await db_session.execute(text("DELETE FROM monitor.ai_index_results"))
    await db_session.commit()
    yield
    await db_session.execute(text("DELETE FROM monitor.ai_index_results"))
    await db_session.commit()


@pytest.mark.asyncio
async def test_ai_index_results_query(client, db_session, admin_auth_headers):
    """admin 查询收录结果。"""
    from app.models.ai_index_result import AIIndexResult
    db_session.add(AIIndexResult(
        url="https://example.com/test",
        model="qwen",
        index_status="indexed",
        ai_response="这是测试内容",
    ))
    await db_session.commit()

    response = await client.get(
        "/api/v1/admin/ai-index/results?model=qwen",
        headers=admin_auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] >= 1
    assert any(item["url"] == "https://example.com/test" for item in data["items"])


@pytest.mark.asyncio
async def test_ai_index_stats(client, db_session, admin_auth_headers):
    """admin 查询收录统计。"""
    from app.models.ai_index_result import AIIndexResult
    db_session.add(AIIndexResult(
        url="https://example.com/stats1", model="qwen", index_status="indexed",
    ))
    db_session.add(AIIndexResult(
        url="https://example.com/stats2", model="qwen", index_status="not_indexed",
    ))
    await db_session.commit()

    response = await client.get(
        "/api/v1/admin/ai-index/stats",
        headers=admin_auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["indexed"] >= 1
    assert data["not_indexed"] >= 1
    assert "by_model" in data


@pytest.mark.asyncio
async def test_ai_index_scan_trigger(client, admin_auth_headers):
    """admin 触发批量 AI 收录检测。"""
    from unittest.mock import AsyncMock, patch

    # mock get_pending_urls 返回空（避免实际调用 AI）
    with patch(
        "app.services.ai_index_checker.AIIndexChecker.get_pending_urls",
        new_callable=AsyncMock,
        return_value=[],
    ):
        response = await client.post(
            "/api/v1/admin/ai-index/scan",
            headers=admin_auth_headers,
        )
    assert response.status_code == 200
    data = response.json()
    assert "task_id" in data or "message" in data
