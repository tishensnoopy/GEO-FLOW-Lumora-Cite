# index-monitor/tests/integration/test_auto_pipeline_e2e.py
"""自动联动 E2E 测试：手动添加文章 → 触发联动 + batch-scan 扩展 ai_index/all。

Phase 3 任务 6 集成测试。验证目标：
1. POST /api/v1/distributions（手动添加文章）成功后触发 auto_pipeline.trigger_for_url
2. POST /api/v1/admin/distributions/batch-scan 接受 scan_type=ai_index
   （原仅接受 index/citation/both，Phase 3 扩展为 index/citation/both/ai_index/all）

适配说明
========
简报原稿用 ``starlette.testclient.TestClient``（同步），在 pytest-asyncio strict
模式 + ``db_session`` 异步 fixture 下会触发事件循环冲突。本文件改用项目既有
``client`` fixture（httpx.AsyncClient + ASGITransport，定义于 ``tests/conftest.py``），
请求改为 ``await client.post(...)``，断言不变。

参考 ``tests/integration/test_unified_scan_trigger.py`` 的 ``_override_app_db``
autouse fixture：pytest-asyncio strict 模式每测试独立事件循环，模块级
``app.core.database.engine`` 绑定 import 时的事件循环，跨测试复用会触发
"Future attached to a different loop"。

数据隔离
========
``db_session`` 不回滚，测试向 ``monitor.manual_distributions`` / ``monitor.index_results``
插数据。本文件加 autouse fixture 在每个测试前后清理相关测试数据，避免污染其他测试 /
多次运行累积。测试用 URL（example.com/auto-pipeline-test）具备唯一性。

GEOFlow mock 表
================
``DistributionQueryService.create_manual_distribution`` 会跨 schema JOIN
``public.article_distributions`` 检查重复。本地 ``geo-postgres-local`` 容器的
``public`` schema 无 GEOFlow 真实表，缺表会触发 ``UndefinedTableError`` 中止事务
（service 的 except 不 rollback → 后续 INSERT 失败）。
参考 ``test_manual_distribution_endpoint.py`` 的 ``geoflow_mock_tables`` fixture，
本文件复制同款 module 级 sync fixture 创建 mock 表，结束 DROP 清理。
"""
import pytest
import pytest_asyncio


# --------------------------------------------------------------------------- #
# Mock 表 DDL：与 GEOFlow migration 字段对齐（复用自 test_manual_distribution_endpoint.py） #
# --------------------------------------------------------------------------- #
# 注意：``public.articles`` 在本地容器中是真实 GEOFlow 表（带 article_images 等
# 依赖），不能 DROP。本测试只需 ``article_distributions``（不存在于本地容器），
# 故只创建/删除这一张表，避免破坏真实 schema。
_CREATE_ARTICLE_DISTRIBUTIONS_SQL = """
CREATE TABLE IF NOT EXISTS public.article_distributions (
    id BIGSERIAL PRIMARY KEY,
    article_id BIGINT NOT NULL,
    distribution_channel_id BIGINT NOT NULL,
    action VARCHAR(30) DEFAULT 'publish',
    status VARCHAR(30) DEFAULT 'queued',
    remote_id VARCHAR(120),
    remote_url VARCHAR(500),
    remote_meta JSON,
    idempotency_key VARCHAR(120) UNIQUE,
    attempt_count INTEGER DEFAULT 0,
    next_retry_at TIMESTAMPTZ,
    last_attempt_at TIMESTAMPTZ,
    last_error_message TEXT,
    payload_hash VARCHAR(64),
    created_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ
)
"""

_DROP_ARTICLE_DISTRIBUTIONS_SQL = "DROP TABLE IF EXISTS public.article_distributions"


