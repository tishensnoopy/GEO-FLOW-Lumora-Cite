# index-monitor/tests/perf/test_perf_scan_lock.py
"""advisory lock 延迟与互斥性能测试（真实 PG 连接）。

测量目标
========
1. acquire→release 一轮的延迟（确认 μs 级，对扫描整体耗时可忽略）
2. ``is_scan_locked`` 预检（查 ``pg_locks``）的查询开销
3. 并发 50 个协程同时 acquire 同一 key：只有 1 个成功、其余立即 False（非阻塞）
   ——验证 advisory lock 在高并发触发下的互斥正确性与延迟

隔离方式
========
advisory lock 是 PostgreSQL 功能，必须真实 PG 连接。使用与
``tests/unit/test_scan_lock.py`` 相同的 fixture 模式（用
``settings.DATABASE_URL`` 建 engine）。测试结束清理残留锁。

运行
====
    source venv/bin/activate
    pytest -p no:cacheprovider tests/perf/test_perf_scan_lock.py -s
"""
import asyncio
import statistics
import time

import pytest
import pytest_asyncio

try:
    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        async_sessionmaker,
        create_async_engine,
    )
    from app.core.config import settings
    from app.services.scan_lock import (
        acquire_scan_lock,
        release_scan_lock,
        is_scan_locked,
    )
    _PG_AVAILABLE = True
except Exception as _exc:  # noqa: BLE001
    _PG_AVAILABLE = False
    _IMPORT_ERR = _exc


@pytest_asyncio.fixture
async def db_factory():
    """创建真实 PG engine + session_factory，用完清理残留锁并 dispose。

    pool_size=60 以支持并发互斥测试中 50 个协程同时各占一条连接。
    """
    engine = create_async_engine(
        settings.DATABASE_URL, echo=False, pool_size=60, max_overflow=0
    )
    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    try:
        # 连通性预检
        async with session_factory() as s:
            from sqlalchemy import text
            await s.execute(text("SELECT 1"))
        yield session_factory
    finally:
        # 清理可能残留的锁
        async with session_factory() as s:
            for st in ("index", "citation"):
                try:
                    await release_scan_lock(s, st)
                except Exception:
                    pass
            await s.commit()
        await engine.dispose()


def _pg_skip():
    if not _PG_AVAILABLE:
        pytest.skip(f"PG 依赖不可用: {_IMPORT_ERR}")


# ---------------------------------------------------------------------------
# 1. acquire → release 单轮延迟（μs 级）
# ---------------------------------------------------------------------------
@pytest.mark.perf
@pytest.mark.asyncio
async def test_acquire_release_latency(capsys, db_factory):
    """测量 200 轮 acquire→release 的平均/中位/最大延迟。"""
    _pg_skip()
    iterations = 200
    latencies_us = []
    async with db_factory() as db:
        for _ in range(iterations):
            t0 = time.perf_counter_ns()
            got = await acquire_scan_lock(db, "citation")
            await release_scan_lock(db, "citation")
            await db.commit()
            t1 = time.perf_counter_ns()
            latencies_us.append((t1 - t0) / 1000.0)
            assert got is True

    avg = statistics.mean(latencies_us)
    med = statistics.median(latencies_us)
    p95 = sorted(latencies_us)[int(len(latencies_us) * 0.95)]
    mx = max(latencies_us)

    out = []
    out.append("")
    out.append("=" * 70)
    out.append(f"【advisory lock acquire→release 延迟】{iterations} 轮")
    out.append("=" * 70)
    out.append(f"{'平均(μs)':>10} | {'中位(μs)':>10} | {'P95(μs)':>10} | {'最大(μs)':>10}")
    out.append("-" * 70)
    out.append(f"{avg:>10.1f} | {med:>10.1f} | {p95:>10.1f} | {mx:>10.1f}")
    out.append("=" * 70)
    text = "\n".join(out)
    print(text)
    with capsys.disabled():
        print(text)

    # 锁延迟应在 ms 级以下（含 commit），对扫描整体耗时可忽略
    assert avg < 2000, f"acquire→release 平均延迟 {avg:.0f}μs 偏高"
    # 中位更稳定，应明显低于 1ms
    assert med < 1000, f"中位延迟 {med:.0f}μs 偏高"


# ---------------------------------------------------------------------------
# 2. is_scan_locked 预检查询开销
# ---------------------------------------------------------------------------
@pytest.mark.perf
@pytest.mark.asyncio
async def test_is_scan_locked_query_cost(capsys, db_factory):
    """测量 is_scan_locked（查 pg_locks）的查询开销。"""
    _pg_skip()
    iterations = 200
    latencies_us = []
    async with db_factory() as db:
        for _ in range(iterations):
            t0 = time.perf_counter_ns()
            locked = await is_scan_locked(db, "citation")
            t1 = time.perf_counter_ns()
            latencies_us.append((t1 - t0) / 1000.0)
            assert locked is False  # 无锁时返回 False

    avg = statistics.mean(latencies_us)
    med = statistics.median(latencies_us)
    mx = max(latencies_us)

    out = []
    out.append("")
    out.append("=" * 70)
    out.append(f"【is_scan_locked 预检查询开销】{iterations} 次")
    out.append("=" * 70)
    out.append(f"{'平均(μs)':>10} | {'中位(μs)':>10} | {'最大(μs)':>10}")
    out.append("-" * 70)
    out.append(f"{avg:>10.1f} | {med:>10.1f} | {mx:>10.1f}")
    out.append("=" * 70)
    text = "\n".join(out)
    print(text)
    with capsys.disabled():
        print(text)

    # 预检查询应很快（pg_locks 是视图，但数据量小）
    assert avg < 3000, f"is_scan_locked 平均开销 {avg:.0f}μs 偏高"


