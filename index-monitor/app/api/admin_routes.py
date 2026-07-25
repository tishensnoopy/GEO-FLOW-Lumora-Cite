# index-monitor/app/api/admin_routes.py
"""管理员端点：客户生命周期 + 站点管理 + 手动录入 + 批量检测。

设计文档第 9 节。前缀 /api/v1/admin。
"""
import uuid
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, EmailStr
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_admin, get_current_user
from app.core.database import get_db
from app.core.security import hash_password, verify_password
from app.models.admin_audit_log import AdminAuditLog
from app.models.client import Client, ClientSite
from app.models.citation_result import CitationResult
from app.models.index_result import IndexResult
from app.services.audit_log import AuditLogService
from app.services.distribution_query import DistributionQueryService
from app.utils.validators import validate_password_strength, normalize_domain

router = APIRouter(prefix="/admin", tags=["admin"])

# 手动录入端点专用 router：不挂 /admin 前缀（设计文档第 9 节：POST /distributions）
# 但仍走 admin 鉴权（Depends(get_current_admin)）。
# 控制者裁定：测试期望 POST /api/v1/distributions（无 /admin），GET /api/v1/admin/distributions
# （有 /admin），故两个端点分别挂在不同 router 上。
distribution_router = APIRouter(tags=["distributions"])


# ---------- Request Models ----------

class CreateClientRequest(BaseModel):
    client_id: str
    username: str
    password: str
    company_name: Optional[str] = None
    contact_name: Optional[str] = None
    contact_email: Optional[EmailStr] = None
    contact_phone: Optional[str] = None


class UpdateClientRequest(BaseModel):
    status: Optional[str] = None  # active/inactive/deleted
    company_name: Optional[str] = None
    contact_name: Optional[str] = None
    contact_email: Optional[EmailStr] = None
    contact_phone: Optional[str] = None
    password: Optional[str] = None  # 重置密码


class CreateClientSiteRequest(BaseModel):
    client_id: str
    site_name: str
    domain: str
    site_type: str = "official"
    has_wordpress: bool = False


class ManualDistributionRequest(BaseModel):
    remote_url: str
    client_id: Optional[str] = None
    note: Optional[str] = None


class ResetPasswordRequest(BaseModel):
    new_password: str


# ---------- Client Lifecycle ----------

@router.post("/clients", status_code=201)
async def create_client(
    req: CreateClientRequest,
    admin: dict = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """创建客户账号。"""
    validate_password_strength(req.password)

    # 检查 client_id 唯一
    existing = await db.execute(select(Client).where(Client.client_id == req.client_id))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="client_id 已存在")

    # 检查 username 唯一（DB 层 UNIQUE 约束，预先检查避免 IntegrityError）
    existing_username = await db.execute(
        select(Client).where(Client.username == req.username)
    )
    if existing_username.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="username 已存在")

    # 检查 email 唯一
    if req.contact_email:
        existing_email = await db.execute(
            select(Client).where(Client.contact_email == req.contact_email)
        )
        if existing_email.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="contact_email 已存在")

    client = Client(
        client_id=req.client_id,
        username=req.username,
        password_hash=hash_password(req.password),
        company_name=req.company_name,
        contact_name=req.contact_name,
        contact_email=req.contact_email,
        contact_phone=req.contact_phone,
        status="active",
    )
    db.add(client)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="数据冲突（唯一约束违反）")

    await AuditLogService.log(
        db, admin_user_id=admin["user_id"], admin_name=admin["name"],
        action="create_client", target_type="client", target_id=req.client_id,
        detail={"company_name": req.company_name},
    )

    return {
        "id": str(client.id),
        "client_id": client.client_id,
        "status": client.status,
    }


@router.get("/clients")
async def list_clients(
    include_deleted: bool = False,
    page: int = 1,
    page_size: int = 20,
    admin: dict = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """客户列表（分页）。"""
    query = select(Client)
    if not include_deleted:
        query = query.where(Client.status != "deleted")
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    clients = result.scalars().all()
    return {
        "items": [
            {
                "id": str(c.id),
                "client_id": c.client_id,
                "username": c.username,
                "company_name": c.company_name,
                "contact_name": c.contact_name,
                "contact_email": c.contact_email,
                "status": c.status,
                "last_login_at": c.last_login_at.isoformat() if c.last_login_at else None,
            }
            for c in clients
        ],
        "page": page,
        "page_size": page_size,
    }


@router.put("/clients/{client_id}")
async def update_client(
    client_id: str,
    req: UpdateClientRequest,
    admin: dict = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """更新客户（状态变更/重置密码/编辑信息）。"""
    result = await db.execute(select(Client).where(Client.client_id == client_id))
    client = result.scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=404, detail="客户不存在")

    old_status = client.status

    if req.status:
        if req.status not in ("active", "inactive", "deleted"):
            raise HTTPException(status_code=400, detail="无效状态")
        client.status = req.status
    if req.company_name is not None:
        client.company_name = req.company_name
    if req.contact_name is not None:
        client.contact_name = req.contact_name
    if req.contact_email is not None and req.contact_email != client.contact_email:
        # 唯一性检查：排除自身（Client.id != client.id），避免 TOCTOU 后触发 500
        existing_email = await db.execute(
            select(Client).where(
                Client.contact_email == req.contact_email,
                Client.id != client.id,
            )
        )
        if existing_email.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="contact_email 已被其他客户使用")
        client.contact_email = req.contact_email
    if req.contact_phone is not None:
        client.contact_phone = req.contact_phone
    if req.password:
        validate_password_strength(req.password)
        client.password_hash = hash_password(req.password)

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="数据冲突（唯一约束违反）")

    action_map = {"active": "restore_client", "inactive": "deactivate_client", "deleted": "delete_client"}
    if req.status and req.status != old_status:
        action = action_map.get(req.status, "update_client")
    else:
        action = "update_client"

    await AuditLogService.log(
        db, admin_user_id=admin["user_id"], admin_name=admin["name"],
        action=action, target_type="client", target_id=client_id,
        detail={"old_status": old_status, "new_status": client.status},
    )

    return {"client_id": client_id, "status": client.status}


