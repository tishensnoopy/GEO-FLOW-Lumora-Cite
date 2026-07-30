# index-monitor/tests/perf/test_perf_progress_update.py
"""update_progress 锁竞争 + trigger_scan 响应延迟性能测试。

测量目标
========
1. ``update_progress`` 单次调用开销（无竞争基线——采信扫描路径的实际开销）
2. ``update_progress`` 在高并发（50 协程经 ``asyncio.to_thread`` 真正跨线程）
   下的 ``threading.Lock`` 竞争开销——压力测试锁是否成为瓶颈
3. ``/scan/trigger/{type}`` 响应延迟：``asyncio.create_task`` 后台执行不阻塞
   HTTP 响应（mock checker + 慢后台任务，响应应 < 100ms）

隔离方式
========
- update_progress 测试只操作内存 dict + threading.Lock，无外部依赖
- trigger 测试用 httpx ASGITransport 直连 ASGI app，mock get_pending_urls
  与 _run_scan_background，override get_db 避免跨事件循环复用 engine

运行
====
    source venv/bin/activate
    pytest -p no:cacheprovider tests/perf/test_perf_progress_update.py -s
"""
import asyncio
import statistics
import time

import pytest
import pytest_asyncio

from app.services import scan_task_manager as stm


# ---------------------------------------------------------------------------
# 1. update_progress 单次调用开销（无竞争基线）
# ---------------------------------------------------------------------------
@pytest.mark.perf
def test_update_progress_per_call_overhead(capsys):
    """采信扫描路径实际开销：单事件循环线程顺序调用 update_progress。"""
    task_id = stm.create_task("citation", 1000, [("https://x.com", "c1")])
    iterations = 5000

    t0 = time.perf_counter_ns()
    for i in range(iterations):
        stm.update_progress(task_id, processed=i, success=i, failed=0)
    elapsed_ns = time.perf_counter_ns() - t0

    per_call_us = elapsed_ns / iterations / 1000.0
    total_ms = elapsed_ns / 1e6
    task = stm.get_task(task_id)
    assert task["processed"] == iterations - 1

    out = []
    out.append("")
    out.append("=" * 66)
    out.append(f"【update_progress 无竞争单次开销】{iterations} 次顺序调用")
    out.append("=" * 66)
    out.append(f"{'总耗时(ms)':>12} | {'单次(μs)':>10} | {'最终 processed':>16}")
    out.append("-" * 66)
    out.append(f"{total_ms:>12.2f} | {per_call_us:>10.3f} | {task['processed']:>16}")
    out.append("=" * 66)
    text = "\n".join(out)
    print(text)
    with capsys.disabled():
        print(text)

    # 单次调用应在微秒级（含 3 次 datetime.isoformat + lock + dict 写）
    assert per_call_us < 50, f"单次 update_progress 开销 {per_call_us:.2f}μs 偏高"


# ---------------------------------------------------------------------------
# 2. update_progress 高并发跨线程锁竞争（压力测试）
# ---------------------------------------------------------------------------
@pytest.mark.perf
@pytest.mark.asyncio
async def test_update_progress_concurrent_contention(capsys):
    """50 协程经 asyncio.to_thread 真正跨线程并发，压测 threading.Lock 竞争。

    生产采信扫描路径在单事件循环线程内调用 update_progress（无真竞争）；
    本测试用线程池制造真实锁竞争，验证即便在最坏情况下锁也不是瓶颈。
    """
    n_workers = 50
    calls_per_worker = 200
    task_id = stm.create_task("citation", n_workers * calls_per_worker, [])

    async def _worker(wid):
        def _batch():
            for j in range(calls_per_worker):
                stm.update_progress(
                    task_id,
                    processed=wid * calls_per_worker + j,
                    success=0,
                    failed=0,
                )
        # 经线程池执行，制造跨线程锁竞争
        await asyncio.to_thread(_batch)

    t0 = time.perf_counter()
    await asyncio.gather(*[_worker(i) for i in range(n_workers)])
    elapsed = time.perf_counter() - t0

    total_calls = n_workers * calls_per_worker
    throughput = total_calls / elapsed
    per_call_us = elapsed / total_calls * 1e6
    task = stm.get_task(task_id)
    # 末态 processed 是某 worker 最后写入的值，非定值；只校验 < 总调用数
    assert task["processed"] < total_calls

    out = []
    out.append("")
    out.append("=" * 74)
    out.append(f"【update_progress 跨线程锁竞争】{n_workers} 线程 × {calls_per_worker} 次")
    out.append("=" * 74)
    out.append(
        f"{'总调用':>8} | {'总耗时(s)':>10} | {'吞吐(call/s)':>14} | {'单次(μs)':>10}"
    )
    out.append("-" * 74)
    out.append(
        f"{total_calls:>8} | {elapsed:>10.4f} | {throughput:>14.0f} | {per_call_us:>10.3f}"
    )
    out.append("=" * 74)
    text = "\n".join(out)
    print(text)
    with capsys.disabled():
        print(text)

    # 即便 50 线程竞争，单次调用应在百微秒级以内（锁竞争不致命）
    assert per_call_us < 500, f"竞争下单次 update_progress {per_call_us:.1f}μs 偏高"
    # 吞吐应远超采信扫描需求（扫描每条才调一次）
    assert throughput > 1000, f"吞吐 {throughput:.0f} call/s 偏低"


