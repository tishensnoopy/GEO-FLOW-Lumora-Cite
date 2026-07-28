"""Reader：SQLAlchemy 查询构建测试（mock db.execute）。

只验证查询能正确构建和执行、结果能正确解包，
不验证 SQL 语义（那是契约测试的职责）。
"""
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.integration.geoflow.reader import (
    fetch_deleted_distributions_with_article,
    fetch_distribution_by_ids,
    fetch_distribution_count_by_date,
    fetch_distributions_with_article,
    fetch_synced_distribution_urls,
    fetch_synced_url_exists,
)


@pytest.mark.asyncio
async def test_fetch_synced_distribution_urls_returns_url_list():
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.fetchall.return_value = [("https://a.com/1",), ("https://b.com/2",)]
    mock_db.execute.return_value = mock_result

    urls = await fetch_synced_distribution_urls(mock_db)
    assert urls == ["https://a.com/1", "https://b.com/2"]


@pytest.mark.asyncio
async def test_fetch_distribution_by_ids_returns_rows():
    mock_db = AsyncMock()
    mock_dist = SimpleNamespace(
        id=1, article_id=100, remote_url="u", status="synced",
        action="publish", distribution_channel_id=5,
        created_at=datetime(2026, 7, 29, tzinfo=timezone.utc),
    )
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [mock_dist]
    mock_db.execute.return_value = mock_result

    rows = await fetch_distribution_by_ids(mock_db, [1, 2])
    assert len(rows) == 1
    assert rows[0].id == 1


@pytest.mark.asyncio
async def test_fetch_distribution_by_ids_empty_ids_returns_empty():
    mock_db = AsyncMock()
    rows = await fetch_distribution_by_ids(mock_db, [])
    assert rows == []
    mock_db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_fetch_distribution_count_by_date_returns_rows():
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.fetchall.return_value = [
        (datetime(2026, 7, 28, tzinfo=timezone.utc), 5),
        (datetime(2026, 7, 29, tzinfo=timezone.utc), 3),
    ]
    mock_db.execute.return_value = mock_result

    rows = await fetch_distribution_count_by_date(
        mock_db, datetime(2026, 7, 28, tzinfo=timezone.utc)
    )
    assert len(rows) == 2
    assert rows[0] == (datetime(2026, 7, 28, tzinfo=timezone.utc), 5)


@pytest.mark.asyncio
async def test_fetch_distributions_with_article_no_date_filter():
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.fetchall.return_value = []
    mock_db.execute.return_value = mock_result

    rows = await fetch_distributions_with_article(mock_db)
    assert rows == []
    # 验证 db.execute 被调用（查询构建成功）
    mock_db.execute.assert_called_once()


@pytest.mark.asyncio
async def test_fetch_distributions_with_article_with_date_filter():
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.fetchall.return_value = []
    mock_db.execute.return_value = mock_result

    start = datetime(2026, 7, 1, tzinfo=timezone.utc)
    end = datetime(2026, 7, 31, tzinfo=timezone.utc)
    await fetch_distributions_with_article(mock_db, date_from=start, date_to=end)
    mock_db.execute.assert_called_once()


@pytest.mark.asyncio
async def test_fetch_deleted_distributions_with_article():
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.fetchall.return_value = []
    mock_db.execute.return_value = mock_result

    rows = await fetch_deleted_distributions_with_article(mock_db)
    assert rows == []
    mock_db.execute.assert_called_once()


@pytest.mark.asyncio
async def test_fetch_synced_url_exists_returns_true():
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar.return_value = True
    mock_db.execute.return_value = mock_result

    exists = await fetch_synced_url_exists(mock_db, "https://a.com/1")
    assert exists is True
    mock_db.execute.assert_called_once()


@pytest.mark.asyncio
async def test_fetch_synced_url_exists_returns_false():
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar.return_value = False
    mock_db.execute.return_value = mock_result

    exists = await fetch_synced_url_exists(mock_db, "https://a.com/not-exist")
    assert exists is False
