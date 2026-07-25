# index-monitor/tests/unit/test_scheduler.py
"""scheduler 定时任务测试。

验证 M3 审查缺口 1 的触发器：start_scheduler 注册 export_processor 任务。
不直接调用 scheduled_export_processor（依赖 async_session 上下文，集成测试覆盖）。
"""
from app.services.scheduler import start_scheduler, scheduler


def test_start_scheduler_registers_export_processor():
    """start_scheduler 注册了 export_processor 定时任务（每 30 秒扫 pending）。"""
    # 清空已有任务（避免重复注册抛错）
    scheduler.remove_all_jobs()

    start_scheduler()

    job_ids = [job.id for job in scheduler.get_jobs()]
    assert "index_check" in job_ids, "收录检测定时任务未注册"
    assert "export_processor" in job_ids, "导出处理定时任务未注册"

    # 验证 export_processor 的触发器是 IntervalTrigger（每 30 秒）
    export_job = scheduler.get_job("export_processor")
    assert export_job is not None
    assert export_job.trigger.__class__.__name__ == "IntervalTrigger"
    assert export_job.trigger.interval.total_seconds() == 30


def test_start_scheduler_registers_index_check():
    """start_scheduler 仍注册 index_check 任务（每日 02:00，向后兼容）。"""
    scheduler.remove_all_jobs()
    start_scheduler()

    index_job = scheduler.get_job("index_check")
    assert index_job is not None
    assert index_job.trigger.__class__.__name__ == "CronTrigger"
