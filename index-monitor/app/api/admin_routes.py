# index-monitor/app/api/admin_routes.py
"""管理员端点：客户生命周期 + 站点管理 + 手动录入 + 批量检测。

设计文档第 9 节。前缀 /api/v1/admin。
"""
import asyncio
import logging
import uuid
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, EmailStr
from sqlalchemy import select, func, update, delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_admin, get_current_user
from app.core.database import get_db, async_session
from app.core.security import hash_password, verify_password
from app.models.admin_audit_log import AdminAuditLog
from app.models.client import Client, ClientSite
from app.models.citation_result import CitationResult
from app.models.geoflow_models import GeoflowArticleDistribution
from app.models.index_result import IndexResult
from app.models.manual_distribution import ManualDistribution
from app.services.audit_log import AuditLogService
from app.services.distribution_query import DistributionQueryService
from app.utils.validators import validate_password_strength, normalize_domain

logger = logging.getLogger(__name__)

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
    service_start_date: Optional[date] = None
    service_end_date: Optional[date] = None


class UpdateClientRequest(BaseModel):
    status: Optional[str] = None  # active/inactive/deleted
    company_name: Optional[str] = None
    contact_name: Optional[str] = None
    contact_email: Optional[EmailStr] = None
    contact_phone: Optional[str] = None
    password: Optional[str] = None  # 重置密码
    service_start_date: Optional[date] = None
    service_end_date: Optional[date] = None


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
        service_start_date=req.service_start_date,
        service_end_date=req.service_end_date,
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
                "service_start_date": c.service_start_date.isoformat() if c.service_start_date else None,
                "service_end_date": c.service_end_date.isoformat() if c.service_end_date else None,
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
    if req.service_start_date is not None:
        client.service_start_date = req.service_start_date
    if req.service_end_date is not None:
        client.service_end_date = req.service_end_date
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
    """运营手动录入 URL。添加后立即抓取文章标题。"""
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

    # 立即抓取文章标题，填充到 ManualDistribution 和 index_results（如果记录存在）
    try:
        from app.services.article_fetcher import article_fetcher
        from app.models.index_result import IndexResult
        title, snapshot = await article_fetcher.fetch_title_and_snapshot(req.remote_url)
        if title:
            # 修复：优先写入 ManualDistribution 记录本身（手动添加时 IndexResult 不存在）
            # 原逻辑只更新已存在的 IndexResult，导致标题被静默丢弃
            await db.execute(
                update(ManualDistribution)
                .where(ManualDistribution.id == result.get("id"))
                .values(content_title=title)
            )
            await db.commit()

            # 同步写入 IndexResult（确保文章列表立即可见）
            # 修复：原逻辑仅更新已存在的 IndexResult，手动添加时 IndexResult 不存在，
            # 导致文章列表（数据源为 index_results）看不到手动添加的记录。
            # 现改为：不存在则创建 pending 状态的新行，并异步触发收录扫描。
            existing = await db.execute(
                select(IndexResult).where(IndexResult.url == req.remote_url)
            )
            if existing.scalar_one_or_none():
                update_data = {"content_title": title}
                if snapshot:
                    update_data["content_snapshot"] = snapshot
                await db.execute(
                    update(IndexResult).where(IndexResult.url == req.remote_url).values(**update_data)
                )
                await db.commit()
            else:
                # 创建新的 IndexResult 行（pending 状态），确保文章列表立即可见
                from app.models.client import ClientSite
                site_result = await db.execute(
                    select(ClientSite).where(
                        ClientSite.client_id == result.get("client_id"),
                        ClientSite.status == "active",
                    )
                )
                site = site_result.scalars().first()
                site_type = site.site_type if site else "unknown"

                new_index_result = IndexResult(
                    url=req.remote_url,
                    client_id=result.get("client_id"),
                    site_type=site_type,
                    content_title=title,
                    content_snapshot=snapshot,
                    baidu_status="pending",
                    toutiao_status="pending",
                    sogou_status="pending",
                    so360_status="pending",
                    bing_status="pending",
                )
                db.add(new_index_result)
                await db.commit()

                # 异步触发收录扫描（不阻塞 HTTP 响应）
                asyncio.create_task(
                    _run_batch_scan([(req.remote_url, result.get("client_id"))], "index")
                )
    except Exception as exc:
        # 标题抓取失败不影响添加链接
        import logging
        logging.getLogger(__name__).warning("抓取文章标题失败: %s", exc)

    return result