# ---------------------------------------------------------------------------
# 3. 50 协程并发 acquire 同一 key：互斥正确性 + 延迟
# ---------------------------------------------------------------------------
@pytest.mark.perf
@pytest.mark.asyncio
async def test_concurrent_acquire_only_one_succeeds(capsys, db_factory):
    """50 个协程同时 acquire 同一 key，应只有 1 个成功、其余立即 False。

    关键设计：
    1. 获胜者 acquire 后在 ``release_event`` 上阻塞，**保持 session 与锁不释放**，
       直到全部协程都完成 acquire 尝试。否则获胜者 session 关闭会释放锁，导致后续
       批次又能获取（连接池分批调度下会出现多个成功者）。
    2. 测量前先 ``SELECT 1`` 预热每条连接，排除连接建立耗时对锁延迟测量的污染——
       生产环境连接池是热的，pg_try_advisory_lock 本身应 μs~低 ms 级返回。
    """
    _pg_skip()
    from sqlalchemy import text

    n = 50
    start_event = asyncio.Event()
    release_event = asyncio.Event()
    results: list[dict] = []
    state = {"warmed": 0}

    async def _try_acquire(idx):
        async with db_factory() as db:
            # 预热：建立真实连接，避免连接建立耗时污染锁延迟测量
            await db.execute(text("SELECT 1"))
            state["warmed"] += 1
            await start_event.wait()
            t0 = time.perf_counter_ns()
            got = await acquire_scan_lock(db, "citation")
            t1 = time.perf_counter_ns()
            results.append({"idx": idx, "got": got, "latency_us": (t1 - t0) / 1000.0})
            if got:
                # 获胜者持有锁，直到主协程发令释放
                await release_event.wait()
                await release_scan_lock(db, "citation")
                await db.commit()
            # 失败者直接退出（session 关闭，未持有锁）

    tasks = [asyncio.create_task(_try_acquire(i)) for i in range(n)]
    # 等待全部 50 个协程完成连接预热（排除连接建立耗时后再开测）
    try:
        await asyncio.wait_for(_wait_warm(state, n), timeout=30.0)
    except asyncio.TimeoutError:
        pass

    t_start = time.perf_counter()
    start_event.set()  # 统一发令
    # 等待全部 50 个协程都记录结果（获胜者此刻阻塞在 release_event）
    try:
        await asyncio.wait_for(_wait_results(results, n), timeout=15.0)
    except asyncio.TimeoutError:
        pass
    t_end = time.perf_counter()

    # 放行获胜者，让其释放锁并退出
    release_event.set()
    await asyncio.gather(*tasks, return_exceptions=True)

    success_count = sum(1 for r in results if r["got"])
    fail_count = sum(1 for r in results if not r["got"])
    fail_latencies = [r["latency_us"] for r in results if not r["got"]]
    fail_avg = statistics.mean(fail_latencies) if fail_latencies else 0.0
    fail_max = max(fail_latencies) if fail_latencies else 0.0

    out = []
    out.append("")
    out.append("=" * 82)
    out.append(f"【并发 acquire 互斥】{n} 个协程同时 acquire 同一 key（连接已预热）")
    out.append("=" * 82)
    out.append(
        f"{'成功数':>6} | {'失败数':>6} | {'失败平均延迟(μs)':>18} | "
        f"{'失败最大延迟(μs)':>18} | {'竞争窗口(ms)':>14}"
    )
    out.append("-" * 82)
    out.append(
        f"{success_count:>6} | {fail_count:>6} | "
        f"{fail_avg:>18.1f} | "
        f"{fail_max:>18.1f} | {(t_end - t_start) * 1000:>14.1f}"
    )
    out.append("=" * 82)
    text = "\n".join(out)
    print(text)
    with capsys.disabled():
        print(text)

    # 关键断言：恰好 1 个成功
    assert success_count == 1, f"应只有 1 个成功，实际 {success_count}"
    assert fail_count == n - 1, f"应 {n - 1} 个失败，实际 {fail_count}"
    # 失败者应"立即"返回（非阻塞）：pg_try_advisory_lock 不等待，应 ms 级返回。
    # 阈值 50ms 足以区分非阻塞（ms 级）与阻塞（会等到 release_event → 超时）
    assert fail_max < 50000, (
        f"失败 acquire 最大延迟 {fail_max:.0f}μs，非阻塞语义可能失效"
    )


async def _wait_warm(state, n):
    """等待 n 个协程完成连接预热。"""
    while state["warmed"] < n:
        await asyncio.sleep(0.01)


async def _wait_results(results, n):
    """等待 results 收集到 n 条。"""
    while len(results) < n:
        await asyncio.sleep(0.005)
