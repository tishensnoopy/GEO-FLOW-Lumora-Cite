# index-monitor/tests/perf/test_perf_concurrency.py
"""并发原语吞吐与加速比性能测试。

测量目标
========
验证 ``check_all_pending`` 的 ``asyncio.gather`` + ``Semaphore(concurrency)``
并发原语是否真正生效，并量化不同 concurrency × N 组合下的：
- 实际总耗时
- 吞吐（URL/s）
- 最大实测并发度（证明 semaphore 既限制并发、又不退化为串行）
- 相对串行（concurrency=1）的加速比

隔离方式
========
用 mock 的 ``check_url``（``asyncio.sleep`` 模拟单条耗时）替代真实
DeepSeek / 爬虫调用，只测本地并发调度开销与加速比，不触外部依赖。

运行
====
    source venv/bin/activate
    pytest -p no:cacheprovider tests/perf/test_perf_concurrency.py -s
"""
import asyncio
import time
from unittest.mock import MagicMock

import pytest

from app.services.citation_checker import CitationChecker

# 单条 check_url 模拟耗时（秒）。0.1s 既能放大加速比、又控制总时长 < 30s。
PER_CALL = 0.1
# 待测并发度
CONCURRENCIES = [1, 3, 5, 8, 10]
# 待测 URL 数量
NS = [10, 30, 50]


def _make_checker_with_pending(pending):
    """构造 CitationChecker，get_pending_urls 返回 pending，check_url 待替换。"""
    checker = CitationChecker(db=MagicMock())

    async def fake_get_pending():
        return pending

    checker.get_pending_urls = fake_get_pending
    return checker


def _run_once(pending, concurrency, per_call=PER_CALL):
    """同步运行一次 check_all_pending，返回 (耗时秒, 最大并发度)。

    用 asyncio.run 隔离每次测量的事件循环，避免跨用例污染。
    """
    checker = _make_checker_with_pending(pending)

    current = 0
    max_concurrent = 0

    async def fake_check_url(self, url, client_id, *, task_id=None, progress=None):
        nonlocal current, max_concurrent
        current += 1
        if current > max_concurrent:
            max_concurrent = current
        await asyncio.sleep(per_call)
        current -= 1

    # Phase 3 改造：check_all_pending 内部为每个 _check_one 创建独立
    # AsyncSession + CitationChecker 实例（AsyncSession 并发不安全）。
    # 实例级 checker.check_url = fake 不会传播到内部实例，需类级 patch。
    # 同时 patch async_session 返回 mock context manager，避免真实 DB 连接
    # （本测试只测并发调度开销，不触 DB）。
    # 注意：citation_checker 在 check_all_pending 内部用 ``from app.core.database
    # import async_session`` 局部导入，所以 patch 目标是源头 app.core.database。
    from contextlib import asynccontextmanager
    from unittest.mock import patch as _patch

    @asynccontextmanager
    async def fake_session():
        yield MagicMock()

    with _patch("app.core.database.async_session", lambda: fake_session()), \
         _patch.object(CitationChecker, "check_url", fake_check_url):
        async def _main():
            return await checker.check_all_pending(concurrency=concurrency)

        t0 = time.perf_counter()
        summary = asyncio.run(_main())
        elapsed = time.perf_counter() - t0
    return elapsed, max_concurrent, summary


