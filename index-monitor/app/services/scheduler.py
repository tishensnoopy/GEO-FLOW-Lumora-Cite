# index-monitor/app/services/scheduler.py
"""定时任务调度。

收录检测：每日 02:00（M1 Task 4 已有）
导出处理：每 30 秒扫 pending 导出任务（M4 补全，闭合 M3 审查缺口 1）

设计文档第 21.1 节 + M3 里程碑审查结论。
"""
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select

from app.core.database import async_session
from app.services.index_checker import IndexChecker
from app.services.export_service import ExportService
from app.models.export_task import ExportTask

logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler()


async def scheduled_index_check():
    """每日 02:00 收录检测。"""
    async with async_session() as db:
        checker = IndexChecker(db)
        await checker.check_all_pending()


async def scheduled_export_processor():
    """每 30 秒扫描 pending 导出任务并处理。

    闭合 M3 审查缺口 1：端点→ExportService 调用链断裂。
    端点只创建 pending 任务返回 202，实际处理由本调度器触发。

    单次最多处理 5 条（防止单轮过载），单条失败不影响其他任务。
    """
    async with async_session() as db:
        # 查 pending 任务（按创建时间升序，限 5 条）
        result = await db.execute(
            select(ExportTask)
            .where(ExportTask.status == "pending")
            .order_by(ExportTask.created_at.asc())
            .limit(5)
        )
        tasks = result.scalars().all()

        if not tasks:
            return

        service = ExportService(db)
        for task in tasks:
            try:
                await service.process_task(str(task.id))
            except Exception:
                # 单条失败不阻塞其他任务；ExportService.process_task 内部
                # 已记录 error_message + status=failed，此处仅兜底
                logger.exception(f"导出任务 {task.id} 处理失败")


def start_scheduler():
    # 收录检测：每日 02:00
    scheduler.add_job(
        scheduled_index_check,
        CronTrigger(hour=2, minute=0),
        id="index_check",
        replace_existing=True,
    )
    # 导出处理：每 30 秒扫 pending（M4 补全）
    scheduler.add_job(
        scheduled_export_processor,
        IntervalTrigger(seconds=30),
        id="export_processor",
        replace_existing=True,
    )
    # 幂等启动：若 scheduler 已在运行（如测试中多次调用 start_scheduler），
    # 跳过 start() 避免 SchedulerAlreadyRunningError；add_job 已用 replace_existing=True 兜底。
    if not scheduler.running:
        scheduler.start()
        logger.info(
            "APScheduler 已启动：收录检测(每日 02:00) + 导出处理(每 30 秒)"
        )


def stop_scheduler():
    # wait=True：等待当前正在执行的任务完成后再关闭，避免定时任务被强制中断
    scheduler.shutdown(wait=True)
