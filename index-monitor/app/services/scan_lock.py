# index-monitor/app/services/scan_lock.py
"""PG advisory lock 防止扫描任务重叠（阶段 3 - ②）。

背景
====
定时任务（scheduler）与手动扫描（/scan/trigger、batch-scan）都可能触发
``check_all_pending``。若同时运行，会重复检测同一批 URL，浪费 API 配额、
拖慢整体进度，还可能产生重复的 citation_results。

方案
====
用 PostgreSQL advisory lock 互斥：
- ``pg_try_advisory_lock(key)``：非阻塞获取，成功返回 True，已被占用返回 False
- 同一 scan_type 用同一 key，跨连接互斥
- 不同 scan_type 用不同 key，互不阻塞（收录与采信可并行）
- 锁绑定获取它的连接，session 关闭/连接归还时自动释放；显式 release 更可控

注意事项
========
acquire 和 release 必须在**同一个 session/连接**内调用，否则 release 找不到
锁持有者。调用方应在 ``async with async_session() as db:`` 块内 acquire →
执行扫描 → release。
"""
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# advisory lock 的 int64 key。不同 scan_type 用不同 key 避免互相阻塞。
# 0x5C414E = "SCAN" 的部分编码，前缀避免与他人冲突。
_LOCK_KEYS = {
    "index": 0x5C414E01,
    "citation": 0x5C414E02,
    "ai_index": 0x5C414E03,
}


async def acquire_scan_lock(db: AsyncSession, scan_type: str) -> bool:
    """尝试获取扫描 advisory lock。

    Returns
    -------
    bool
        True：获取成功，可执行扫描；
        False：已有同类型扫描在运行，应跳过本次。
        未知 scan_type：返回 True（不阻塞，不占用锁）。
    """
    key = _LOCK_KEYS.get(scan_type)
    if key is None:
        return True
    result = await db.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": key})
    return bool(result.scalar())


async def release_scan_lock(db: AsyncSession, scan_type: str) -> None:
    """释放扫描 advisory lock。

    必须与 acquire_scan_lock 在同一 session/连接内调用。
    """
    key = _LOCK_KEYS.get(scan_type)
    if key is None:
        return
    await db.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": key})


async def is_scan_locked(db: AsyncSession, scan_type: str) -> bool:
    """检查某 scan_type 的 advisory lock 是否已被持有（不获取锁）。

    用于手动触发端点（/scan/trigger）做同步预检：若已有同类型扫描在运行，
    立即返回 409，而非创建任务后再在后台跳过——给用户即时反馈。

    注意：单 bigint key 在 pg_locks 中按 (classid, objid) = (key>>32, key&0xFFFFFFFF)
    存储。本实现使用的 key 高 32 位均为 0，故 classid=0、objid=key。
    """
    key = _LOCK_KEYS.get(scan_type)
    if key is None:
        return False
    classid = key >> 32
    objid = key & 0xFFFFFFFF
    result = await db.execute(
        text(
            "SELECT EXISTS ("
            "  SELECT 1 FROM pg_locks"
            "  WHERE locktype = 'advisory' AND classid = :c AND objid = :o"
            ")"
        ),
        {"c": classid, "o": objid},
    )
    return bool(result.scalar())
