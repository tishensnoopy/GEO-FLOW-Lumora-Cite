# index-monitor/app/services/scheduler.py
"""定时任务调度。

收录检测：每日 02:00（M1 Task 4 已有）
AI 采信检测：每日 03:00（修复：原缺失，导致采信数据不更新）
导出处理：每 30 秒扫 pending 导出任务（M4 补全，闭合 M3 审查缺口 1）

阶段 3 - ② / 阶段 4 - ①：定时任务接入 advisory lock + scan_task_manager。
- advisory lock 防止定时任务与手动扫描（/scan/trigger、batch-scan）重叠，
  拿不到锁则 warning 跳过，避免重复检测浪费 API 配额。
- scan_task_manager 记录任务进度，便于运维排查（定时任务无前端活动窗口，
  但 task 状态仍可在内存中查询，且日志写入 citation_check_logs 持久化）。

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
from app.services.scan_lock import acquire_scan_lock, release_scan_lock
from app.services.scan_task_manager import create_task, complete_task
from app.models.export_task import ExportTask

logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler()


async def scheduled_index_check():
    """每日 02:00 收录检测。

    阶段 3 - ②：advisory lock 互斥，拿不到锁则跳过（手动扫描可能正在运行）。
    阶段 4 - ①：创建 scan_task_manager 任务，透传 task_id 写进度日志。
    """
    async with async_session() as db:
        if not await acquire_scan_lock(db, "index"):
            logger.warning("已有收录扫描在运行，定时任务跳过以避免重复检测")
            return
        try:
            checker = IndexChecker(db)
            pending = await checker.get_pending_urls()
            if not pending:
                logger.info("收录检测：无待检测 URL")
                return
            task_id = create_task("index", len(pending), pending)
            logger.info("收录检测定时任务启动：共 %d 条（task_id=%s）", len(pending), task_id)
            await checker.check_all_pending(task_id=task_id)
            complete_task(task_id)
        finally:
            await release_scan_lock(db, "index")


async def scheduled_citation_check():
    """每日 03:00 AI 采信检测。

    修复：原 scheduler 未注册采信检测定时任务，导致：
    1. citation_results 表长期无新数据，Dashboard 采信统计始终为 0
    2. batch_scan 是占位符（已在 admin_routes.py 修复），即便手动触发也不执行
    现补全定时任务，每日 03:00（在收录检测 02:00 之后）扫描所有待检测 URL。

    阶段 3 - ②：advisory lock 互斥，拿不到锁则跳过。
    阶段 4 - ①：创建 scan_task_manager 任务，透传 task_id 写 5 阶段进度 + 模型 probe 状态。
    """
    from app.services.citation_checker import CitationChecker
    async with async_session() as db:
        if not await acquire_scan_lock(db, "citation"):
            logger.warning("已有采信扫描在运行，定时任务跳过以避免重复检测")
            return
        try:
            checker = CitationChecker(db)
            pending = await checker.get_pending_urls()
            if not pending:
                logger.info("采信检测：无待检测 URL")
                return
            task_id = create_task("citation", len(pending), pending)
            logger.info("采信检测定时任务启动：共 %d 条（task_id=%s）", len(pending), task_id)
            result = await checker.check_all_pending(task_id=task_id)
            complete_task(task_id)
            logger.info(
                "采信检测完成：共 %d 条，成功 %d，失败 %d",
                result["total"], result["success"], result["failed"],
            )
        finally:
            await release_scan_lock(db, "citation")


async def scheduled_ai_index_check():
    """每日 02:30 AI 收录检测（兜底 pending）。

    处理自动联动触发失败的 URL×模型组合。
    在搜索引擎收录检测（02:00）之后、采信检测（03:00）之前执行。
    """
    from app.services.ai_index_checker import AIIndexChecker
    async with async_session() as db:
        if not await acquire_scan_lock(db, "ai_index"):
            logger.warning("已有 AI 收录扫描在运行，定时任务跳过")
            return
        try:
            checker = AIIndexChecker(db)
            pending = await checker.get_pending_urls()
            if not pending:
                logger.info("AI 收录检测：无待检测组合")
                return
            task_id = create_task("ai_index", len(pending), pending)
            logger.info("AI 收录检测定时任务启动：共 %d 组合（task_id=%s）", len(pending), task_id)
            await checker.check_all_pending(task_id=task_id)
            complete_task(task_id)
        finally:
            await release_scan_lock(db, "ai_index")


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
    # AI 采信检测：每日 03:00（修复：原缺失）
    scheduler.add_job(
        scheduled_citation_check,
        CronTrigger(hour=3, minute=0),
        id="citation_check",
        replace_existing=True,
    )
    # AI 收录检测：每日 02:30（Phase 3 新增，兜底 pending）
    scheduler.add_job(
        scheduled_ai_index_check,
        CronTrigger(hour=2, minute=30),
        id="ai_index_check",
        replace_existing=True,
    )
    # 导出处理：每 30 秒扫 pending（M4 补全）
    scheduler.add_job(
        scheduled_export_processor,
        IntervalTrigger(seconds=30),
        id="export_processor",
        replace_existing=True,
    )
    # 归档扫描：每日 02:00 归档已删除的分发记录（任务 9 补丁，D03 增量追加）
    scheduler.add_job(
        scheduled_archive_scan,
        CronTrigger(hour=2, minute=0),
        id="archive_scan",
        replace_existing=True,
    )
    # 幂等启动：若 scheduler 已在运行（如测试中多次调用 start_scheduler），
    # 跳过 start() 避免 SchedulerAlreadyRunningError；add_job 已用 replace_existing=True 兜底。
    if not scheduler.running:
        scheduler.start()
        logger.info(
            "APScheduler 已启动：收录检测(每日 02:00) + AI 收录检测(每日 02:30) "
            "+ 采信检测(每日 03:00) + 导出处理(每 30 秒) + 归档扫描(每日 02:00)"
        )


def stop_scheduler():
    # wait=True：等待当前正在执行的任务完成后再关闭，避免定时任务被强制中断
    scheduler.shutdown(wait=True)


# D03 修复：增量追加 scheduled_archive_scan（不替换现有 scheduled_export_processor）。
# 控制者裁定 1：用 async_session（不是 async_session_factory，该符号不存在）。
# 控制者裁定 2：不实现 scheduled_monthly_archive（不在任务 9 范围）。
# 控制者裁定 5：timezone 已在 archive_service.py 顶部导入，本函数只需延迟导入
# ArchiveService 和 async_session。
async def scheduled_archive_scan():
    """每日 02:00 归档已删除的分发记录（任务 9 补丁）。

    查 action=='delete' 的 GEOFlow article_distributions 记录，按 remote_url 的 domain
    匹配 ClientSite.client_id，写入 monitor.archived_distributions 表。
    D01/D02/D06 修复详见 ArchiveService.archive_deleted_distributions。
    """
    # 延迟导入避免循环依赖
    from app.services.archive_service import ArchiveService

    # 注：async_session 已在文件顶部导入（from app.core.database import async_session），
    # 此处直接复用。控制者裁定 5 提到"延迟导入 async_session"——但既已在模块作用域，
    # 重复延迟导入会造成冗余，故直接使用。
    async with async_session() as db:
        service = ArchiveService(db)
        count = await service.archive_deleted_distributions()
        logger.info(f"归档扫描完成：归档 {count} 条已删除分发记录")
