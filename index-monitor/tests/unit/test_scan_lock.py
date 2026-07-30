# index-monitor/tests/unit/test_scan_lock.py
"""scan_lock advisory lock 测试（阶段 3 - ②）。

验证目标：
1. acquire_scan_lock 首次获取成功
2. 同 scan_type 二次获取失败（互斥）
3. 不同 scan_type 不互斥
4. release_scan_lock 后可重新获取
5. 未知 scan_type 不阻塞（返回 True）

advisory lock 防止定时任务与手动扫描重叠，避免重复检测。
"""
import pytest
import pytest_asyncio


@pytest_asyncio.fixture(autouse=True)
async def _real_db():
    """advisory lock 是 PG 功能，需真实 DB 连接。"""
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
    from app.core.config import settings

    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        yield session_factory
    finally:
        # 清理可能残留的锁
        async with session_factory() as s:
            from app.services.scan_lock import release_scan_lock
            for st in ("index", "citation"):
                try:
                    await release_scan_lock(s, st)
                except Exception:
                    pass
            await s.commit()
        await engine.dispose()


@pytest.mark.asyncio
async def test_acquire_lock_first_time_succeeds(_real_db):
    from app.services.scan_lock import acquire_scan_lock, release_scan_lock
    async with _real_db() as db:
        got = await acquire_scan_lock(db, "citation")
        assert got is True
        await release_scan_lock(db, "citation")
        await db.commit()


@pytest.mark.asyncio
async def test_acquire_lock_second_time_fails(_real_db):
    """同 scan_type 二次获取应失败（互斥）。"""
    from app.services.scan_lock import acquire_scan_lock, release_scan_lock
    async with _real_db() as db1:
        assert await acquire_scan_lock(db1, "citation") is True
        async with _real_db() as db2:
            # 不同连接尝试获取同一锁，应失败
            got = await acquire_scan_lock(db2, "citation")
            assert got is False
        await release_scan_lock(db1, "citation")
        await db1.commit()


@pytest.mark.asyncio
async def test_different_scan_types_not_mutually_exclusive(_real_db):
    """不同 scan_type 不互斥。"""
    from app.services.scan_lock import acquire_scan_lock, release_scan_lock
    async with _real_db() as db:
        assert await acquire_scan_lock(db, "index") is True
        assert await acquire_scan_lock(db, "citation") is True
        await release_scan_lock(db, "index")
        await release_scan_lock(db, "citation")
        await db.commit()


@pytest.mark.asyncio
async def test_release_allows_reacquire(_real_db):
    """释放后可重新获取。"""
    from app.services.scan_lock import acquire_scan_lock, release_scan_lock
    async with _real_db() as db:
        assert await acquire_scan_lock(db, "citation") is True
        await release_scan_lock(db, "citation")
        await db.commit()
        # 释放后重新获取应成功
        assert await acquire_scan_lock(db, "citation") is True
        await release_scan_lock(db, "citation")
        await db.commit()


@pytest.mark.asyncio
async def test_unknown_scan_type_does_not_block(_real_db):
    """未知 scan_type 不阻塞（返回 True，不占用锁）。"""
    from app.services.scan_lock import acquire_scan_lock
    async with _real_db() as db:
        assert await acquire_scan_lock(db, "unknown_type") is True
