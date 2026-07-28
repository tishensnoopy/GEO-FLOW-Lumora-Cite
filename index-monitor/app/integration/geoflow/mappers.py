"""Raw ORM row → DTO 映射函数。

把字段访问集中在这里——GEOFlow 改字段名时只改此文件，
DTO 定义和调用方都不动。
"""
from app.integration.geoflow.dto import (
    ArticleDTO,
    DistributionChannelDTO,
    DistributionDTO,
    DistributionWithArticleDTO,
)


def map_distribution_row(row) -> DistributionDTO:
    """单条 article_distributions 行 → DistributionDTO。"""
    return DistributionDTO(
        id=row.id,
        article_id=row.article_id,
        remote_url=row.remote_url,
        status=row.status,
        action=row.action,
        distribution_channel_id=row.distribution_channel_id,
        created_at=row.created_at,
    )


def map_article_row(row) -> ArticleDTO | None:
    """articles 行 → ArticleDTO。row 为 None 时返回 None（outer join 场景）。"""
    if row is None:
        return None
    return ArticleDTO(
        id=row.id,
        title=row.title,
        slug=row.slug,
        excerpt=row.excerpt,
        content=row.content,
        keywords=row.keywords,
        meta_description=row.meta_description,
        original_keyword=row.original_keyword,
        published_at=row.published_at,
    )


def map_channel_row(row) -> DistributionChannelDTO | None:
    """distribution_channels 行 → DistributionChannelDTO。row 为 None 时返回 None。"""
    if row is None:
        return None
    return DistributionChannelDTO(
        id=row.id,
        name=row.name,
        domain=row.domain,
        channel_type=row.channel_type,
    )


def map_join_row(dist_row, article_row, channel_row) -> DistributionWithArticleDTO:
    """三表 join 的三行 → DistributionWithArticleDTO。"""
    return DistributionWithArticleDTO(
        distribution=map_distribution_row(dist_row),
        article=map_article_row(article_row),
        channel=map_channel_row(channel_row),
    )
