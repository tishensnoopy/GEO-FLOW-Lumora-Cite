# index-monitor/app/api/export_routes.py
"""导出端点：admin 导出全部 / 客户导出自己 / 下载。

设计文档第 12.3 节。
- POST /api/v1/admin/exports：admin 导出（可指定 client_id）
- POST /api/v1/exports：客户导出自己的数据
- GET /api/v1/exports：分页列出导出任务（admin 全部 / client 自己）
- GET /api/v1/exports/{task_id}：查询导出任务状态
- GET /api/v1/exports/{task_id}/download：下载已完成的导出文件

异步处理约定
============

本路由只负责创建 ``ExportTask`` 记录（status="pending"）并立即返回 202 +
``{"task_id": ..., "status": "pending"}``。实际导出处理由 ExportService
（M3 任务 4）实现，可通过后台调度器（M4）或单独触发调用——不在请求路径内
同步执行，避免长耗时导出阻塞 HTTP 响应。

权限隔离
========

- admin：可导出全部客户数据，可指定 ``client_id`` 限定单个客户；
- client：仅可导出 / 查询 / 下载自己的数据，跨客户访问返回 403。
"""
import os
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_admin, get_current_user
from app.core.database import get_db
from app.models.export_task import ExportTask
from app.services.audit_log import AuditLogService

router = APIRouter(tags=["exports"])


class ExportRequest(BaseModel):
    export_type: str  # 'pdf' | 'excel'
    client_id: Optional[str] = None
    # 用 date 而非 str：Pydantic 自动解析 ISO 字符串（"2026-07-01"）为 date 对象，
    # 直接传给 ExportTask.date_from（Date 列），asyncpg 原生支持 date 类型。
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    # charts：前端 ECharts getDataURL() 生成的 base64 数据 URL 字典。
    # 格式 {"trend": "data:image/png;base64,...", "pie": "..."}。
    # 设计文档第 12.4 节。None = 不带图表（向后兼容）。
    charts: Optional[dict] = None


@router.post("/admin/exports", status_code=202)
async def admin_create_export(
    req: ExportRequest,
    admin: dict = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """admin 触发导出（异步处理）。

    创建 ExportTask 记录（status="pending"），记审计日志后立即返回。
    实际导出处理由后台任务或单独触发调用 ExportService 完成。
    """
    if req.export_type not in ("pdf", "excel"):
        raise HTTPException(status_code=400, detail="export_type 必须是 pdf 或 excel")

    task = ExportTask(
        client_id=req.client_id,
        requested_by=admin["name"],
        requested_by_role="admin",
        export_type=req.export_type,
        date_from=req.date_from,
        date_to=req.date_to,
        charts=req.charts,
        status="pending",
    )
    db.add(task)
    await db.commit()

    await AuditLogService.log(
        db, admin_user_id=admin["user_id"], admin_name=admin["name"],
        action="create_export", target_type="export_task", target_id=str(task.id),
        detail={"export_type": req.export_type, "client_id": req.client_id},
    )

    return {"task_id": str(task.id), "status": "pending"}


@router.post("/exports", status_code=202)
async def client_create_export(
    req: ExportRequest,
    user_client: tuple = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """客户导出自己的数据。

    role != "client" → 403。client_id 强制取登录用户本身（忽略请求体里的
    client_id，防止越权导出他人数据）。
    """
    user, role = user_client
    if role != "client":
        raise HTTPException(status_code=403, detail="仅客户可调用此端点")

    if req.export_type not in ("pdf", "excel"):
        raise HTTPException(status_code=400, detail="export_type 必须是 pdf 或 excel")

    task = ExportTask(
        client_id=user.client_id,
        requested_by=user.client_id,
        requested_by_role="client",
        export_type=req.export_type,
        date_from=req.date_from,
        date_to=req.date_to,
        charts=req.charts,
        status="pending",
    )
    db.add(task)
    await db.commit()

    return {"task_id": str(task.id), "status": "pending"}


@router.get("/exports")
async def list_export_tasks(
    page: int = 1,
    page_size: int = 20,
    user_client: tuple = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """列出导出任务（分页）。admin 看所有，client 只看自己的。"""
    user, role = user_client
    query = select(ExportTask)
    if role == "client":
        query = query.where(ExportTask.client_id == user.client_id)
    query = query.order_by(ExportTask.created_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    tasks = result.scalars().all()
    return {
        "items": [
            {
                "task_id": str(t.id),
                "export_type": t.export_type,
                "status": t.status,
                "client_id": t.client_id,
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "completed_at": t.completed_at.isoformat() if t.completed_at else None,
                "file_size": t.file_size,
            }
            for t in tasks
        ],
        "page": page,
        "page_size": page_size,
    }


@router.get("/exports/{task_id}")
async def get_export_status(
    task_id: str,
    user_client: tuple = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """查询导出任务状态。admin 可查所有，client 只查自己的（403 隔离）。"""
    result = await db.execute(select(ExportTask).where(ExportTask.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="导出任务不存在")

    user, role = user_client
    if role == "client" and task.client_id != user.client_id:
        raise HTTPException(status_code=403, detail="无权查看此任务")

    # 安全：不返回服务器内部 file_path（绝对路径），避免信息泄露。
    # 前端通过 GET /exports/{task_id}/download 下载文件，无需知道路径。
    # file_size 仅在完成时返回，供前端展示文件大小。
    return {
        "task_id": str(task.id),
        "status": task.status,
        "export_type": task.export_type,
        "file_size": task.file_size if task.status == "completed" else None,
        "error_message": task.error_message,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
    }


@router.get("/exports/{task_id}/download")
async def download_export(
    task_id: str,
    user_client: tuple = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """下载已完成的导出文件。client 只下载自己的（403 隔离）。"""
    result = await db.execute(select(ExportTask).where(ExportTask.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="导出任务不存在")

    user, role = user_client
    if role == "client" and task.client_id != user.client_id:
        raise HTTPException(status_code=403, detail="无权下载此文件")

    if task.status != "completed":
        raise HTTPException(status_code=400, detail=f"任务状态：{task.status}，无法下载")

    if not task.file_path or not os.path.exists(task.file_path):
        raise HTTPException(status_code=404, detail="导出文件不存在")

    return FileResponse(
        task.file_path,
        media_type="application/octet-stream",
        filename=os.path.basename(task.file_path),
    )
