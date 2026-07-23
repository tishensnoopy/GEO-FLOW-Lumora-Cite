# index-monitor/app/api/routes.py
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.core.security import create_access_token, verify_password, hash_password
from app.models.client import Client
from app.models.index_result import IndexResult, IndexHistory
from app.models.citation_result import CitationResult
from app.models.system_config import SystemConfig
from app.services.index_checker import IndexChecker

router = APIRouter()


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/auth/login")
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Client).where(Client.username == req.username))
    client = result.scalar_one_or_none()
    if not client or not verify_password(req.password, client.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    token = create_access_token({"sub": client.client_id})
    return {"access_token": token, "token_type": "bearer"}


@router.get("/stats/index")
async def get_index_stats(client_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(IndexResult).where(IndexResult.client_id == client_id))
    articles = result.scalars().all()
    total = len(articles)
    indexed = sum(1 for a in articles if any([
        a.baidu_status == "indexed", a.toutiao_status == "indexed",
        a.sogou_status == "indexed", a.so360_status == "indexed",
        a.bing_status == "indexed"
    ]))
    return {"total": total, "indexed": indexed, "rate": indexed / total if total > 0 else 0}


@router.get("/stats/citation")
async def get_citation_stats(client_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(CitationResult).where(CitationResult.url.in_(
            select(IndexResult.url).where(IndexResult.client_id == client_id)
        ))
    )
    citations = result.scalars().all()
    return {"total": len(citations), "cited": sum(1 for c in citations if c.hit_type != "none")}


@router.post("/index/check")
async def trigger_index_check(db: AsyncSession = Depends(get_db)):
    checker = IndexChecker(db)
    await checker.check_all_pending()
    return {"message": "收录检测任务已完成"}


# 修复任务 1 - Fix 3 辅助：按 config_type 将字符串值转换为对应类型
def _type_value(config_value: str, config_type: str):
    if config_type == "number":
        try:
            return int(config_value)
        except (ValueError, TypeError):
            return config_value
    return config_value


# 修复任务 1 - Fix 3 辅助：从 DB 加载所有 SystemConfig 行，返回类型化 dict
async def _load_config_typed(db: AsyncSession) -> dict:
    result = await db.execute(select(SystemConfig))
    rows = result.scalars().all()
    return {row.config_key: _type_value(row.config_value, row.config_type) for row in rows}


# 修复任务 1 - Fix 3：GET /config 返回类型化 dict
@router.get("/config")
async def get_config(db: AsyncSession = Depends(get_db)):
    return await _load_config_typed(db)


# 修复任务 1 - Fix 3：PUT /config 接收 dict，按 key 更新（统一存 str(value)），返回更新后的类型化 dict
@router.put("/config")
async def update_config(payload: dict, db: AsyncSession = Depends(get_db)):
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="请求体必须是 JSON 对象")
    for key, value in payload.items():
        result = await db.execute(select(SystemConfig).where(SystemConfig.config_key == key))
        cfg = result.scalar_one_or_none()
        if cfg is None:
            # 前端会回传整个 config dict；未知 key 跳过（不创建，避免污染配置表）
            continue
        cfg.config_value = str(value)
    await db.commit()
    return await _load_config_typed(db)


# 修复任务 1 - Fix 4：POST /scan/trigger/{type}
#   index：复用 IndexChecker.check_all_pending()
#   citation：lumora-cite 集成待实现，返回诚实 stub（HTTP 200，不让前端按钮报错）
@router.post("/scan/trigger/{scan_type}")
async def trigger_scan(scan_type: str, db: AsyncSession = Depends(get_db)):
    if scan_type == "index":
        checker = IndexChecker(db)
        await checker.check_all_pending()
        return {"message": "收录检测任务已触发并完成"}
    elif scan_type == "citation":
        return {"message": "AI 采信检测（lumora-cite）集成待实现，触发请求已记录"}
    else:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的扫描类型: {scan_type}（支持: index, citation）",
        )


# 修复任务 1 - Fix 5：GET /articles 返回 IndexResult 列表（空表返回 []）
@router.get("/articles")
async def list_articles(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(IndexResult))
    articles = result.scalars().all()
    return [
        {
            "id": str(a.id) if a.id else None,
            "url": a.url,
            "client_id": a.client_id,
            "site_type": a.site_type,
            "content_title": a.content_title,
            "content_keywords": a.content_keywords,
            "content_snapshot": a.content_snapshot,
            "baidu_status": a.baidu_status,
            "toutiao_status": a.toutiao_status,
            "sogou_status": a.sogou_status,
            "so360_status": a.so360_status,
            "bing_status": a.bing_status,
            "baidu_checked_at": a.baidu_checked_at.isoformat() if a.baidu_checked_at else None,
            "toutiao_checked_at": a.toutiao_checked_at.isoformat() if a.toutiao_checked_at else None,
            "sogou_checked_at": a.sogou_checked_at.isoformat() if a.sogou_checked_at else None,
            "so360_checked_at": a.so360_checked_at.isoformat() if a.so360_checked_at else None,
            "bing_checked_at": a.bing_checked_at.isoformat() if a.bing_checked_at else None,
            "created_at": a.created_at.isoformat() if a.created_at else None,
            "updated_at": a.updated_at.isoformat() if a.updated_at else None,
        }
        for a in articles
    ]


# 修复任务 1 - 验证辅助：在 /api/v1 前缀下暴露 /health，
# 供 vite proxy 验证步骤 curl http://localhost:3000/api/v1/health 使用。
# 不影响 main.py 根路径 /health，也不影响 Task 4 既有 4 路由。
@router.get("/health")
async def api_health():
    return {"status": "healthy"}
