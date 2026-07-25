# index-monitor/app/services/scan_rate_limiter.py
"""检测频率控制服务。

设计文档第 21.1 节。

规则：
1. 同一 URL 最小间隔 6 小时（SCAN_MIN_INTERVAL_HOURS）
2. 全局并发限制 5（SCAN_MAX_CONCURRENCY，用 asyncio.Semaphore）
3. 每客户每日 100 次（SCAN_DAILY_QUOTA_PER_CLIENT）
"""
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings


class ScanRateLimiter:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def check_url_scan_allowed(
        self,
        url: str,
        recent_checked_at: Optional[datetime] = None,
    ) -> dict:
        """检查 URL 是否允许检测（6 小时间隔）。

        Parameters
        ----------
        url : str
            待检测 URL。
        recent_checked_at : datetime | None
            最近一次检测时间。None = 无历史记录。

        Returns
        -------
        dict
            {"allowed": bool, "reason": str, "next_available_at": str | None}
        """
        if recent_checked_at is None:
            return {"allowed": True, "reason": "", "next_available_at": None}

        now = datetime.now(timezone.utc)
        min_interval = timedelta(hours=settings.SCAN_MIN_INTERVAL_HOURS)
        elapsed = now - recent_checked_at

        if elapsed < min_interval:
            next_available = recent_checked_at + min_interval
            return {
                "allowed": False,
                "reason": f"距上次检测不足 {settings.SCAN_MIN_INTERVAL_HOURS} 小时",
                "next_available_at": next_available.isoformat(),
            }

        return {"allowed": True, "reason": "", "next_available_at": None}

    async def enforce_url_scan(self, url: str, recent_checked_at: Optional[datetime] = None) -> None:
        """强制校验，不允许时抛 409。"""
        result = await self.check_url_scan_allowed(url, recent_checked_at)
        if not result["allowed"]:
            raise HTTPException(
                status_code=409,
                detail={
                    "detail": result["reason"],
                    "next_available_at": result["next_available_at"],
                },
            )


# 全局并发信号量（模块级单例，所有检测共享）
_scan_semaphore = asyncio.Semaphore(settings.SCAN_MAX_CONCURRENCY)


def get_scan_semaphore() -> asyncio.Semaphore:
    """获取全局检测并发信号量。"""
    return _scan_semaphore