# ---------------------------------------------------------------------------
# 3. trigger_scan 响应延迟（asyncio.create_task 不阻塞 HTTP）
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture
async def _app_with_overridden_db():
    """override get_db 避免跨事件循环复用模块级 engine。"""
    from app.main import app
    from app.core.database import get_db
    from app.core.config import settings
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _get_db_override():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _get_db_override
    try:
        yield app
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


def _admin_headers():
    from datetime import datetime, timedelta, timezone
    import jwt
    from app.core.config import settings
    payload = {
        "sub": "1", "name": "perf", "role": "admin", "type": "admin",
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        "iat": datetime.now(timezone.utc),
    }
    token = jwt.encode(payload, settings.SSO_JWT_SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.perf
@pytest.mark.asyncio
async def test_trigger_scan_response_latency(capsys, _app_with_overridden_db, monkeypatch):
    """mock 慢后台任务（sleep 1s），测量 /scan/trigger 响应延迟应 < 100ms。"""
    from httpx import ASGITransport, AsyncClient
    from app.core.config import settings  # noqa: F401  确保 settings 可导入
    from app.api import routes

    fake_pending = [(f"https://example.com/{i}", "client-1") for i in range(30)]

    async def fake_get_pending(self):
        return fake_pending
    monkeypatch.setattr(
        "app.services.citation_checker.CitationChecker.get_pending_urls",
        fake_get_pending,
    )

    done_event = asyncio.Event()

    async def slow_background(scan_type, task_id):
        # 模拟耗时扫描；create_task 应使其后台运行，不阻塞 HTTP 响应
        await asyncio.sleep(1.0)
        done_event.set()

    monkeypatch.setattr(routes, "_run_scan_background", slow_background)

    transport = ASGITransport(app=_app_with_overridden_db)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        # 多次测量取统计
        latencies_ms = []
        task_ids = []
        for _ in range(10):
            t0 = time.perf_counter()
            resp = await ac.post("/api/v1/scan/trigger/citation", headers=_admin_headers())
            t1 = time.perf_counter()
            assert resp.status_code == 200, resp.text
            latencies_ms.append((t1 - t0) * 1000)
            data = resp.json()
            task_ids.append(data.get("task_id"))

        # 等待最后一次的后台慢任务完成（避免事件循环警告）
        await done_event.wait()

    avg = statistics.mean(latencies_ms)
    med = statistics.median(latencies_ms)
    mx = max(latencies_ms)

    out = []
    out.append("")
    out.append("=" * 72)
    out.append("【/scan/trigger 响应延迟】后台任务 sleep 1s，10 次测量")
    out.append("=" * 72)
    out.append(f"{'平均(ms)':>10} | {'中位(ms)':>10} | {'最大(ms)':>10} | {'返回 task_id':>14}")
    out.append("-" * 72)
    all_have_tid = all(t is not None for t in task_ids)
    out.append(f"{avg:>10.2f} | {med:>10.2f} | {mx:>10.2f} | {'全部非空' if all_have_tid else '有空值':>14}")
    out.append("=" * 72)
    text = "\n".join(out)
    print(text)
    with capsys.disabled():
        print(text)

    # 关键断言：响应延迟 < 100ms（后台慢任务不阻塞）
    assert avg < 100, f"trigger 平均响应 {avg:.1f}ms 超过 100ms，可能被后台任务阻塞"
    assert mx < 200, f"trigger 最大响应 {mx:.1f}ms 偏高"
    assert all_have_tid, "每次应返回非空 task_id"
