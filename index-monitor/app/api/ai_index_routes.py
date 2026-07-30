# index-monitor/app/api/ai_index_routes.py
"""AI 收录检测路由（运营端）。

触发检测 + 查询结果 + 统计。
"""
import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, case
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_admin
from app.core.database import get_db, async_session
from app.models.ai_index_result import AIIndexResult
from app.services.ai_index_checker import AIIndexChecker
from app.services.scan_lock import acquire_scan_lock, release_scan_lock, is_scan_locked
from app.services.scan_task_manager import create_task, complete_task

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/admin/ai-index/scan")
async def trigger_ai_index_scan(
    admin: dict = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """批量增量 AI 收录检测（仅 pending URL×模型组合）。"""
    if await is_scan_locked(db, "ai_index"):
        raise HTTPException(status_code=409, detail="已有 AI 收录扫描在运行，请等待完成")

    checker = AIIndexChecker(db)
    pending = await checker.get_pending_urls()
    if not pending:
        return {"task_id": None, "queued": 0, "message": "无待检测的 URL×模型组合"}

    task_id = create_task("ai_index", len(pending), pending)
    asyncio.create_task(_run_ai_index_scan_background(task_id))

    return {
        "task_id": task_id,
        "queued": len(pending),
        "message": f"已开始检测 {len(pending)} 个组合，结果将异步更新",
    }


async def _run_ai_index_scan_background(task_id: str) -> None:
    """后台执行 AI 收录检测。"""
    async with async_session() as db:
        if not await acquire_scan_lock(db, "ai_index"):
            logger.warning("AI 收录扫描后台任务：获取锁失败，跳过")
            return
        try:
            checker = AIIndexChecker(db)
            await checker.check_all_pending(task_id=task_id)
            complete_task(task_id)
        except Exception as exc:
            logger.error("AI 收录扫描后台任务失败: %s", exc)
        finally:
            await release_scan_lock(db, "ai_index")


@router.post("/admin/ai-index/scan/{url:path}")
async def trigger_ai_index_rescan(
    url: str,
    admin: dict = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """单 URL 重新检测（覆盖旧结果）。"""
    checker = AIIndexChecker(db)
    models = checker._get_configured_models()
    if not models:
        raise HTTPException(status_code=400, detail="未配置任何 AI 模型 API Key")

    task_id = create_task("ai_index", len(models), [(url, "", m) for m in models])
    asyncio.create_task(_run_ai_index_rescan_background(task_id, url, models))

    return {
        "task_id": task_id,
        "models_count": len(models),
        "message": f"已开始重新检测 {url}（{len(models)} 个模型）",
    }


async def _run_ai_index_rescan_background(task_id: str, url: str, models: list[str]) -> None:
    """后台执行单 URL 重检。"""
    async with async_session() as db:
        checker = AIIndexChecker(db)
        for model in models:
            try:
                await checker.check_url(url, model, task_id=task_id)
            except Exception as exc:
                logger.error("单 URL 重检失败 %s [%s]: %s", url, model, exc)
        complete_task(task_id)


@router.get("/admin/ai-index/results")
async def list_ai_index_results(
    url: str | None = Query(None),
    model: str | None = Query(None),
    index_status: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    admin: dict = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """查询收录结果（全状态，可过滤）。"""
    stmt = select(AIIndexResult)
    if url:
        stmt = stmt.where(AIIndexResult.url == url)
    if model:
        stmt = stmt.where(AIIndexResult.model == model)
    if index_status:
        stmt = stmt.where(AIIndexResult.index_status == index_status)

    # 总数
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar() or 0

    # 分页
    stmt = stmt.order_by(AIIndexResult.created_at.desc()).offset(
        (page - 1) * page_size
    ).limit(page_size)
    result = await db.execute(stmt)
    items = [
        {
            "id": str(r.id),
            "url": r.url,
            "model": r.model,
            "index_status": r.index_status,
            "ai_response": r.ai_response,
            "checked_at": r.checked_at.isoformat() if r.checked_at else None,
        }
        for r in result.scalars().all()
    ]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/admin/ai-index/stats")
async def ai_index_stats(
    client_id: str | None = Query(None),
    admin: dict = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """收录统计（按模型/客户维度）。"""
    # 总体统计
    stmt = select(
        func.count(AIIndexResult.id).label("total"),
        func.sum(case((AIIndexResult.index_status == "indexed", 1), else_=0)).label("indexed"),
        func.sum(case((AIIndexResult.index_status == "not_indexed", 1), else_=0)).label("not_indexed"),
        func.sum(case((AIIndexResult.index_status == "pending", 1), else_=0)).label("pending"),
    )
    row = (await db.execute(stmt)).one()
    indexed = int(row.indexed or 0)
    not_indexed = int(row.not_indexed or 0)
    pending = int(row.pending or 0)
    total = int(row.total or 0)
    index_rate = indexed / (indexed + not_indexed) if (indexed + not_indexed) > 0 else 0

    # 按模型维度
    model_stmt = select(
        AIIndexResult.model,
        func.sum(case((AIIndexResult.index_status == "indexed", 1), else_=0)).label("indexed"),
        func.sum(case((AIIndexResult.index_status == "not_indexed", 1), else_=0)).label("not_indexed"),
        func.sum(case((AIIndexResult.index_status == "pending", 1), else_=0)).label("pending"),
    ).group_by(AIIndexResult.model)
    model_rows = (await db.execute(model_stmt)).all()
    by_model = []
    for m, idx, nidx, pend in model_rows:
        idx, nidx = int(idx or 0), int(nidx or 0)
        rate = idx / (idx + nidx) if (idx + nidx) > 0 else 0
        by_model.append({
            "model": m, "indexed": idx, "not_indexed": nidx,
            "pending": int(pend or 0), "rate": rate,
        })

    return {
        "total_combinations": total,
        "indexed": indexed,
        "not_indexed": not_indexed,
        "pending": pending,
        "index_rate": index_rate,
        "by_model": by_model,
    }