# GET /distributions：client 查询自己的分发记录（D04 修复）
# 挂在 distribution_router（无 prefix），实际路径 /api/v1/distributions
# admin 应使用 GET /admin/distributions（跨客户视图）
# 修复：补齐 source/date_from/date_to 参数（原函数签名缺少这些参数，FastAPI 自动丢弃前端传的筛选条件）
@distribution_router.get("/distributions")
async def list_client_distributions(
    page: int = 1,
    page_size: int = 20,
    source: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    user_client: tuple = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """client 查看自己的分发记录（按 client_id 过滤）。

    用 get_current_user 统一鉴权，client 角色按 user.client_id 过滤；
    非 client 角色（admin）返回 403，引导其走 /admin/distributions。

    支持后端分页（page/page_size），避免大量数据导致前端卡顿。
    支持按 source / date_from / date_to 过滤（与 admin 端点对齐）。
    """
    user, role = user_client
    if role != "client":
        raise HTTPException(
            status_code=403,
            detail="本端点仅供客户使用；admin 请用 /admin/distributions",
        )

    service = DistributionQueryService(db)
    all_items = await service.list_distributions(
        client_id=user.client_id,
        source=source,
        date_from=date_from,
        date_to=date_to,
    )
    total = len(all_items)
    # 后端分页：按 page/page_size 切片
    start = (page - 1) * page_size
    end = start + page_size
    items = all_items[start:end]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


# GET /admin/distributions：admin 查询所有分发记录（跨客户），挂在原 router 上
# C10 修复：新增 date_from / date_to 查询参数，透传给 list_distributions
# 分页修复：新增 page/page_size 参数，后端切片返回，避免前端加载全量数据卡顿
@router.get("/distributions")
async def list_distributions(
    client_id: Optional[str] = None,
    source: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    page: int = 1,
    page_size: int = 20,
    admin: dict = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """admin 查看所有分发记录（跨客户）。

    支持按 client_id / source / date_from / date_to 过滤。
    日期范围与导出报告一致（C10 修复）。
    支持后端分页（page/page_size），避免大量数据导致前端卡顿。
    """
    service = DistributionQueryService(db)
    all_items = await service.list_distributions(
        client_id=client_id,
        source=source,
        date_from=date_from,
        date_to=date_to,
    )
    total = len(all_items)
    # 后端分页：按 page/page_size 切片
    start = (page - 1) * page_size
    end = start + page_size
    items = all_items[start:end]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


class BatchScanRequest(BaseModel):
    distribution_ids: list[str]
    scan_type: str  # 'index' | 'citation' | 'both'


@router.post("/distributions/batch-scan")
async def batch_scan(
    req: BatchScanRequest,
    admin: dict = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """批量触发检测。设计文档第 9.1 节。

    修复：原为占位符（只返回入队数，不执行实际检测），导致 AI 采信监测失灵。
    现改为：解析 distribution_ids → 查 (url, client_id) → asyncio.create_task
    异步执行检测（不阻塞 HTTP 响应），结果异步写入 index_results / citation_results。
    """
    if req.scan_type not in ("index", "citation", "both"):
        raise HTTPException(status_code=400, detail="scan_type 必须是 index/citation/both")

    if not req.distribution_ids:
        raise HTTPException(status_code=400, detail="distribution_ids 不能为空")

    await AuditLogService.log(
        db, admin_user_id=admin["user_id"], admin_name=admin["name"],
        action="batch_scan",
        detail={"ids": req.distribution_ids, "type": req.scan_type},
    )

    # 解析 distribution_ids → [(url, client_id), ...]
    # id 可能来自 ManualDistribution 或 GeoflowArticleDistribution，两表都查
    targets = await _resolve_scan_targets(db, req.distribution_ids)
    if not targets:
        raise HTTPException(status_code=404, detail="未找到对应的分发记录")

    # 创建扫描任务（活动窗口）
    from app.services.scan_task_manager import create_task
    task_id = create_task(req.scan_type, len(targets), targets)

    # 异步执行检测（不阻塞响应；检测可能耗时数分钟，避免 HTTP 超时）
    asyncio.create_task(_run_batch_scan(targets, req.scan_type, task_id))

    return {
        "task_id": task_id,
        "queued": len(targets),
        "scan_type": req.scan_type,
        "message": f"已开始检测 {len(targets)} 条链接，结果将异步更新",
    }


async def _resolve_scan_targets(
    db: AsyncSession, distribution_ids: list[str]
) -> list[tuple[str, str]]:
    """将 distribution_ids 解析为 (url, client_id) 列表。

    distribution_id 可能来自 ManualDistribution（手动录入，UUID 主键）
    或 GeoflowArticleDistribution（GEOFlow 分发，BigInteger 主键）。
    两表 id 类型不同，必须分别查询，否则触发 ``bigint = uuid`` 类型错误。
    """
    targets: list[tuple[str, str]] = []
    seen_urls: set[str] = set()

    # 1. 查 ManualDistribution（id 是 UUID 类型）
    manual_uuids: list[uuid.UUID] = []
    for did in distribution_ids:
        try:
            manual_uuids.append(uuid.UUID(did))
        except (ValueError, AttributeError):
            pass  # 非 UUID 格式，可能是 GEOFlow 的 bigint id

    if manual_uuids:
        manual_result = await db.execute(
            select(ManualDistribution).where(ManualDistribution.id.in_(manual_uuids))
        )
        for record in manual_result.scalars().all():
            if record.remote_url and record.remote_url not in seen_urls:
                targets.append((record.remote_url, record.client_id))
                seen_urls.add(record.remote_url)

    # 2. 查 GeoflowArticleDistribution（id 是 BigInteger 类型，需转为 int）
    geoflow_int_ids: list[int] = []
    for did in distribution_ids:
        try:
            geoflow_int_ids.append(int(did))
        except (ValueError, TypeError):
            pass  # 非数字格式，可能是 ManualDistribution 的 UUID

    if geoflow_int_ids:
        geoflow_result = await db.execute(
            select(GeoflowArticleDistribution).where(
                GeoflowArticleDistribution.id.in_(geoflow_int_ids),
                GeoflowArticleDistribution.remote_url.isnot(None),
            )
        )
        geoflow_dists = geoflow_result.scalars().all()
        if geoflow_dists:
            sites_result = await db.execute(
                select(ClientSite).where(ClientSite.status == "active")
            )
            domain_map = {
                normalize_domain(s.domain): s.client_id
                for s in sites_result.scalars().all()
            }
            for dist in geoflow_dists:
                if dist.remote_url and dist.remote_url not in seen_urls:
                    domain = normalize_domain(dist.remote_url)
                    client_id = domain_map.get(domain)
                    if client_id:
                        targets.append((dist.remote_url, client_id))
                        seen_urls.add(dist.remote_url)

    return targets


async def _run_batch_scan(targets: list[tuple[str, str]], scan_type: str, task_id: str = None) -> None:
    """异步执行批量检测（后台任务，不阻塞 HTTP 响应）。

    独立 session：避免与请求级 session 生命周期耦合。
    单条失败不影响其他 URL（记录日志，继续下一条）。
    活动窗口：通过 task_id 将进度和日志写入 scan_task_manager。
    """
    from app.services.index_checker import IndexChecker
    from app.services.citation_checker import CitationChecker
    from app.services.scan_task_manager import add_log, update_progress, complete_task

    processed = 0
    success = 0
    failed = 0

    async with async_session() as task_db:
        if scan_type in ("index", "both"):
            checker = IndexChecker(task_db)
            for url, client_id in targets:
                try:
                    if task_id:
                        add_log(task_id, "info", f"[收录检测] 开始: {url}")
                    await checker.check_url(url, client_id, "official")
                    logger.info("批量收录检测完成: %s", url)
                    success += 1
                    if task_id:
                        add_log(task_id, "success", f"[收录检测] 完成: {url}")
                except Exception as exc:
                    logger.error("批量收录检测失败 %s: %s", url, exc)
                    failed += 1
                    if task_id:
                        add_log(task_id, "error", f"[收录检测] 失败: {url} - {exc}")
                finally:
                    processed += 1
                    if task_id:
                        update_progress(task_id, processed=processed, success=success, failed=failed)

        if scan_type in ("citation", "both"):
            checker = CitationChecker(task_db)
            for url, client_id in targets:
                try:
                    if task_id:
                        add_log(task_id, "info", f"[AI采信检测] 开始: {url}")
                    # 删除旧的采信记录，允许重新检测（强制刷新）
                    await task_db.execute(
                        delete(CitationResult).where(CitationResult.url == url)
                    )
                    await task_db.commit()
                    await checker.check_url(url, client_id)
                    logger.info("批量采信检测完成: %s", url)
                    success += 1
                    if task_id:
                        add_log(task_id, "success", f"[AI采信检测] 完成: {url}")
                except Exception as exc:
                    logger.error("批量采信检测失败 %s: %s", url, exc)
                    failed += 1
                    if task_id:
                        add_log(task_id, "error", f"[AI采信检测] 失败: {url} - {exc}")
                finally:
                    processed += 1
                    if task_id:
                        update_progress(task_id, processed=processed, success=success, failed=failed)

    if task_id:
        complete_task(task_id)


@router.get("/scan/status/{task_id}")
async def get_scan_status(
    task_id: str,
    admin: dict = Depends(get_current_admin),
):
    """获取扫描任务状态（活动窗口）。

    前端通过 task_id 轮询此端点，实时显示扫描进度和日志。
    任务状态存储在内存中，服务重启后清除。
    """
    from app.services.scan_task_manager import get_task
    task = get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="扫描任务不存在或已过期")
    return task


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
