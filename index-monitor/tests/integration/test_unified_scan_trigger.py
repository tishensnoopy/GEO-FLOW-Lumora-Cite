# index-monitor/tests/integration/test_unified_scan_trigger.py
"""统一扫描触发 + 问题监测 API 集成测试（Phase 3 任务 4）。

验证目标：
1. POST /api/v1/admin/scan/trigger  —— 统一扫描触发入口
   - scan_type='index' / 'ai_index' / 'citation' / 'all' 均可触发
   - 无效 scan_type 返回 400
2. GET  /api/v1/admin/citation/results —— 查询问题监测结果（按 model 过滤）

适配说明
========
简报原稿用 ``starlette.testclient.TestClient``（同步），但在 pytest-asyncio strict
模式 + ``db_session`` 异步 fixture 下会触发事件循环冲突。本文件改用项目既有的
``client`` fixture（httpx.AsyncClient + ASGITransport，定义于 ``tests/conftest.py``），
请求改为 ``await client.get/post(...)``，断言不变。

参考 ``tests/integration/test_ai_index_api.py`` 的 ``_override_app_db`` autouse
fixture：pytest-asyncio strict 模式每测试独立事件循环，模块级
``app.core.database.engine`` 绑定 import 时的事件循环，跨测试复用会触发
"Future attached to a different loop"。

数据隔离
========
``db_session`` 不回滚，测试向 ``monitor.citation_results`` 插数据。本文件加
autouse fixture 在每个测试前后清理该表，避免污染其他测试 / 多次运行累积。
测试用 URL（example.com/citation-test）具备唯一性，断言用 ``>= 1`` 进一步隔离。
"""
import pytest
import pytest_asyncio


@pytest_asyncio.fixture(autouse=True)
async def _clean_citation_results(db_session):
    """每个测试前后清理 ``monitor.citation_results`` 表，保证数据隔离。

    ``db_session`` fixture 仅做事件循环隔离（每测试新建 engine），不做数据回滚；
    本文件 ``test_citation_results_query`` 向 ``citation_results`` 插数据，若不清理
    会跨测试 / 跨运行累积，导致 ``total >= 1`` 这类弱断言无法区分"本次插入"
    还是"历史残留"。

    autouse + 前后双删：前删清历史残留，后删清本测试产生的数据，避免污染后续测试。
    """
    from sqlalchemy import text

    await db_session.execute(text("DELETE FROM monitor.citation_results"))
    await db_session.commit()
    yield
    await db_session.execute(text("DELETE FROM monitor.citation_results"))
    await db_session.commit()


@pytest.mark.asyncio
async def test_unified_scan_trigger_index(client, admin_auth_headers):
    """统一扫描触发 index 类型。"""
    from unittest.mock import AsyncMock, patch

    with patch(
        "app.services.index_checker.IndexChecker.get_pending_urls",
        new_callable=AsyncMock,
        return_value=[],
    ):
        response = await client.post(
            "/api/v1/admin/scan/trigger",
            json={"scan_type": "index"},
            headers=admin_auth_headers,
        )
    assert response.status_code == 200
    data = response.json()
    assert "task_ids" in data


@pytest.mark.asyncio
async def test_unified_scan_trigger_ai_index(client, admin_auth_headers):
    """统一扫描触发 ai_index 类型。"""
    from unittest.mock import AsyncMock, patch

    with patch(
        "app.services.ai_index_checker.AIIndexChecker.get_pending_urls",
        new_callable=AsyncMock,
        return_value=[],
    ):
        response = await client.post(
            "/api/v1/admin/scan/trigger",
            json={"scan_type": "ai_index"},
            headers=admin_auth_headers,
        )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_unified_scan_trigger_citation(client, admin_auth_headers):
    """统一扫描触发 citation 类型。"""
    from unittest.mock import AsyncMock, patch

    with patch(
        "app.services.citation_checker.CitationChecker.get_pending_urls",
        new_callable=AsyncMock,
        return_value=[],
    ):
        response = await client.post(
            "/api/v1/admin/scan/trigger",
            json={"scan_type": "citation"},
            headers=admin_auth_headers,
        )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_unified_scan_trigger_all(client, admin_auth_headers):
    """统一扫描触发 all 类型（顺序执行三种）。"""
    from unittest.mock import AsyncMock, patch

    with patch(
        "app.services.index_checker.IndexChecker.get_pending_urls",
        new_callable=AsyncMock,
        return_value=[],
    ), patch(
        "app.services.ai_index_checker.AIIndexChecker.get_pending_urls",
        new_callable=AsyncMock,
        return_value=[],
    ), patch(
        "app.services.citation_checker.CitationChecker.get_pending_urls",
        new_callable=AsyncMock,
        return_value=[],
    ):
        response = await client.post(
            "/api/v1/admin/scan/trigger",
            json={"scan_type": "all"},
            headers=admin_auth_headers,
        )
    assert response.status_code == 200
    data = response.json()
    assert "task_ids" in data


