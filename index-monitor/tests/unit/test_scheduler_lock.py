# index-monitor/tests/unit/test_scheduler_lock.py
"""scheduler advisory lock + task_manager 集成测试（阶段 3 - ② / 阶段 4 - ①）。

验证目标：
1. 拿不到锁 → warning 跳过，不创建任务、不调用 checker
2. 拿到锁 + 无 pending → 释放锁，不创建任务
3. 拿到锁 + 有 pending → 创建任务、透传 task_id 执行 check_all_pending、
   complete_task，并在 finally 释放锁
4. check_all_pending 抛异常时仍释放锁（finally 兜底）

用 monkeypatch 替换 async_session / acquire_scan_lock / release_scan_lock /
scan_task_manager / CitationChecker，避免真实 DB 与真实检测。
"""
from unittest.mock import MagicMock

import pytest


class _FakeCM:
    """模拟 async_session() 返回的 async context manager，yield 固定 db。"""
    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, *exc):
        return False


class _FakeCitationChecker:
    """模拟 CitationChecker，可控 pending 与 check_all_pending 行为。"""
    def __init__(self, db, *, pending=None, raise_exc=None):
        self.db = db
        self._pending = pending or []
        self._raise_exc = raise_exc
        self.check_all_pending_called_with = None

    async def get_pending_urls(self):
        return self._pending

    async def check_all_pending(self, *, task_id=None, concurrency=3):
        self.check_all_pending_called_with = task_id
        if self._raise_exc:
            raise self._raise_exc
        return {"total": len(self._pending), "success": len(self._pending), "failed": 0, "failures": []}


class _FakeIndexChecker:
    def __init__(self, db, *, pending=None, raise_exc=None):
        self.db = db
        self._pending = pending or []
        self._raise_exc = raise_exc
        self.check_all_pending_called_with = None

    async def get_pending_urls(self):
        return self._pending

    async def check_all_pending(self, *, task_id=None):
        self.check_all_pending_called_with = task_id
        if self._raise_exc:
            raise self._raise_exc


def _patch_scheduler_common(monkeypatch, *, acquire_returns, fake_checker_cls):
    """统一 patch scheduler 模块的依赖。返回收集器 dict。"""
    from app.services import scheduler as sched

    fake_db = MagicMock()
    monkeypatch.setattr(sched, "async_session", lambda: _FakeCM(fake_db))

    acquire_calls = []
    async def fake_acquire(db, st):
        acquire_calls.append(st)
        return acquire_returns
    monkeypatch.setattr(sched, "acquire_scan_lock", fake_acquire)

    release_calls = []
    async def fake_release(db, st):
        release_calls.append(st)
    monkeypatch.setattr(sched, "release_scan_lock", fake_release)

    create_calls = []
    def fake_create(scan_type, total, targets):
        create_calls.append((scan_type, total))
        return "fake-task-id"
    monkeypatch.setattr(sched, "create_task", fake_create)

    complete_calls = []
    def fake_complete(task_id, status="completed"):
        complete_calls.append((task_id, status))
    monkeypatch.setattr(sched, "complete_task", fake_complete)

    # CitationChecker 在 scheduled_citation_check 内延迟导入
    monkeypatch.setattr("app.services.citation_checker.CitationChecker", fake_checker_cls)

    return {
        "db": fake_db,
        "acquire_calls": acquire_calls,
        "release_calls": release_calls,
        "create_calls": create_calls,
        "complete_calls": complete_calls,
    }


@pytest.mark.asyncio
async def test_scheduled_citation_check_skips_when_locked(monkeypatch):
    """拿不到锁 → 跳过，不创建任务、不释放锁（未获取则无需释放）。"""
    from app.services import scheduler as sched

    # 拿不到锁时也不应实例化 CitationChecker；用会失败的 fake 防止误调用
    def _unexpected_checker(db):
        raise AssertionError("拿不到锁时不应实例化 CitationChecker")

    ctx = _patch_scheduler_common(
        monkeypatch,
        acquire_returns=False,
        fake_checker_cls=_unexpected_checker,
    )

    await sched.scheduled_citation_check()

    assert ctx["acquire_calls"] == ["citation"]
    assert ctx["release_calls"] == []  # 未获取锁，不释放
    assert ctx["create_calls"] == []
    assert ctx["complete_calls"] == []


