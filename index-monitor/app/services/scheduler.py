# index-monitor/app/services/scheduler.py
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from app.core.database import async_session
from app.services.index_checker import IndexChecker

scheduler = AsyncIOScheduler()

async def scheduled_index_check():
    async with async_session() as db:
        checker = IndexChecker(db)
        await checker.check_all_pending()

def start_scheduler():
    scheduler.add_job(
        scheduled_index_check,
        CronTrigger(hour=2, minute=0),
        id="index_check",
        replace_existing=True
    )
    scheduler.start()

def stop_scheduler():
    # wait=True：等待当前正在执行的任务完成后再关闭，避免 02:00 定时任务被强制中断
    scheduler.shutdown(wait=True)