@pytest.mark.asyncio
async def test_unified_scan_invalid_type(client, admin_auth_headers):
    """无效 scan_type 返回 400。"""
    response = await client.post(
        "/api/v1/admin/scan/trigger",
        json={"scan_type": "invalid"},
        headers=admin_auth_headers,
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_unified_scan_all_executes_sequentially(client, admin_auth_headers):
    """all 类型顺序执行三阶段（C1 修复验证，I8 新增测试）。

    设计约束：scan_type='all' 时按顺序执行 index → ai_index → citation，
    确保 citation 阶段能看到 ai_index 阶段本次新写入的 indexed 记录。

    RED→GREEN 验证：
    - 修复前（并发 create_task 三阶段）：max_concurrent == 3 → 断言失败
    - 修复后（单一 background task 顺序 await）：max_concurrent == 1 → 断言通过
    """
    import asyncio
    from unittest.mock import AsyncMock, patch

    # 记录调用顺序和并发度
    call_log: list[tuple[str, str]] = []
    active = {"count": 0}
    max_concurrent = {"value": 0}

    async def mock_background(scan_type: str, task_id: str) -> None:
        call_log.append((scan_type, "start"))
        active["count"] += 1
        max_concurrent["value"] = max(max_concurrent["value"], active["count"])
        # 让事件循环有机会调度其他 task（若并发，此时其他阶段会进入）
        await asyncio.sleep(0.05)
        active["count"] -= 1
        call_log.append((scan_type, "end"))

    with patch(
        "app.services.index_checker.IndexChecker.get_pending_urls",
        new_callable=AsyncMock,
        return_value=[("https://example.com/seq-test", "DEMO001")],
    ), patch(
        "app.services.ai_index_checker.AIIndexChecker.get_pending_urls",
        new_callable=AsyncMock,
        return_value=[("https://example.com/seq-test", "DEMO001", "deepseek")],
    ), patch(
        "app.services.citation_checker.CitationChecker.get_pending_urls",
        new_callable=AsyncMock,
        return_value=[("https://example.com/seq-test", "DEMO001")],
    ), patch(
        "app.api.admin_routes._run_unified_scan_background",
        new=mock_background,
    ):
        response = await client.post(
            "/api/v1/admin/scan/trigger",
            json={"scan_type": "all"},
            headers=admin_auth_headers,
        )
        # 等待 background task 完成（三阶段 × 0.05s + 余量）
        await asyncio.sleep(0.3)

    assert response.status_code == 200
    data = response.json()
    # 三个阶段都创建了 task_id（pending 非空）
    assert data["task_ids"]["index"] is not None, "index 阶段应有 task_id"
    assert data["task_ids"]["ai_index"] is not None, "ai_index 阶段应有 task_id"
    assert data["task_ids"]["citation"] is not None, "citation 阶段应有 task_id"

    # 核心断言：任一时刻最多 1 个阶段在执行（顺序，非并发）
    assert max_concurrent["value"] == 1, (
        f"all 类型应顺序执行（max_concurrent=1），"
        f"实际 max_concurrent={max_concurrent['value']}，call_log={call_log}"
    )
    # 验证执行顺序：index → ai_index → citation
    start_order = [scan_type for scan_type, event in call_log if event == "start"]
    assert start_order == ["index", "ai_index", "citation"], (
        f"阶段执行顺序应为 index → ai_index → citation，实际: {start_order}"
    )


@pytest.mark.asyncio
async def test_citation_results_query(client, db_session, admin_auth_headers):
    """admin 查询问题监测结果。"""
    from app.models.citation_result import CitationResult
    db_session.add(CitationResult(
        url="https://example.com/citation-test",
        model="qwen",
        question="测试问题",
        answer="测试回答",
        hit_type="domain",
        sources=[],
    ))
    await db_session.commit()

    response = await client.get(
        "/api/v1/admin/citation/results?model=qwen",
        headers=admin_auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] >= 1
