# index-monitor/tests/unit/test_scan_rate_limiter.py
"""检测频率控制测试。设计文档第 21.1 节。

规则：
- 同一 URL 6 小时内重复检测返回 409
- 全局并发限制 5
- 每客户每日 100 次
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.services.scan_rate_limiter import ScanRateLimiter


@pytest.mark.asyncio
async def test_scan_within_6h_returns_conflict(db_session):
    """6 小时内重复检测返回 409。"""
    limiter = ScanRateLimiter(db_session)
    # 模拟最近检测时间在 3 小时前
    from datetime import datetime, timedelta, timezone
    recent = datetime.now(timezone.utc) - timedelta(hours=3)

    result = await limiter.check_url_scan_allowed("https://example.com/test", recent_checked_at=recent)
    assert result["allowed"] is False
    assert "6" in result["reason"]


@pytest.mark.asyncio
async def test_scan_after_6h_allowed(db_session):
    """超过 6 小时允许检测。"""
    limiter = ScanRateLimiter(db_session)
    from datetime import datetime, timedelta, timezone
    old = datetime.now(timezone.utc) - timedelta(hours=7)

    result = await limiter.check_url_scan_allowed("https://example.com/test", recent_checked_at=old)
    assert result["allowed"] is True


@pytest.mark.asyncio
async def test_scan_no_history_allowed(db_session):
    """无历史检测记录允许检测。"""
    limiter = ScanRateLimiter(db_session)
    result = await limiter.check_url_scan_allowed("https://example.com/new", recent_checked_at=None)
    assert result["allowed"] is True