@pytest.mark.perf
def test_concurrency_speedup_matrix(capsys):
    """主加速比矩阵：concurrency × N，输出耗时/吞吐/加速比/最大并发度。"""
    rows = []
    # 先测串行基线（concurrency=1），用于计算加速比
    serial_times = {}  # N -> serial elapsed
    for n in NS:
        pending = [(f"https://example.com/{i}", f"c-{i}") for i in range(n)]
        elapsed, max_c, summary = _run_once(pending, 1)
        serial_times[n] = elapsed
        rows.append({
            "N": n, "concurrency": 1, "elapsed": elapsed,
            "max_conc": max_c, "throughput": n / elapsed,
            "speedup": 1.0, "success": summary["success"], "failed": summary["failed"],
        })

    # 再测并发场景
    for n in NS:
        pending = [(f"https://example.com/{i}", f"c-{i}") for i in range(n)]
        for c in CONCURRENCIES:
            if c == 1:
                continue  # 已测
            elapsed, max_c, summary = _run_once(pending, c)
            serial_base = serial_times[n]
            speedup = serial_base / elapsed
            rows.append({
                "N": n, "concurrency": c, "elapsed": elapsed,
                "max_conc": max_c, "throughput": n / elapsed,
                "speedup": speedup, "success": summary["success"], "failed": summary["failed"],
            })

    # 打印表格
    out = []
    out.append("")
    out.append("=" * 92)
    out.append("【并发原语加速比矩阵】单条模拟耗时 = %.3fs" % PER_CALL)
    out.append("=" * 92)
    header = f"{'N':>4} | {'conc':>4} | {'耗时(s)':>9} | {'吞吐(URL/s)':>12} | {'加速比':>7} | {'最大并发':>8} | {'成功/失败':>9}"
    out.append(header)
    out.append("-" * 92)
    for r in sorted(rows, key=lambda x: (x["N"], x["concurrency"])):
        out.append(
            f"{r['N']:>4} | {r['concurrency']:>4} | {r['elapsed']:>9.4f} | "
            f"{r['throughput']:>12.2f} | {r['speedup']:>7.2f} | {r['max_conc']:>8} | "
            f"{r['success']}/{r['failed']:>2}"
        )
    out.append("=" * 92)
    text = "\n".join(out)
    print(text)
    with capsys.disabled():
        print(text)

    # ---- 关键断言（用证据支撑结论）----
    by_key = {(r["N"], r["concurrency"]): r for r in rows}

    # 1. semaphore 真正限制并发：最大并发度 <= concurrency
    for (n, c), r in by_key.items():
        assert r["max_conc"] <= c, f"N={n} c={c} 最大并发 {r['max_conc']} 超过 semaphore 上限 {c}"

    # 2. concurrency=1 退化为串行：最大并发度 == 1
    for n in NS:
        assert by_key[(n, 1)]["max_conc"] == 1, f"N={n} c=1 应串行，实际最大并发 {by_key[(n, 1)]['max_conc']}"

    # 3. 并发确实发生（c>=3 且 N>=c 时最大并发 >= 2）
    assert by_key[(30, 5)]["max_conc"] >= 3, "c=5 N=30 应至少并发 3"

    # 4. 加速比：c=5 应明显快于 c=1（加速比 >= 3.0，留调度开销余量）
    for n in NS:
        sp5 = by_key[(n, 5)]["speedup"]
        assert sp5 >= 3.0, f"N={n} c=5 加速比 {sp5:.2f} 偏低，并发未生效"

    # 5. 吞吐随并发上升（c=10 吞吐 >= c=1 吞吐的 3 倍）
    for n in NS:
        tp1 = by_key[(n, 1)]["throughput"]
        tp10 = by_key[(n, 10)]["throughput"]
        assert tp10 >= tp1 * 3, f"N={n} c=10 吞吐 {tp10:.1f} 未达 c=1 吞吐 {tp1:.1f} 的 3 倍"


@pytest.mark.perf
def test_concurrency_scheduling_overhead(capsys):
    """调度开销测量：单条耗时趋近 0 时，并发原语本身的纯调度开销。

    当 per_call 极小（0.001s）时，耗时主要来自 gather + semaphore 调度，
    而非业务等待。验证并发原语本身开销可忽略（50 个任务调度 < 50ms 量级）。
    """
    n = 50
    pending = [(f"https://example.com/{i}", f"c-{i}") for i in range(n)]
    rows = []
    for c in [1, 3, 5, 10]:
        elapsed, max_c, _ = _run_once(pending, c, per_call=0.001)
        rows.append({"N": n, "concurrency": c, "elapsed_ms": elapsed * 1000, "max_conc": max_c})

    out = []
    out.append("")
    out.append("-" * 60)
    out.append("【调度纯开销】单条模拟耗时 = 0.001s, N = 50")
    out.append("-" * 60)
    out.append(f"{'conc':>4} | {'耗时(ms)':>10} | {'最大并发':>8}")
    for r in rows:
        out.append(f"{r['concurrency']:>4} | {r['elapsed_ms']:>10.2f} | {r['max_conc']:>8}")
    out.append("-" * 60)
    text = "\n".join(out)
    print(text)
    with capsys.disabled():
        print(text)

    # 调度开销应很小：c=1 时 50 个任务纯调度 < 200ms
    assert rows[0]["elapsed_ms"] < 200, f"纯调度开销过大: {rows[0]['elapsed_ms']:.1f}ms"
