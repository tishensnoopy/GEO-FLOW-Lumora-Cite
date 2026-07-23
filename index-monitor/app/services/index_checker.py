# index-monitor/app/services/index_checker.py
from datetime import datetime
from typing import List, Dict, Tuple
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.article import ArticleDistribution
from app.models.index_result import IndexResult, IndexHistory
from app.services.spider import spider

class IndexChecker:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.spider = spider

    async def get_pending_urls(self) -> List[Tuple[str, str]]:
        result = await self.db.execute(
            select(ArticleDistribution.remote_url, ArticleDistribution.client_id)
            .where(ArticleDistribution.status == "synced")
        )
        distributed = {row[0]: row[1] for row in result.fetchall()}

        result = await self.db.execute(select(IndexResult.url))
        checked_urls = {row[0] for row in result.fetchall()}

        return [(url, distributed[url]) for url in distributed if url not in checked_urls]

    async def check_url(self, url: str, client_id: str, site_type: str):
        results = await self.spider.check_all_engines(url)
        now = datetime.now()

        update_data = {
            "url": url,
            "client_id": client_id,
            "site_type": site_type,
            "baidu_status": "indexed" if results["baidu"] else "not_indexed",
            "toutiao_status": "indexed" if results["toutiao"] else "not_indexed",
            "sogou_status": "indexed" if results["sogou"] else "not_indexed",
            "so360_status": "indexed" if results["so360"] else "not_indexed",
            "bing_status": "indexed" if results["bing"] else "not_indexed",
            "baidu_checked_at": now if results["baidu"] else None,
            "toutiao_checked_at": now if results["toutiao"] else None,
            "sogou_checked_at": now if results["sogou"] else None,
            "so360_checked_at": now if results["so360"] else None,
            "bing_checked_at": now if results["bing"] else None,
        }

        existing = await self.db.execute(select(IndexResult).where(IndexResult.url == url))
        if existing.scalar_one_or_none():
            await self.db.execute(update(IndexResult).where(IndexResult.url == url).values(**update_data))
        else:
            self.db.add(IndexResult(**update_data))

        await self.db.commit()
        await self._record_history(url, results)

    async def _record_history(self, url: str, results: Dict[str, bool]):
        today = datetime.now().date()
        existing = await self.db.execute(
            select(IndexHistory).where(IndexHistory.url == url, IndexHistory.check_date == today)
        )
        if existing.scalar_one_or_none():
            return

        total_indexed = sum(1 for v in results.values() if v)
        self.db.add(IndexHistory(
            url=url, check_date=today,
            baidu_status="indexed" if results["baidu"] else "not_indexed",
            toutiao_status="indexed" if results["toutiao"] else "not_indexed",
            sogou_status="indexed" if results["sogou"] else "not_indexed",
            so360_status="indexed" if results["so360"] else "not_indexed",
            bing_status="indexed" if results["bing"] else "not_indexed",
            total_indexed=total_indexed
        ))
        await self.db.commit()

    async def check_all_pending(self):
        pending = await self.get_pending_urls()
        for url, client_id in pending:
            await self.check_url(url, client_id, "official")
