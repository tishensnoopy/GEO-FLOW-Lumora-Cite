#!/usr/bin/env python3
"""回填脚本：为已有 index_results 记录抓取缺失的 content_title 和 content_snapshot。

使用方法（在 index-monitor 容器内执行）：
    python -m scripts.backfill_article_titles

或在宿主机：
    docker exec -it index-monitor python -m scripts.backfill_article_titles

修复背景：原 article_fetcher 使用 "Mozilla/5.0 (compatible; ZkeeeAIMonitor/1.0)"
UA 被多数网站屏蔽，导致 content_title 始终为空。本脚本用修复后的 UA 重新抓取。
"""
import asyncio
import logging
import sys
from pathlib import Path

# 确保能导入 app 包（容器内 /app 是工作目录，本地开发需加 path）
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select, update
from app.core.database import async_session
from app.models.index_result import IndexResult
from app.services.article_fetcher import article_fetcher

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("backfill")


async def backfill_titles():
    """为 content_title 为空的 index_results 记录抓取标题。"""
    async with async_session() as db:
        # 查找标题为空或 NULL 的记录
        result = await db.execute(
            select(IndexResult).where(
                (IndexResult.content_title.is_(None))
                | (IndexResult.content_title == "")
            )
        )
        records = result.scalars().all()

        total = len(records)
        logger.info("找到 %d 条待回填记录", total)

        if total == 0:
            logger.info("无需回填，所有记录都已有标题")
            return

        success = 0
        failed = 0

        for i, record in enumerate(records, 1):
            logger.info("[%d/%d] 抓取: %s", i, total, record.url)
            try:
                title, snapshot = await article_fetcher.fetch_title_and_snapshot(
                    record.url
                )
                if title:
                    update_data = {"content_title": title}
                    if snapshot:
                        update_data["content_snapshot"] = snapshot
                    await db.execute(
                        update(IndexResult)
                        .where(IndexResult.id == record.id)
                        .values(**update_data)
                    )
                    await db.commit()
                    success += 1
                    logger.info("  ✓ 标题: %s", title[:50])
                else:
                    failed += 1
                    logger.warning("  ✗ 未抓取到标题")
            except Exception as e:
                failed += 1
                logger.error("  ✗ 抓取失败: %s", e)
                await db.rollback()

            # 每条间隔 1 秒，避免请求过快
            await asyncio.sleep(1)

        logger.info("=" * 50)
        logger.info("回填完成：成功 %d / 失败 %d / 总计 %d", success, failed, total)


if __name__ == "__main__":
    asyncio.run(backfill_titles())