@router.delete("/clients/{client_id}")
async def delete_client(
    client_id: str,
    admin: dict = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """软删除客户（status=deleted）。"""
    result = await db.execute(select(Client).where(Client.client_id == client_id))
    client = result.scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=404, detail="客户不存在")

    client.status = "deleted"
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="数据冲突（唯一约束违反）")

    await AuditLogService.log(
        db, admin_user_id=admin["user_id"], admin_name=admin["name"],
        action="delete_client", target_type="client", target_id=client_id,
    )

    return {"client_id": client_id, "status": "deleted"}


@router.put("/clients/{client_id}/password")
async def admin_reset_password(
    client_id: str,
    req: ResetPasswordRequest,
    admin: dict = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """admin 重置客户密码。不需旧密码，但记录审计日志。"""
    result = await db.execute(select(Client).where(Client.client_id == client_id))
    client = result.scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=404, detail="客户不存在")

    validate_password_strength(req.new_password)
    client.password_hash = hash_password(req.new_password)
    await db.commit()

    await AuditLogService.log(
        db, admin_user_id=admin["user_id"], admin_name=admin["name"],
        action="reset_client_password", target_type="client", target_id=client_id,
    )
    return {"message": f"客户 {client_id} 密码已重置"}


# ---------- Client Sites ----------

@router.post("/client_sites", status_code=201)
async def create_client_site(
    req: CreateClientSiteRequest,
    admin: dict = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """登记客户站点（domain 自动标准化去 www）。"""
    normalized = normalize_domain(req.domain)

    # 检查 domain 唯一
    existing = await db.execute(
        select(ClientSite).where(ClientSite.domain == normalized)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"domain '{normalized}' 已登记")

    site = ClientSite(
        client_id=req.client_id,
        site_name=req.site_name,
        domain=normalized,
        site_type=req.site_type,
        has_wordpress=req.has_wordpress,
        status="active",
    )
    db.add(site)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="数据冲突（唯一约束违反）")

    await AuditLogService.log(
        db, admin_user_id=admin["user_id"], admin_name=admin["name"],
        action="create_client_site", target_type="client_site",
        target_id=str(site.id),
        detail={"client_id": req.client_id, "domain": normalized},
    )

    return {"id": str(site.id), "domain": normalized}


# ---------- Manual Distribution + Distribution Query ----------

