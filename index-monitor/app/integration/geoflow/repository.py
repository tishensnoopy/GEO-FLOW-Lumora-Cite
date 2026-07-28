"""GEOFlow 仓储类——防腐层的对外接口。

调用方只使用 GeoflowRepository，不接触 reader/mappers/ORM 模型。
GEOFlow schema 变化时，只改 reader.py + mappers.py，此文件不动
（除非业务方法签名要调整）。
"""
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.integration.geoflow.dto import (
    DistributionDTO,
    DistributionWithArticleDTO,
)
from app.integration.geoflow.mappers import map_distribution_row, map_join_row
from app.integration.geoflow.reader import (
    fetch_deleted_distributions_with_article,
    fetch_distribution_by_ids,
    fetch_distribution_count_by_date,
    fetch_distributions_with_article,
    fetch_synced_distribution_urls,
    fetch_synced_url_exists,
)


class GeoflowRepository:
    """GEOFlow 数据只读仓储。所有方法都是 async，返回 DTO。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_synced_distribution_urls(self) -> list[str]:
        """取所有 synced 且非 delete 的 remote_url 列表。"""
        return await fetch_synced_distribution_urls(self.db)

    async def get_synced_url_exists(self, url: str) -> bool:
        """检查指定 url 是否已存在于 synced 且非 delete 的分发记录中。

        用精确查询替代全量列表拉取，适合单 URL 存在性判定。
        """
        return await fetch_synced_url_exists(self.db, url)

    async def get_distribution_by_ids(self, ids: list[int]) -> list[DistributionDTO]:
        """按 id 批量查分发记录，返回 DistributionDTO 列表。"""
        rows = await fetch_distribution_by_ids(self.db, ids)
        return [map_distribution_row(row) for row in rows]

    async def get_distribution_count_by_date(
        self, start_date: datetime
    ) -> dict[datetime, int]:
        """按天聚合 created_at，返回 {date: count} 字典。"""
        rows = await fetch_distribution_count_by_date(self.db, start_date)
        return {row[0]: int(row[1]) for row in rows}

    async def get_distributions_with_article(
        self,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> list[DistributionWithArticleDTO]:
        """三表 join 查询 synced 分发。不含 IndexResult——调用方自行 join。"""
        rows = await fetch_distributions_with_article(
            self.db, date_from=date_from, date_to=date_to
        )
        return [map_join_row(row[0], row[1], row[2]) for row in rows]

    async def get_deleted_distributions_with_article(
        self,
    ) -> list[DistributionWithArticleDTO]:
        """三表 join 查询 action='delete' 的分发。不含 ~exists 过滤——调用方自行处理。"""
        rows = await fetch_deleted_distributions_with_article(self.db)
        return [map_join_row(row[0], row[1], row[2]) for row in rows]
