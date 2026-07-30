# index-monitor/tests/perf/test_perf_get_pending_urls.py
"""get_pending_urls 优先级查询与排序开销性能测试。

测量目标
========
``CitationChecker.get_pending_urls`` 新增了一次 ``SELECT ... WHERE url IN (...)``
查询 + Python 侧按 ``IndexResult.created_at DESC`` 排序。测量不同 pending 规模
（10/100/1000/5000）下的耗时，确认：
- 新增 IN 查询 + Python 排序在 1000 级别仍 < 200ms
- 排序正确性（新文章优先，未收录排末尾）

隔离方式
========
用 mock ``db.execute`` 返回预设数据，隔离测量 Python 侧"IN 查询结果组装 +
dict 构建 + 排序"开销（这部分是本轮新增代码路径，决定排序是否成瓶颈）。
真实 DB 的 IN 查询本身有索引支撑，不在本测试范围。

运行
====
    source venv/bin/activate
    pytest -p no:cacheprovider tests/perf/test_perf_get_pending_urls.py -s
"""
import random
import statistics
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.citation_checker import CitationChecker


def _result(*, fetchall=None, scalars_all=None):
    """构造 db.execute 返回的 mock Result。"""
    m = MagicMock()
    if fetchall is not None:
        m.fetchall.return_value = fetchall
    if scalars_all is not None:
        m.scalars.return_value.all.return_value = scalars_all
    return m


def _build_mock_db(n, with_unrecorded_ratio=0.2, seed=42):
    """构造 mock db，4 次 execute 分别返回 manual/sites/checked/index 结果。

    Parameters
    ----------
    n : int
        pending URL 数量
    with_unrecorded_ratio : float
        无 IndexResult 记录（未收录）的 URL 占比，用于测试 partition 排序
    seed : int
        随机种子（created_at 顺序打乱用）
    """
    rng = random.Random(seed)
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)

    # manual 分发：n 个 URL，client_id 统一
    manual = [(f"https://site-{i}.com/article-{i}", "client-1") for i in range(n)]
    # 1 个 active 站点
    sites = [SimpleNamespace(domain="site-0.com", client_id="client-1")]
    # 已检测 URL：空（全部 pending，走完整排序路径）
    checked = []
    # IndexResult.created_at：部分 URL 无记录（未收录）
    n_recorded = int(n * (1 - with_unrecorded_ratio))
    recorded_urls = manual[:n_recorded]
    # created_at 随机打乱顺序，验证排序正确性
    shuffled = list(recorded_urls)
    rng.shuffle(shuffled)
    idx_rows = [
        (url, base + timedelta(seconds=rng.randint(0, n * 100)))
        for url, _ in shuffled
    ]

    db = MagicMock()
    db.execute = AsyncMock(side_effect=[
        _result(fetchall=manual),          # 1. manual_distributions
        _result(scalars_all=sites),        # 2. client_sites
        _result(fetchall=checked),         # 3. citation_results（增量）
        _result(fetchall=idx_rows),        # 4. index_results.created_at（IN 查询）
    ])
    return db, manual, idx_rows


async def _patched_geoflow_urls(self):
    """屏蔽 GEOFlow 仓库，专注手动录入分支的排序开销。"""
    return []