# POST /distributions：手动录入端点不挂 /admin 前缀（设计文档第 9 节）
# 挂在 distribution_router（无 prefix），实际路径 /api/v1/distributions
@distribution_router.post("/distributions", status_code=201)
async def create_manual_distribution(
    req: ManualDistributionRequest,
    admin: dict = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """运营手动录入 URL。"""
    service = DistributionQueryService(db)
    result = await service.create_manual_distribution(
        remote_url=req.remote_url,
        admin_user_id=admin["user_id"],
        admin_name=admin["name"],
        client_id=req.client_id,
        note=req.note,
    )
    await AuditLogService.log(
        db, admin_user_id=admin["user_id"], admin_name=admin["name"],
        action="manual_create_distribution", target_type="distribution",
        detail={"url": req.remote_url, "client_id": result.get("client_id")},
    )
    return result


# GET /distributions：client 查询自己的分发记录（D04 修复）
# 挂在 distribution_router（无 prefix），实际路径 /api/v1/distributions
# admin 应使用 GET /admin/distributions（跨客户视图）
@distribution_router.get("/distributions")
async def list_client_distributions(
    user_client: tuple = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """client 查看自己的分发记录（按 client_id 过滤）。

    用 get_current_user 统一鉴权，client 角色按 user.client_id 过滤；
    非 client 角色（admin）返回 403，引导其走 /admin/distributions。
    """
    user, role = user_client
    if role != "client":
        raise HTTPException(
            status_code=403,
            detail="本端点仅供客户使用；admin 请用 /admin/distributions",
        )

    service = DistributionQueryService(db)
    items = await service.list_distributions(client_id=user.client_id)
    return {"items": items, "total": len(items)}


# GET /admin/distributions：admin 查询所有分发记录（跨客户），挂在原 router 上
# C10 修复：新增 date_from / date_to 查询参数，透传给 list_distributions
@router.get("/distributions")
async def list_distributions(
    client_id: Optional[str] = None,
    source: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    admin: dict = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """admin 查看所有分发记录（跨客户）。

    支持按 client_id / source / date_from / date_to 过滤。
    日期范围与导出报告一致（C10 修复）。
    """
    service = DistributionQueryService(db)
    items = await service.list_distributions(
        client_id=client_id,
        source=source,
        date_from=date_from,
        date_to=date_to,
    )
    return {"items": items, "total": len(items)}


class BatchScanRequest(BaseModel):
    distribution_ids: list[str]
    scan_type: str  # 'index' | 'citation' | 'both'


@router.post("/distributions/batch-scan")
async def batch_scan(
    req: BatchScanRequest,
    admin: dict = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """批量触发检测。设计文档第 9.1 节。"""
    if req.scan_type not in ("index", "citation", "both"):
        raise HTTPException(status_code=400, detail="scan_type 必须是 index/citation/both")

    if not req.distribution_ids:
        raise HTTPException(status_code=400, detail="distribution_ids 不能为空")

    await AuditLogService.log(
        db, admin_user_id=admin["user_id"], admin_name=admin["name"],
        action="batch_scan",
        detail={"ids": req.distribution_ids, "type": req.scan_type},
    )

    # 实际检测入队逻辑在 M4 定时任务/后台任务中实现
    # 此处只返回入队确认（异步处理）
    return {"queued": len(req.distribution_ids), "scan_type": req.scan_type}


@router.get("/audit_logs")
async def list_audit_logs(
    page: int = 1,
    page_size: int = 50,
    action: Optional[str] = None,
    admin: dict = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """审计日志列表。admin 看自己，super_admin 看所有。设计文档第 10 节。"""
    # D15 修复：先查 total（与分页查询同样过滤条件）
    count_query = select(func.count()).select_from(AdminAuditLog)
    if admin["role"] != "super_admin":
        count_query = count_query.where(AdminAuditLog.admin_user_id == admin["user_id"])
    if action:
        count_query = count_query.where(AdminAuditLog.action == action)
    total = (await db.execute(count_query)).scalar()

    query = select(AdminAuditLog)

    # 权限隔离：普通 admin 只看自己的日志
    if admin["role"] != "super_admin":
        query = query.where(AdminAuditLog.admin_user_id == admin["user_id"])

    if action:
        query = query.where(AdminAuditLog.action == action)

    query = query.order_by(AdminAuditLog.created_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)

    result = await db.execute(query)
    logs = result.scalars().all()

    return {
        "items": [
            {
                "id": str(log.id),
                "admin_user_id": log.admin_user_id,
                "admin_name": log.admin_name,
                "action": log.action,
                "target_type": log.target_type,
                "target_id": log.target_id,
                "detail": log.detail,
                "created_at": log.created_at.isoformat() if log.created_at else None,
            }
            for log in logs
        ],
        "page": page,
        "page_size": page_size,
        "total": total,  # D15 修复
    }


# ---------- Admin Stats ----------
#
# C7 修复（整分支代码审查发现）：
# 原 /stats/citation 端点用 get_current_client_id（client JWT 鉴权），
# admin JWT 用 SSO_JWT_SECRET 签发 → decode_token 必抛 InvalidTokenError → 401，
# 导致 Dashboard.vue 静默回退 citation_count=0。
# 本端点用 get_current_admin 鉴权，提供 admin 全量聚合视图。
# 聚合口径与 /stats/citation 对齐：total = 全部采信记录数，cited = hit_type != "none"。
@router.get("/stats/citation")
async def get_admin_citation_stats(
    client_id: Optional[str] = None,
    admin: dict = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """admin 获取采信统计（全量聚合，可按 client_id 过滤）。

    - 无 client_id：跨所有客户聚合（admin 全局视图）
    - 有 client_id：只统计该客户的 URL 对应的采信记录

    返回 ``{"total": N, "cited": M}``，其中 ``cited`` = hit_type != "none"。
    """
    # 基础查询：CitationResult 全量
    base_query = select(CitationResult)
    if client_id:
        # 按 client_id 过滤：限定 URL 属于该客户的 IndexResult.url 集合
        url_subquery = select(IndexResult.url).where(IndexResult.client_id == client_id)
        base_query = base_query.where(CitationResult.url.in_(url_subquery))

    rows = (await db.execute(base_query)).scalars().all()
    total = len(rows)
    cited = sum(1 for r in rows if r.hit_type != "none")
    return {"total": total, "cited": cited}
