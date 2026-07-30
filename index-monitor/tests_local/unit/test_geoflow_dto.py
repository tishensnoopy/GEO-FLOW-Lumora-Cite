"""DTO 不可变性 + 字段定义测试。"""
from datetime import datetime, timezone

import pytest

from app.integration.geoflow.dto import (
    ArticleDTO,
    DistributionChannelDTO,
    DistributionDTO,
    DistributionWithArticleDTO,
)


def test_distribution_dto_fields():
    dto = DistributionDTO(
        id=1,
        article_id=100,
        remote_url="https://example.com/a",
        status="synced",
        action="publish",
        distribution_channel_id=5,
        created_at=datetime(2026, 7, 29, tzinfo=timezone.utc),
    )
    assert dto.id == 1
    assert dto.article_id == 100
    assert dto.remote_url == "https://example.com/a"
    assert dto.status == "synced"
    assert dto.action == "publish"
    assert dto.distribution_channel_id == 5
    assert dto.created_at == datetime(2026, 7, 29, tzinfo=timezone.utc)


def test_article_dto_fields():
    dto = ArticleDTO(
        id=100,
        title="标题",
        slug="slug",
        excerpt="摘要",
        content="正文",
        keywords='["k1","k2"]',
        meta_description="描述",
        original_keyword="关键词",
        published_at=datetime(2026, 7, 29, tzinfo=timezone.utc),
    )
    assert dto.id == 100
    assert dto.title == "标题"
    assert dto.slug == "slug"
    assert dto.keywords == '["k1","k2"]'
    assert dto.published_at == datetime(2026, 7, 29, tzinfo=timezone.utc)


def test_distribution_channel_dto_fields():
    dto = DistributionChannelDTO(
        id=5,
        name="渠道",
        domain="example.com",
        channel_type="geoflow_agent",
    )
    assert dto.id == 5
    assert dto.name == "渠道"
    assert dto.domain == "example.com"
    assert dto.channel_type == "geoflow_agent"


def test_distribution_with_article_dto_composition():
    dist = DistributionDTO(
        id=1, article_id=100, remote_url="u", status="synced",
        action="publish", distribution_channel_id=5,
        created_at=datetime(2026, 7, 29, tzinfo=timezone.utc),
    )
    article = ArticleDTO(
        id=100, title="t", slug="s", excerpt=None, content=None,
        keywords=None, meta_description=None, original_keyword=None,
        published_at=None,
    )
    channel = DistributionChannelDTO(
        id=5, name="c", domain="d", channel_type="geoflow_agent",
    )
    composite = DistributionWithArticleDTO(
        distribution=dist, article=article, channel=channel,
    )
    assert composite.distribution.id == 1
    assert composite.article.title == "t"
    assert composite.channel.name == "c"


def test_dto_is_frozen():
    """DTO 不可变——修改字段应抛 FrozenInstanceError。"""
    dto = DistributionDTO(
        id=1, article_id=None, remote_url="u", status="s",
        action="a", distribution_channel_id=None,
        created_at=datetime(2026, 7, 29, tzinfo=timezone.utc),
    )
    with pytest.raises(Exception):  # dataclasses.FrozenInstanceError
        dto.id = 2


def test_dto_optional_fields_accept_none():
    """article_id、distribution_channel_id、article 各字段都可为 None。"""
    dist = DistributionDTO(
        id=1, article_id=None, remote_url="u", status="s",
        action="a", distribution_channel_id=None,
        created_at=datetime(2026, 7, 29, tzinfo=timezone.utc),
    )
    assert dist.article_id is None
    assert dist.distribution_channel_id is None

    composite = DistributionWithArticleDTO(
        distribution=dist, article=None, channel=None,
    )
    assert composite.article is None
    assert composite.channel is None