@pytest.mark.asyncio
async def test_scheduled_citation_check_no_pending_releases_lock(monkeypatch):
    """拿到锁 + 无 pending → 不创建任务，但仍释放锁。"""
    from app.services import scheduler as sched

    fake_checker_cls = lambda db: _FakeCitationChecker(db, pending=[])
    ctx = _patch_scheduler_common(
        monkeypatch,
        acquire_returns=True,
        fake_checker_cls=fake_checker_cls,
    )

    await sched.scheduled_citation_check()

    assert ctx["acquire_calls"] == ["citation"]
    assert ctx["release_calls"] == ["citation"]  # finally 释放
    assert ctx["create_calls"] == []  # 无 pending，不创建任务
    assert ctx["complete_calls"] == []


@pytest.mark.asyncio
async def test_scheduled_citation_check_full_flow(monkeypatch):
    """拿到锁 + 有 pending → 创建任务、透传 task_id、complete_task、释放锁。"""
    from app.services import scheduler as sched

    pending = [("https://a.com/1", "c1"), ("https://b.com/1", "c1")]
    instance_holder = {}
    def fake_checker_cls(db):
        inst = _FakeCitationChecker(db, pending=pending)
        instance_holder["inst"] = inst
        return inst
    ctx = _patch_scheduler_common(
        monkeypatch,
        acquire_returns=True,
        fake_checker_cls=fake_checker_cls,
    )

    await sched.scheduled_citation_check()

    assert ctx["acquire_calls"] == ["citation"]
    assert ctx["create_calls"] == [("citation", 2)]
    # task_id 透传给 check_all_pending
    assert instance_holder["inst"].check_all_pending_called_with == "fake-task-id"
    assert ctx["complete_calls"] == [("fake-task-id", "completed")]
    assert ctx["release_calls"] == ["citation"]


@pytest.mark.asyncio
async def test_scheduled_citation_check_releases_lock_on_exception(monkeypatch):
    """check_all_pending 抛异常时 finally 仍释放锁，不 complete_task。"""
    from app.services import scheduler as sched

    pending = [("https://a.com/1", "c1")]
    def fake_checker_cls(db):
        return _FakeCitationChecker(db, pending=pending, raise_exc=RuntimeError("boom"))
    ctx = _patch_scheduler_common(
        monkeypatch,
        acquire_returns=True,
        fake_checker_cls=fake_checker_cls,
    )

    # 异常应向上传播（scheduler 内不吞异常），但锁必须已释放
    with pytest.raises(RuntimeError, match="boom"):
        await sched.scheduled_citation_check()

    assert ctx["release_calls"] == ["citation"]  # finally 兜底释放
    assert ctx["complete_calls"] == []  # 异常时未 complete


@pytest.mark.asyncio
async def test_scheduled_index_check_full_flow(monkeypatch):
    """收录定时任务同样接入 lock + task_manager。"""
    from app.services import scheduler as sched

    fake_db = MagicMock()
    monkeypatch.setattr(sched, "async_session", lambda: _FakeCM(fake_db))

    async def fake_acquire(db, st):
        return True
    monkeypatch.setattr(sched, "acquire_scan_lock", fake_acquire)

    release_calls = []
    async def fake_release(db, st):
        release_calls.append(st)
    monkeypatch.setattr(sched, "release_scan_lock", fake_release)

    create_calls = []
    monkeypatch.setattr(
        sched, "create_task",
        lambda scan_type, total, targets: (create_calls.append((scan_type, total)) or "idx-tid"),
    )
    complete_calls = []
    monkeypatch.setattr(sched, "complete_task", lambda *a, **k: complete_calls.append(a))

    pending = [("https://a.com/1", "c1")]
    instance_holder = {}
    def fake_index_checker_cls(db):
        inst = _FakeIndexChecker(db, pending=pending)
        instance_holder["inst"] = inst
        return inst
    # IndexChecker 在 scheduler.py 顶部 import，绑定到 scheduler 模块命名空间，
    # 故 patch sched.IndexChecker（而非 app.services.index_checker.IndexChecker）
    monkeypatch.setattr(sched, "IndexChecker", fake_index_checker_cls)

    await sched.scheduled_index_check()

    # create_task(scan_type, total, targets)：pending 1 条 → total=1
    assert create_calls == [("index", 1)]
    assert instance_holder["inst"].check_all_pending_called_with == "idx-tid"
    assert complete_calls == [("idx-tid",)]
    assert release_calls == ["index"]
