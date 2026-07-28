"""GEOFlow schema 防腐层。

所有对 GEOFlow public schema 的直接 ORM 依赖集中在此包内。
调用方通过 GeoflowRepository 访问 GEOFlow 数据，操作 DTO 而非 ORM 模型。
"""
from app.integration.geoflow.dto import (
    ArticleDTO,
    DistributionChannelDTO,
    DistributionDTO,
    DistributionWithArticleDTO,
)
from app.integration.geoflow.repository import GeoflowRepository

__all__ = [
    "GeoflowRepository",
    "DistributionDTO",
    "ArticleDTO",
    "DistributionChannelDTO",
    "DistributionWithArticleDTO",
]
