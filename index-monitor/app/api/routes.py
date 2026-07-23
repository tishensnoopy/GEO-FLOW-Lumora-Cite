# index-monitor/app/api/routes.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.core.security import create_access_token, verify_password, hash_password
from app.models.client import Client
from app.models.index_result import IndexResult, IndexHistory
from app.models.citation_result import CitationResult
from app.services.index_checker import IndexChecker

router = APIRouter()

@router.post("/auth/login")
async def login(username: str, password: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Client).where(Client.username == username))
    client = result.scalar_one_or_none()
    if not client or not verify_password(password, client.password_hash):
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
