"""Repository：仓储方法编排测试（mock reader 函数）。"""
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.integration.geoflow.dto import (
    ArticleDTO,
    DistributionChannelDTO,
    DistributionDTO,
    DistributionWithArticleDTO,
)
from app.integration.geoflow.repository import GeoflowRepository


def _fake_dist_row(**overrides):
    base = SimpleNamespace(
        id=1, article_id=100, remote_url="u", status="synced",
        action="publish", distribution_channel_id=5,
        created_at=datetime(2026, 7, 29, tzinfo=timezone.utc),
    )
    base.__dict__.update(overrides)
    return base


def _fake_article_row():
    return SimpleNamespace(
        id=100, title="t", slug="s", excerpt="e", content="c",
        keywords='["k"]', meta_description="m", original_keyword="k",
        published_at=datetime(2026, 7, 29, tzinfo=timezone.utc),
    )


def _fake_channel_row():
    return SimpleNamespace(
        id=5, name="n", domain="d", channel_type="geoflow_agent",
    )


@pytest.mark.asyncio
async def test_get_synced_distribution_urls():
    mock_db = AsyncMock()
    repo = GeoflowRepository(mock_db)
    with patch(
        "app.integration.geoflow.repository.fetch_synced_distribution_urls",
        new_callable=AsyncMock,
        return_value=["https://a.com/1", "https://b.com/2"],
    ) as mock_fetch:
        urls = await repo.get_synced_distribution_urls()
        assert urls == ["https://a.com/1", "https://b.com/2"]
        mock_fetch.assert_called_once_with(mock_db)


@pytest.mark.asyncio
async def test_get_synced_url_exists():
    mock_db = AsyncMock()
    repo = GeoflowRepository(mock_db)
    with patch(
        "app.integration.geoflow.repository.fetch_synced_url_exists",
        new_callable=AsyncMock,
        return_value=True,
    ) as mock_fetch:
        result = await repo.get_synced_url_exists("https://a.com/1")
        assert result is True
        mock_fetch.assert_called_once_with(mock_db, "https://a.com/1")


@pytest.mark.asyncio
async def test_get_distribution_by_ids_returns_dtos():
    mock_db = AsyncMock()
    repo = GeoflowRepository(mock_db)
    fake_rows = [_fake_dist_row(id=1), _fake_dist_row(id=2)]
    with patch(
        "app.integration.geoflow.repository.fetch_distribution_by_ids",
        new_callable=AsyncMock,
        return_value=fake_rows,
    ):
        dtos = await repo.get_distribution_by_ids([1, 2])
        assert len(dtos) == 2
        assert all(isinstance(d, DistributionDTO) for d in dtos)
        assert dtos[0].id == 1
        assert dtos[1].id == 2


@pytest.mark.asyncio
async def test_get_distribution_by_ids_empty():
    mock_db = AsyncMock()
    repo = GeoflowRepository(mock_db)
    dtos = await repo.get_distribution_by_ids([])
    assert dtos == []


@pytest.mark.asyncio
async def test_get_distribution_count_by_date_returns_dict():
    mock_db = AsyncMock()
    repo = GeoflowRepository(mock_db)
    start = datetime(2026, 7, 28, tzinfo=timezone.utc)
    fake_rows = [
        (datetime(2026, 7, 28, tzinfo=timezone.utc), 5),
        (datetime(2026, 7, 29, tzinfo=timezone.utc), 3),
    ]
    with patch(
        "app.integration.geoflow.repository.fetch_distribution_count_by_date",
        new_callable=AsyncMock,
        return_value=fake_rows,
    ):
        result = await repo.get_distribution_count_by_date(start)
        assert isinstance(result, dict)
        assert result[datetime(2026, 7, 28, tzinfo=timezone.utc)] == 5
        assert result[datetime(2026, 7, 29, tzinfo=timezone.utc)] == 3


@pytest.mark.asyncio
async def test_get_distributions_with_article_returns_composite_dtos():
    mock_db = AsyncMock()
    repo = GeoflowRepository(mock_db)
    fake_rows = [
        (_fake_dist_row(), _fake_article_row(), _fake_channel_row()),
        (_fake_dist_row(id=2, article_id=None), None, None),
    ]
    with patch(
        "app.integration.geoflow.repository.fetch_distributions_with_article",
        new_callable=AsyncMock,
        return_value=fake_rows,
    ):
        dtos = await repo.get_distributions_with_article()
        assert len(dtos) == 2
        assert isinstance(dtos[0], DistributionWithArticleDTO)
        assert dtos[0].distribution.id == 1
        assert dtos[0].article.id == 100
        assert dtos[0].channel.id == 5
        assert dtos[1].article is None
        assert dtos[1].channel is None


@pytest.mark.asyncio
async def test_get_distributions_with_article_passes_date_filter():
    mock_db = AsyncMock()
    repo = GeoflowRepository(mock_db)
    start = datetime(2026, 7, 1, tzinfo=timezone.utc)
    end = datetime(2026, 7, 31, tzinfo=timezone.utc)
    with patch(
        "app.integration.geoflow.repository.fetch_distributions_with_article",
        new_callable=AsyncMock,
        return_value=[],
    ) as mock_fetch:
        await repo.get_distributions_with_article(date_from=start, date_to=end)
        mock_fetch.assert_called_once_with(mock_db, date_from=start, date_to=end)


@pytest.mark.asyncio
async def test_get_deleted_distributions_with_article():
    mock_db = AsyncMock()
    repo = GeoflowRepository(mock_db)
    fake_rows = [
        (_fake_dist_row(action="delete"), _fake_article_row(), _fake_channel_row()),
    ]
    with patch(
        "app.integration.geoflow.repository.fetch_deleted_distributions_with_article",
        new_callable=AsyncMock,
        return_value=fake_rows,
    ):
        dtos = await repo.get_deleted_distributions_with_article()
        assert len(dtos) == 1
        assert dtos[0].distribution.action == "delete"
        assert dtos[0].article is not None
