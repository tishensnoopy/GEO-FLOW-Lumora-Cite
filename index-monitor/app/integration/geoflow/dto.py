"""GEOFlow 数据传输对象。

DTO 只暴露 LumoraCite 实际消费的字段——GEOFlow 加新字段不影响，
删/改字段才触发契约测试失败。所有 DTO 都是 frozen dataclass。
"""
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class DistributionDTO:
    """article_distributions 表中 LumoraCite 实际消费的字段。"""
    id: int
    article_id: int | None
    remote_url: str
    status: str
    action: str
    distribution_channel_id: int | None
    created_at: datetime


@dataclass(frozen=True)
class ArticleDTO:
    """articles 表中 LumoraCite 实际消费的字段。"""
    id: int
    title: str | None
    slug: str | None
    excerpt: str | None
    content: str | None
    keywords: str | None  # TEXT 类型，LumoraCite 侧自行解析 JSON
    meta_description: str | None
    original_keyword: str | None
    published_at: datetime | None


@dataclass(frozen=True)
class DistributionChannelDTO:
    """distribution_channels 表中 LumoraCite 实际消费的字段。"""
    id: int
    name: str | None
    domain: str | None
    channel_type: str | None


@dataclass(frozen=True)
class DistributionWithArticleDTO:
    """三表 join 查询的复合 DTO（不含 IndexResult——那是 LumoraCite 自己的表）。"""
    distribution: DistributionDTO
    article: ArticleDTO | None
    channel: DistributionChannelDTO | None
