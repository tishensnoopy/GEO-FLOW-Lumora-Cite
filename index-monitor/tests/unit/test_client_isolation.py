"""客户端隔离 + scheduler 单元测试。"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock


@pytest.mark.skip(reason="需要同步 session fixture，暂跳过")
def test_get_client_urls_filters_by_client(db_session_sync):
    """_get_client_urls 仅返回该客户的 URL。"""
    # 此测试需要同步 session fixture；如果没有可跳过
    pass


@pytest.mark.asyncio
async def test_scheduled_ai_index_check_no_pending():
    """AI 收录检测定时任务：无 pending 时跳过。"""
    from app.services.scheduler import scheduled_ai_index_check

    with patch(
        "app.services.scheduler.async_session",
        new_callable=MagicMock,
    ) as mock_session_factory:
        mock_db = AsyncMock()
        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_session_factory.return_value = mock_session

        with patch(
            "app.services.scheduler.acquire_scan_lock",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.services.scheduler.release_scan_lock",
            new_callable=AsyncMock,
        ), patch(
            "app.services.ai_index_checker.AIIndexChecker.get_pending_urls",
            new_callable=AsyncMock,
            return_value=[],
        ):
            await scheduled_ai_index_check()


@pytest.mark.asyncio
async def test_scheduled_ai_index_check_locked():
    """AI 收录检测定时任务：已有锁时跳过。"""
    from app.services.scheduler import scheduled_ai_index_check

    with patch(
        "app.services.scheduler.acquire_scan_lock",
        new_callable=AsyncMock,
        return_value=False,
    ):
        await scheduled_ai_index_check()
