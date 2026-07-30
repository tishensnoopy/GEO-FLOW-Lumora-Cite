# index-monitor/tests/unit/test_check_all_pending_concurrent.py
"""check_all_pending 并发化测试（阶段 3 - ②）。

验证目标：
1. check_all_pending 并发执行 check_url，并发度受 semaphore 限制
2. 单条失败不影响其他 URL（failures 记录，success 继续）
3. 并发度可配（concurrency 参数）

原串行实现 N 个 URL 耗时 = N × 单条耗时；并发后 ≈ N/并发度 × 单条耗时。

Bugfix 适配：check_all_pending 现在每个 _check_one 创建独立 AsyncSession +
独立 CitationChecker（修复 AsyncSession 并发不安全）。测试通过 monkeypatch
类方法 CitationChecker.check_url + async_session 工厂，让所有新实例都用 fake。
"""
import asyncio
from contextlib import asynccontextmanager
from unittest.mock import MagicMock

import pytest

from app.services.citation_checker import CitationChecker


class _FakeSessionCM:
    """模拟 async_session() 返回的 async context manager。"""

    async def __aenter__(self):
        return MagicMock()

    async def __aexit__(self, *exc):
        return False


@pytest.fixture
def _patch_session(monkeypatch):
    """让 check_all_pending 内的 async_session() 返回 mock，不连真实 DB。"""
    import app.core.database as db_mod
    monkeypatch.setattr(db_mod, "async_session", lambda: _FakeSessionCM())


def _make_checker_with_pending(pending):
    """构造 CitationChecker，get_pending_urls 返回 pending。"""
    checker = CitationChecker(db=MagicMock())

    async def fake_get_pending():
        return pending
    checker.get_pending_urls = fake_get_pending
    return checker


@pytest.mark.asyncio
async def test_check_all_pending_runs_concurrently(_patch_session, monkeypatch):
    """6 个 URL × concurrency=3：最大并发数应 ≤ 3，且比串行快。"""
    pending = [(f"https://example.com/{i}", f"client-{i}") for i in range(6)]
    checker = _make_checker_with_pending(pending)

    current = 0
    max_concurrent = 0

    async def fake_check_url(self, url, client_id, *, task_id=None, progress=None):
        nonlocal current, max_concurrent
        current += 1
        max_concurrent = max(max_concurrent, current)
        await asyncio.sleep(0.05)  # 模拟检测耗时
        current -= 1

    # 类方法级别 patch：所有新 CitationChecker 实例都用 fake
    monkeypatch.setattr(CitationChecker, "check_url", fake_check_url)

    summary = await checker.check_all_pending(concurrency=3)

    assert summary["total"] == 6
    assert summary["success"] == 6
    assert summary["failed"] == 0
    # 关键断言：并发度被 semaphore 限制在 3
    assert max_concurrent <= 3, f"最大并发数 {max_concurrent} 应 ≤ 3"
    # 且确实并发了（>1），否则说明退化为串行
    assert max_concurrent >= 2, f"最大并发数 {max_concurrent} 应 ≥ 2（证明并发）"


@pytest.mark.asyncio
async def test_check_all_pending_concurrency_1_is_serial(_patch_session, monkeypatch):
    """concurrency=1 应退化为串行（最大并发数 = 1）。"""
    pending = [(f"https://example.com/{i}", f"client-{i}") for i in range(4)]
    checker = _make_checker_with_pending(pending)

    current = 0
    max_concurrent = 0

    async def fake_check_url(self, url, client_id, *, task_id=None, progress=None):
        nonlocal current, max_concurrent
        current += 1
        max_concurrent = max(max_concurrent, current)
        await asyncio.sleep(0.02)
        current -= 1

    monkeypatch.setattr(CitationChecker, "check_url", fake_check_url)

    await checker.check_all_pending(concurrency=1)
    assert max_concurrent == 1, "concurrency=1 应串行"


@pytest.mark.asyncio
async def test_check_all_pending_single_failure_doesnt_block_others(_patch_session, monkeypatch):
    """单条失败不影响其他 URL，failures 记录失败项。"""
    pending = [(f"https://example.com/{i}", f"client-{i}") for i in range(4)]
    checker = _make_checker_with_pending(pending)

    async def fake_check_url(self, url, client_id, *, task_id=None, progress=None):
        if "example.com/1" in url:
            raise ValueError("[2/5 目的推断] 模拟失败")
        await asyncio.sleep(0.01)

    monkeypatch.setattr(CitationChecker, "check_url", fake_check_url)

    summary = await checker.check_all_pending(concurrency=3)

    assert summary["total"] == 4
    assert summary["success"] == 3
    assert summary["failed"] == 1
    assert len(summary["failures"]) == 1
    assert summary["failures"][0]["url"] == "https://example.com/1"
    assert summary["failures"][0]["stage"] == "2/5 目的推断"


@pytest.mark.asyncio
async def test_check_all_pending_default_concurrency(_patch_session, monkeypatch):
    """不传 concurrency 时用默认值（应并发执行，不串行）。"""
    pending = [(f"https://example.com/{i}", f"client-{i}") for i in range(5)]
    checker = _make_checker_with_pending(pending)

    current = 0
    max_concurrent = 0

    async def fake_check_url(self, url, client_id, *, task_id=None, progress=None):
        nonlocal current, max_concurrent
        current += 1
        max_concurrent = max(max_concurrent, current)
        await asyncio.sleep(0.03)
        current -= 1

    monkeypatch.setattr(CitationChecker, "check_url", fake_check_url)

    await checker.check_all_pending()
    assert max_concurrent >= 2, "默认应并发执行"


@pytest.mark.asyncio
async def test_check_all_pending_passes_task_id_to_all(_patch_session, monkeypatch):
    """并发执行时 task_id 应透传给每个 check_url。"""
    pending = [(f"https://example.com/{i}", f"client-{i}") for i in range(4)]
    checker = _make_checker_with_pending(pending)

    received_task_ids = []

    async def fake_check_url(self, url, client_id, *, task_id=None, progress=None):
        received_task_ids.append(task_id)
        await asyncio.sleep(0.01)

    monkeypatch.setattr(CitationChecker, "check_url", fake_check_url)

    await checker.check_all_pending(task_id="concurrent-task", concurrency=2)

    assert all(tid == "concurrent-task" for tid in received_task_ids)
    assert len(received_task_ids) == 4