@pytest.fixture(scope="module", autouse=True)
def geoflow_mock_tables():
    """Module 级 sync fixture：在 public schema 创建 GEOFlow mock 表，结束 DROP。

    只创建 ``article_distributions``（本地容器缺此表）。``articles`` 已作为真实
    GEOFlow 表存在（带依赖），不创建也不删除，避免破坏 schema。

    用 ``psycopg2`` 同步连接（独立于 asyncio 事件循环），避免 strict 模式下
    模块级 async fixture 与 per-test 事件循环冲突。DDL 用 ``autocommit`` 提交，
    不会被 per-test 事务回滚影响。
    """
    import psycopg2
    from app.core.config import settings

    conn = psycopg2.connect(
        host=settings.POSTGRES_HOST,
        port=settings.POSTGRES_PORT,
        dbname=settings.POSTGRES_DB,
        user=settings.POSTGRES_USER,
        password=settings.POSTGRES_PASSWORD,
    )
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(_CREATE_ARTICLE_DISTRIBUTIONS_SQL)
        yield conn
    finally:
        with conn.cursor() as cur:
            cur.execute(_DROP_ARTICLE_DISTRIBUTIONS_SQL)
        conn.close()


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
    from sqlalchemy.ext.asyncio import (
        create_async_engine, async_sessionmaker, AsyncSession,
    )

    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False,
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
async def _clean_auto_pipelineTestData(db_session):
    """每个测试前后清理本文件涉及的测试数据，保证数据隔离。

    清理范围：
    - ``monitor.manual_distributions`` 中测试 URL 的记录
    - ``monitor.index_results`` 中测试 URL 的记录

    ``db_session`` fixture 仅做事件循环隔离（每测试新建 engine），不做数据回滚；
    若不清理会跨测试 / 跨运行累积，导致重复录入触发 409 "URL 已存在"。
    """
    from sqlalchemy import text

    test_url = "https://example.com/auto-pipeline-test"
    await db_session.execute(
        text("DELETE FROM monitor.manual_distributions WHERE remote_url = :u"),
        {"u": test_url},
    )
    await db_session.execute(
        text("DELETE FROM monitor.index_results WHERE url = :u"),
        {"u": test_url},
    )
    await db_session.commit()
    yield
    await db_session.execute(
        text("DELETE FROM monitor.manual_distributions WHERE remote_url = :u"),
        {"u": test_url},
    )
    await db_session.execute(
        text("DELETE FROM monitor.index_results WHERE url = :u"),
        {"u": test_url},
    )
    await db_session.commit()


@pytest.mark.asyncio
async def test_manual_distribution_triggers_auto_pipeline(
    client, admin_auth_headers,
):
    """手动添加文章后触发 auto_pipeline。

    mock auto_pipeline.trigger_for_url 避免实际调用 AI。
    断言：HTTP 201 + auto_pipeline 被调用（asyncio.create_task 异步，
    用 await asyncio.sleep 让事件循环调度后验证 mock 被调用）。
    """
    import asyncio
    from unittest.mock import AsyncMock, patch

    # mock auto_pipeline 避免实际调用 AI
    with patch(
        "app.services.auto_pipeline.trigger_for_url",
        new_callable=AsyncMock,
    ) as mock_trigger:
        response = await client.post(
            "/api/v1/distributions",
            json={
                "remote_url": "https://example.com/auto-pipeline-test",
                "client_id": "DEMO001",
                "title": "测试标题",
            },
            headers=admin_auth_headers,
        )

    assert response.status_code == 201, (
        f"unexpected status: {response.status_code} body: {response.text}"
    )

    # auto_pipeline 被 asyncio.create_task 调度，让事件循环跑一下让 task 启动
    # trigger_for_url 内部用独立 session，不依赖请求 db，mock 后立即返回
    await asyncio.sleep(0.05)
    assert mock_trigger.called, "auto_pipeline.trigger_for_url 未被触发"
    # 校验调用参数：url + client_id
    call_args = mock_trigger.call_args
    assert call_args.args[0] == "https://example.com/auto-pipeline-test"
    assert call_args.args[1] == "DEMO001"


@pytest.mark.asyncio
async def test_batch_scan_supports_ai_index(client, admin_auth_headers):
    """batch-scan 支持 ai_index 类型。

    修复前：scan_type=ai_index → 400 "scan_type 必须是 index/citation/both"
    修复后：scan_type=ai_index 被接受（distribution_ids 为空时仍 400，
    但 detail 不含"必须是"）。

    断言：响应状态码不是 400，或者是 400 但 detail 不含"必须是"
    （即 ai_index 已被 scan_type 校验接受，错误只能来自 distribution_ids 空）。
    """
    from unittest.mock import AsyncMock, patch

    # mock get_pending_urls 返回空（避免触发实际 AI 检测）
    with patch(
        "app.services.ai_index_checker.AIIndexChecker.get_pending_urls",
        new_callable=AsyncMock,
        return_value=[],
    ):
        response = await client.post(
            "/api/v1/admin/distributions/batch-scan",
            json={"distribution_ids": [], "scan_type": "ai_index"},
            headers=admin_auth_headers,
        )
    # distribution_ids 为空时返回 400，或无 pending 时返回成功
    # 这里验证 scan_type=ai_index 不再返回 400 "必须是 index/citation/both"
    assert (
        response.status_code != 400
        or "必须是" not in response.json().get("detail", "")
    ), (
        f"scan_type=ai_index 应被接受，但被拒绝: {response.status_code} "
        f"{response.text}"
    )
