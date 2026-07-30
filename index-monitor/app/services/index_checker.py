# index-monitor/app/services/index_checker.py
import logging
from datetime import datetime, timezone
from typing import List, Dict, Tuple, Optional
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from app.integration.geoflow import GeoflowRepository
from app.models.manual_distribution import ManualDistribution
from app.models.index_result import IndexResult, IndexHistory
from app.models.client import ClientSite
from app.utils.validators import normalize_domain
from app.services.spider import spider
from app.services.article_fetcher import article_fetcher
from app.services.scan_task_manager import add_log, update_progress

logger = logging.getLogger(__name__)

class IndexChecker:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.spider = spider

    async def get_pending_urls(self) -> List[Tuple[str, str]]:
        """获取待检测 URL：GEOFlow 分发 + 手动录入，排除已检测。

        Returns
        -------
        list[tuple[str, str]]
            [(url, client_id), ...]
        """
        # 1. 查 GEOFlow 分发记录（通过防腐层）
        repo = GeoflowRepository(self.db)
        geoflow_urls = set(await repo.get_synced_distribution_urls())

        # 2. 查手动录入记录
        manual_result = await self.db.execute(
            select(ManualDistribution.remote_url, ManualDistribution.client_id)
            .where(ManualDistribution.status == "synced")
        )
        distributed: dict[str, str] = {}  # url → client_id

        # 手动录入直接有 client_id
        for url, client_id in manual_result.fetchall():
            distributed[url] = client_id

        # GEOFlow 分发通过 domain 匹配 client_sites
        sites_result = await self.db.execute(
            select(ClientSite).where(ClientSite.status == "active")
        )
        domain_map = {
            normalize_domain(s.domain): s.client_id
            for s in sites_result.scalars().all()
        }
        for url in geoflow_urls:
            domain = normalize_domain(url)
            client_id = domain_map.get(domain)
            if client_id:
                distributed.setdefault(url, client_id)  # GEOFlow 优先

        # 3. 排除已检测
        checked_result = await self.db.execute(select(IndexResult.url))
        checked_urls = {row[0] for row in checked_result.fetchall()}

        return [(url, cid) for url, cid in distributed.items() if url not in checked_urls]

    async def check_url(self, url: str, client_id: str, site_type: str):
        results = await self.spider.check_all_engines(url)
        now = datetime.now()

        # 抓取文章标题和内容快照
        title, snapshot = await article_fetcher.fetch_title_and_snapshot(url)

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
        # 填充标题和快照（抓取成功时）
        if title:
            update_data["content_title"] = title
        if snapshot:
            update_data["content_snapshot"] = snapshot

        existing = await self.db.execute(select(IndexResult).where(IndexResult.url == url))
        if existing.scalar_one_or_none():
            await self.db.execute(update(IndexResult).where(IndexResult.url == url).values(**update_data))
        else:
            self.db.add(IndexResult(**update_data))

        await self.db.commit()
        await self._record_history(url, results)

    async def _record_history(self, url: str, results: Dict[str, bool]):
        today = datetime.now(timezone.utc).date()
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

    async def check_all_pending(self, *, task_id: Optional[str] = None):
        """检测所有待检测 URL。

        阶段 4 - ①：新增 task_id 参数，供 /scan/trigger 异步入口透传，
        使收录扫描进度也能写入 scan_task_manager（ScanPanel 可展示）。
        task_id 为 None（定时任务）时不写活动窗口日志。
        单条失败不中断整体扫描，记入 failed 计数。
        """
        pending = await self.get_pending_urls()
        # 修复进度 >100%：用实际 pending 数更新 task.total（与 citation_checker 一致），
        # 避免 trigger_scan 的旧 total 与实际检测数不一致导致 ScanPanel 进度 >100%。
        if task_id:
            try:
                update_progress(task_id, total=len(pending))
            except Exception:  # noqa: BLE001
                pass
        processed = 0
        success = 0
        failed = 0
        for url, client_id in pending:
            try:
                await self.check_url(url, client_id, "official")
                success += 1
                if task_id:
                    add_log(task_id, "success", f"收录检测完成: {url}")
            except Exception as exc:  # noqa: BLE001 - 单条失败不中断整体扫描
                failed += 1
                logger.error("收录检测失败 %s: %s", url, exc)
                if task_id:
                    add_log(task_id, "error", f"收录检测失败 {url}: {exc}")
            processed += 1
            if task_id:
                try:
                    update_progress(task_id, processed=processed, success=success, failed=failed)
                except Exception:  # noqa: BLE001 - 进度更新失败不中断扫描
                    pass
