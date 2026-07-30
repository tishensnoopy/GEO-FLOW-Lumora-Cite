# index-monitor/tests/unit/test_get_pending_urls_priority.py
"""get_pending_urls 增量优先级测试（阶段 3 - ②）。

验证目标：
1. 按 IndexResult.created_at DESC 排序——新文章优先检测
2. 未收录文章（无 IndexResult 记录）排末尾
3. 已有 citation_results 记录的 URL 被排除（增量）

设计文档②：SQL 层增量（LEFT JOIN citation_results IS NULL）+
按 IndexResult.created_at DESC 排序（新文章优先）。
"""
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


def _result(*, fetchall=None, scalars_all=None):
    """构造 db.execute 返回的 mock Result。"""
    m = MagicMock()
    if fetchall is not None:
        m.fetchall.return_value = fetchall
    if scalars_all is not None:
        m.scalars.return_value.all.return_value = scalars_all
    return m


@pytest.mark.asyncio
async def test_get_pending_urls_priority_newest_first(monkeypatch):
    """新文章（created_at 大）排前，旧文章排后，未收录排末尾。"""
    from app.services.citation_checker import CitationChecker

    db = MagicMock()
    checker = CitationChecker(db=db)

    # 屏蔽 GEOFlow 仓库（不引入额外 URL，专注手动录入分支的优先级）
    async def fake_geoflow_urls(self):
        return []
    monkeypatch.setattr(
        "app.integration.geoflow.GeoflowRepository.get_synced_distribution_urls",
        fake_geoflow_urls,
    )

    t_old = datetime(2026, 1, 1, tzinfo=timezone.utc)
    t_mid = datetime(2026, 3, 1, tzinfo=timezone.utc)
    t_new = datetime(2026, 7, 1, tzinfo=timezone.utc)

    db.execute = AsyncMock(side_effect=[
        # 1. manual_distributions：4 个 URL
        _result(fetchall=[
            ("https://old.com/a", "c1"),
            ("https://new.com/a", "c1"),
            ("https://mid.com/a", "c1"),
            ("https://norec.com/a", "c1"),  # 无 index 记录
        ]),
        # 2. client_sites：1 个 active 站点
        _result(scalars_all=[SimpleNamespace(domain="x.com", client_id="c1")]),
        # 3. citation_results：空（全部未检测）
        _result(fetchall=[]),
        # 4. index_results.created_at：old/mid/new 有记录，norec 无
        _result(fetchall=[
            ("https://old.com/a", t_old),
            ("https://mid.com/a", t_mid),
            ("https://new.com/a", t_new),
        ]),
    ])

    pending = await checker.get_pending_urls()
    urls = [u for u, _ in pending]

    # 期望：new（最新）→ mid → old → norec（未收录排末尾）
    assert urls == [
        "https://new.com/a",
        "https://mid.com/a",
        "https://old.com/a",
        "https://norec.com/a",
    ]


@pytest.mark.asyncio
async def test_get_pending_urls_excludes_already_cited(monkeypatch):
    """已有 citation_results 记录的 URL 被排除（增量语义）。"""
    from app.services.citation_checker import CitationChecker

    db = MagicMock()
    checker = CitationChecker(db=db)

    async def fake_geoflow_urls(self):
        return []
    monkeypatch.setattr(
        "app.integration.geoflow.GeoflowRepository.get_synced_distribution_urls",
        fake_geoflow_urls,
    )

    t = datetime(2026, 7, 1, tzinfo=timezone.utc)

    db.execute = AsyncMock(side_effect=[
        # manual：3 个 URL
        _result(fetchall=[
            ("https://a.com/1", "c1"),
            ("https://b.com/1", "c1"),
            ("https://c.com/1", "c1"),
        ]),
        _result(scalars_all=[SimpleNamespace(domain="x.com", client_id="c1")]),
        # citation_results：b.com 已检测 → 应被排除
        _result(fetchall=[("https://b.com/1",)]),
        # index_results：a/c 有记录
        _result(fetchall=[
            ("https://a.com/1", t),
            ("https://c.com/1", t),
        ]),
    ])

    pending = await checker.get_pending_urls()
    urls = {u for u, _ in pending}

    assert urls == {"https://a.com/1", "https://c.com/1"}
    assert "https://b.com/1" not in urls


@pytest.mark.asyncio
async def test_get_pending_urls_empty_returns_empty(monkeypatch):
    """无待检测 URL 时返回空列表（不查询 index_results.created_at）。"""
    from app.services.citation_checker import CitationChecker

    db = MagicMock()
    checker = CitationChecker(db=db)

    async def fake_geoflow_urls(self):
        return []
    monkeypatch.setattr(
        "app.integration.geoflow.GeoflowRepository.get_synced_distribution_urls",
        fake_geoflow_urls,
    )

    db.execute = AsyncMock(side_effect=[
        _result(fetchall=[]),  # manual 空
        _result(scalars_all=[]),  # sites 空
        _result(fetchall=[]),  # citation_results 空（early return 前仍会查询）
        # 无 pending → 提前 return，不再调用 index_results 查询
    ])

    pending = await checker.get_pending_urls()
    assert pending == []