@pytest.mark.perf
@pytest.mark.asyncio
async def test_get_pending_urls_sort_overhead(capsys, monkeypatch):
    """测量不同 pending 规模下 get_pending_urls 的排序+组装耗时。"""
    monkeypatch.setattr(
        "app.integration.geoflow.GeoflowRepository.get_synced_distribution_urls",
        _patched_geoflow_urls,
    )

    scales = [10, 100, 1000, 5000]
    repeats = 5
    rows = []

    for n in scales:
        latencies_ms = []
        for rep in range(repeats):
            db, manual, idx_rows = _build_mock_db(n, seed=rep)
            checker = CitationChecker(db=db)
            t0 = time.perf_counter_ns()
            pending = await checker.get_pending_urls()
            elapsed_ms = (time.perf_counter_ns() - t0) / 1e6
            latencies_ms.append(elapsed_ms)
            # 正确性校验（最后一次用例）
            assert len(pending) == n, f"N={n} 期望返回 {n} 条，实际 {len(pending)}"

        avg = statistics.mean(latencies_ms)
        med = statistics.median(latencies_ms)
        mx = max(latencies_ms)
        rows.append({"N": n, "avg_ms": avg, "med_ms": med, "max_ms": mx})

    out = []
    out.append("")
    out.append("=" * 66)
    out.append("【get_pending_urls 排序+组装开销】mock db，5 次取统计")
    out.append("=" * 66)
    out.append(f"{'N':>6} | {'平均(ms)':>10} | {'中位(ms)':>10} | {'最大(ms)':>10}")
    out.append("-" * 66)
    for r in rows:
        out.append(f"{r['N']:>6} | {r['avg_ms']:>10.3f} | {r['med_ms']:>10.3f} | {r['max_ms']:>10.3f}")
    out.append("=" * 66)
    text = "\n".join(out)
    print(text)
    with capsys.disabled():
        print(text)

    # 关键断言：1000 级别 < 200ms
    by_n = {r["N"]: r for r in rows}
    assert by_n[1000]["avg_ms"] < 200, f"N=1000 平均 {by_n[1000]['avg_ms']:.1f}ms 超过 200ms"
    # 5000 级别也应很快（纯 Python 排序 O(n log n)）
    assert by_n[5000]["avg_ms"] < 500, f"N=5000 平均 {by_n[5000]['avg_ms']:.1f}ms 偏高"
    # 规模线性度：1000 的耗时不应是 100 的 50 倍以上（非平方退化）
    ratio = by_n[1000]["avg_ms"] / max(by_n[100]["avg_ms"], 0.001)
    assert ratio < 50, f"1000→100 耗时比 {ratio:.1f}，疑似平方退化"


@pytest.mark.perf
@pytest.mark.asyncio
async def test_get_pending_urls_sort_correctness(capsys, monkeypatch):
    """验证排序正确性：新文章（created_at 大）在前，未收录排末尾。"""
    monkeypatch.setattr(
        "app.integration.geoflow.GeoflowRepository.get_synced_distribution_urls",
        _patched_geoflow_urls,
    )

    n = 100
    db, manual, idx_rows = _build_mock_db(n, with_unrecorded_ratio=0.2, seed=7)
    checker = CitationChecker(db=db)
    pending = await checker.get_pending_urls()

    urls = [u for u, _ in pending]
    # 拆分：有 created_at 的前段 + 无记录的末段
    recorded_set = {row[0] for row in idx_rows}
    unrecorded_set = set(u for u, _ in manual) - recorded_set

    # 找到第一个未收录 URL 的位置
    first_unrec_idx = next(
        (i for i, u in enumerate(urls) if u in unrecorded_set), len(urls)
    )
    recorded_part = urls[:first_unrec_idx]
    unrecorded_part = urls[first_unrec_idx:]

    # 未收录应全部在末尾
    assert len(unrecorded_part) == len(unrecorded_set), "未收录 URL 应全部排末尾"
    # 已收录部分应按 created_at DESC
    ts_map = {row[0]: row[1] for row in idx_rows}
    recorded_ts = [ts_map[u] for u in recorded_part]
    assert recorded_ts == sorted(recorded_ts, reverse=True), "已收录应按 created_at DESC"

    n_unrec = len(unrecorded_set)
    n_rec = n - n_unrec
    out = []
    out.append("")
    out.append("-" * 50)
    out.append(f"【排序正确性】N={n}, 已收录={n_rec}, 未收录={n_unrec}")
    out.append(f"前 3（最新）: {[u.split('/')[-1] for u in recorded_part[:3]]}")
    out.append(f"末 3（未收录）: {[u.split('/')[-1] for u in unrecorded_part[-3:]]}")
    out.append(f"已收录部分降序校验: 通过")
    out.append("-" * 50)
    text = "\n".join(out)
    print(text)
    with capsys.disabled():
        print(text)
