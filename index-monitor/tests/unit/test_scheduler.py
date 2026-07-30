# index-monitor/tests/unit/test_scheduler.py
"""scheduler 定时任务测试。

验证 M3 审查缺口 1 的触发器：start_scheduler 注册 export_processor 任务。
不直接调用 scheduled_export_processor（依赖 async_session 上下文，集成测试覆盖）。

测试设计：``start_scheduler`` 内部调用 ``AsyncIOScheduler.start()``，需要运行中的
事件循环。本模块用 ``@pytest.mark.asyncio`` 提供事件循环，并 mock ``scheduler.start``
避免真实启动调度器（否则定时任务会实际触发，干扰其他测试 + 污染 DB）。
``add_job`` 不依赖事件循环，可在 mock start 的情况下正常注册任务供断言。
"""
from unittest.mock import patch

import pytest

from app.services.scheduler import start_scheduler, scheduler


@pytest.mark.asyncio
async def test_start_scheduler_registers_export_processor():
    """start_scheduler 注册了 export_processor 定时任务（每 30 秒扫 pending）。"""
    # 清空已有任务（避免重复注册抛错）
    scheduler.remove_all_jobs()

    # mock start 避免 AsyncIOScheduler 真实启动（会触发定时任务 + 干扰其他测试）
    with patch.object(scheduler, "start"):
        start_scheduler()

    job_ids = [job.id for job in scheduler.get_jobs()]
    assert "index_check" in job_ids, "收录检测定时任务未注册"
    assert "export_processor" in job_ids, "导出处理定时任务未注册"

    # 验证 export_processor 的触发器是 IntervalTrigger（每 30 秒）
    export_job = scheduler.get_job("export_processor")
    assert export_job is not None
    assert export_job.trigger.__class__.__name__ == "IntervalTrigger"
    assert export_job.trigger.interval.total_seconds() == 30


@pytest.mark.asyncio
async def test_start_scheduler_registers_index_check():
    """start_scheduler 仍注册 index_check 任务（每日 02:00，向后兼容）。"""
    scheduler.remove_all_jobs()

    with patch.object(scheduler, "start"):
        start_scheduler()

    index_job = scheduler.get_job("index_check")
    assert index_job is not None
    assert index_job.trigger.__class__.__name__ == "CronTrigger"


@pytest.mark.asyncio
async def test_start_scheduler_registers_archive_scan():
    """start_scheduler 注册 archive_scan 任务（任务 9 补丁，每日 02:00 归档扫描）。

    验证 D03 修复：scheduler.py 增量追加 scheduled_archive_scan，不替换现有任务。
    """
    scheduler.remove_all_jobs()

    with patch.object(scheduler, "start"):
        start_scheduler()

    archive_job = scheduler.get_job("archive_scan")
    assert archive_job is not None, "归档扫描定时任务未注册（D03 修复未生效）"
    assert archive_job.trigger.__class__.__name__ == "CronTrigger"

    # 现有任务仍应存在（D03：增量追加，不替换）
    job_ids = [job.id for job in scheduler.get_jobs()]
    assert "index_check" in job_ids, "D03 增量追加破坏了现有 index_check"
    assert "export_processor" in job_ids, "D03 增量追加破坏了现有 export_processor"
    assert "archive_scan" in job_ids
