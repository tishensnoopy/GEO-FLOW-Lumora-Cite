"""Mappers：raw row → DTO 映射测试。"""
from datetime import datetime, timezone
from types import SimpleNamespace

from app.integration.geoflow.dto import (
    ArticleDTO,
    DistributionChannelDTO,
    DistributionDTO,
    DistributionWithArticleDTO,
)
from app.integration.geoflow.mappers import (
    map_article_row,
    map_channel_row,
    map_distribution_row,
    map_join_row,
)


def _fake_dist_row(**overrides):
    base = SimpleNamespace(
        id=1,
        article_id=100,
        remote_url="https://example.com/a",
        status="synced",
        action="publish",
        distribution_channel_id=5,
        created_at=datetime(2026, 7, 29, tzinfo=timezone.utc),
    )
    base.__dict__.update(overrides)
    return base


def _fake_article_row(**overrides):
    base = SimpleNamespace(
        id=100,
        title="标题",
        slug="slug",
        excerpt="摘要",
        content="正文",
        keywords='["k1"]',
        meta_description="描述",
        original_keyword="关键词",
        published_at=datetime(2026, 7, 29, tzinfo=timezone.utc),
    )
    base.__dict__.update(overrides)
    return base


def _fake_channel_row(**overrides):
    base = SimpleNamespace(
        id=5,
        name="渠道",
        domain="example.com",
        channel_type="geoflow_agent",
    )
    base.__dict__.update(overrides)
    return base


def test_map_distribution_row_full():
    row = _fake_dist_row()
    dto = map_distribution_row(row)
    assert isinstance(dto, DistributionDTO)
    assert dto.id == 1
    assert dto.article_id == 100
    assert dto.remote_url == "https://example.com/a"


def test_map_distribution_row_none_fields():
    row = _fake_dist_row(article_id=None, distribution_channel_id=None)
    dto = map_distribution_row(row)
    assert dto.article_id is None
    assert dto.distribution_channel_id is None


def test_map_article_row_full():
    row = _fake_article_row()
    dto = map_article_row(row)
    assert isinstance(dto, ArticleDTO)
    assert dto.id == 100
    assert dto.title == "标题"
    assert dto.keywords == '["k1"]'


def test_map_article_row_none():
    dto = map_article_row(None)
    assert dto is None


def test_map_channel_row_full():
    row = _fake_channel_row()
    dto = map_channel_row(row)
    assert isinstance(dto, DistributionChannelDTO)
    assert dto.id == 5
    assert dto.channel_type == "geoflow_agent"


def test_map_channel_row_none():
    dto = map_channel_row(None)
    assert dto is None


def test_map_join_row_all_present():
    dist = _fake_dist_row()
    article = _fake_article_row()
    channel = _fake_channel_row()
    composite = map_join_row(dist, article, channel)
    assert isinstance(composite, DistributionWithArticleDTO)
    assert composite.distribution.id == 1
    assert composite.article.id == 100
    assert composite.channel.id == 5


def test_map_join_row_article_channel_none():
    dist = _fake_dist_row()
    composite = map_join_row(dist, None, None)
    assert composite.distribution.id == 1
    assert composite.article is None
    assert composite.channel is None
