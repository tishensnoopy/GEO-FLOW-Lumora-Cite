# index-monitor/app/api/routes.py
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, case
from app.core.database import get_db
from app.api.deps import get_current_client_id
from app.models.client import Client
from app.models.index_result import IndexResult
from app.models.citation_result import CitationResult
from app.models.system_config import SystemConfig
from app.services.index_checker import IndexChecker
from app.services.citation_checker import CitationChecker

# AI API Key 配置项（GET /config 返回时需脱敏，PUT /config 时跳过脱敏占位）
_API_KEY_CONFIG_KEYS = {
    "ai_deepseek_api_key",
    "ai_dashscope_api_key",
    "ai_ark_api_key",
    "ai_baidu_api_key",
    "ai_openai_api_key",
    "ai_gemini_api_key",
    "ai_anthropic_api_key",
}

# P1 性能优化：stats 接口内存缓存（30 秒 TTL）
# key: f"stats_{type}_{client_id}", value: {"data": ..., "ts": timestamp}
_stats_cache: dict[str, dict] = {}


def _mask_api_key(value: str) -> str:
    """脱敏 API Key：保留前 3 + 后 4 字符，中间用 **** 替代。"""
    if not value:
        return ""
    if len(value) <= 8:
        return "****"
    return f"{value[:3]}****{value[-4:]}"

router = APIRouter()


def _is_admin(client_id: str) -> bool:
    """判断是否为 admin（SSO 登录的管理员，可查看所有客户数据）。

    ``get_current_client_id`` 对 admin JWT 返回 ``"admin"`` 标记。
    admin 调用各端点时不按 client_id 过滤，可查看全部数据。
    """
    return client_id == "admin"


@router.get("/stats/index")
async def get_index_stats(client_id: str = Depends(get_current_client_id), db: AsyncSession = Depends(get_db)):
    """收录统计。

    P1 性能优化：
    1. 原实现 select(IndexResult) 全表加载到内存再 Python 聚合，数据量大时内存和耗时都高。
       改为 SQL COUNT + CASE WHEN 聚合，DB 侧完成计算。
    2. 加 30 秒内存缓存，避免短时间内重复查询（Dashboard 频繁刷新）。
    """
    import time
    cache_key = f"stats_index_{client_id}"
    cached = _stats_cache.get(cache_key)
    if cached and time.time() - cached["ts"] < 30:
        return cached["data"]

    # SQL 聚合：COUNT + CASE WHEN，避免全表加载到内存
    from sqlalchemy import func, case
    base_filter = [] if _is_admin(client_id) else [IndexResult.client_id == client_id]
    result = await db.execute(
        select(
            func.count(IndexResult.id).label("total"),
            func.sum(
                case(
                    (
                        (IndexResult.baidu_status == "indexed")
                        | (IndexResult.toutiao_status == "indexed")
                        | (IndexResult.sogou_status == "indexed")
                        | (IndexResult.so360_status == "indexed")
                        | (IndexResult.bing_status == "indexed"),
                        1,
                    ),
                    else_=0,
                )
            ).label("indexed"),
        ).where(*base_filter)
    )
    row = result.one()
    total = row.total or 0
    indexed = int(row.indexed or 0)
    data = {"total": total, "indexed": indexed, "rate": indexed / total if total > 0 else 0}

    _stats_cache[cache_key] = {"data": data, "ts": time.time()}
    return data


@router.get("/stats/citation")
async def get_citation_stats(client_id: str = Depends(get_current_client_id), db: AsyncSession = Depends(get_db)):
    """采信统计。

    P1 性能优化：SQL COUNT 聚合 + 30 秒内存缓存。
    """
    import time
    cache_key = f"stats_citation_{client_id}"
    cached = _stats_cache.get(cache_key)
    if cached and time.time() - cached["ts"] < 30:
        return cached["data"]

    from sqlalchemy import func
    if _is_admin(client_id):
        result = await db.execute(
            select(
                func.count(CitationResult.id).label("total"),
                func.sum(case((CitationResult.hit_type != "none", 1), else_=0)).label("cited"),
            )
        )
    else:
        result = await db.execute(
            select(
                func.count(CitationResult.id).label("total"),
                func.sum(case((CitationResult.hit_type != "none", 1), else_=0)).label("cited"),
            ).where(
                CitationResult.url.in_(
                    select(IndexResult.url).where(IndexResult.client_id == client_id)
                )
            )
        )
    row = result.one()
    total = row.total or 0
    cited = int(row.cited or 0)
    data = {"total": total, "cited": cited}

    _stats_cache[cache_key] = {"data": data, "ts": time.time()}
    return data


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
# lumora-cite 集成：AI API Key 字段脱敏后返回（仅显示前3+后4字符）
async def _load_config_typed(db: AsyncSession) -> dict:
    result = await db.execute(select(SystemConfig))
    rows = result.scalars().all()
    config = {}
    for row in rows:
        value = _type_value(row.config_value, row.config_type)
        if row.config_key in _API_KEY_CONFIG_KEYS and value:
            value = _mask_api_key(str(value))
        config[row.config_key] = value
    return config


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
        # lumora-cite 集成：API Key 字段如果是脱敏占位（含 ****），跳过不覆盖
        if key in _API_KEY_CONFIG_KEYS and "****" in str(value):
            continue
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
        checker = CitationChecker(db)
        summary = await checker.check_all_pending()
        if summary["total"] == 0:
            return {"message": "没有待检测的 URL（所有已同步文章均已检测或无文章）"}
        return {
            "message": f"AI 采信检测完成：{summary['success']} 成功 / {summary['failed']} 失败 / {summary['total']} 总计",
            "summary": summary,
        }
    else:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的扫描类型: {scan_type}（支持: index, citation）",
        )


# 修复任务 1 - Fix 5：GET /articles 返回 IndexResult 列表（空表返回 []）
# lumora-cite 集成：附加 citation_status / citation_total / citation_exact 等字段
@router.get("/articles")
async def list_articles(client_id: str = Depends(get_current_client_id), db: AsyncSession = Depends(get_db)):
    query = select(IndexResult)
    if not _is_admin(client_id):
        query = query.where(IndexResult.client_id == client_id)
    result = await db.execute(query)
    articles = result.scalars().all()

    # 按 URL 聚合采信检测统计
    if articles:
        urls = [a.url for a in articles]
        citation_stats = await db.execute(
            select(
                CitationResult.url,
                func.count().label("total"),
                func.count().filter(CitationResult.hit_type == "exact").label("exact"),
                func.count().filter(CitationResult.hit_type == "domain").label("domain"),
                func.count().filter(CitationResult.hit_type == "none").label("none"),
                func.max(CitationResult.checked_at).label("last_checked"),
            )
            .where(CitationResult.url.in_(urls))
            .group_by(CitationResult.url)
        )
        stats_map = {row.url: row for row in citation_stats.fetchall()}
    else:
        stats_map = {}

    def _citation_status(stat) -> str:
        if stat is None or stat.total == 0:
            return "pending"
        if stat.exact > 0:
            return "cited"
        if stat.domain > 0:
            return "partial"
        return "not_cited"

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
            # lumora-cite 集成：采信检测统计
            "citation_status": _citation_status(stats_map.get(a.url)),
            "citation_total": stats_map[a.url].total if a.url in stats_map else 0,
            "citation_exact": stats_map[a.url].exact if a.url in stats_map else 0,
            "citation_domain": stats_map[a.url].domain if a.url in stats_map else 0,
            "citation_last_checked": (
                stats_map[a.url].last_checked.isoformat()
                if a.url in stats_map and stats_map[a.url].last_checked
                else None
            ),
        }
        for a in articles
    ]


# ===========================================================================
# lumora-cite 集成：AI 采信检测端点
# ===========================================================================

class CitationCheckRequest(BaseModel):
    """手动触发单个 URL 的 AI 采信检测。"""
    url: str


@router.get("/citations")
async def list_citations(client_id: str = Depends(get_current_client_id), db: AsyncSession = Depends(get_db)):
    """按 URL 聚合返回当前客户的 AI 采信检测结果。"""
    # 先获取属于当前客户的 URL 集合（admin 查看所有）
    if _is_admin(client_id):
        url_subquery = select(IndexResult.url)
    else:
        url_subquery = select(IndexResult.url).where(IndexResult.client_id == client_id)
    result = await db.execute(
        select(
            CitationResult.url,
            func.count().label("total"),
            func.count().filter(CitationResult.hit_type == "exact").label("exact"),
            func.count().filter(CitationResult.hit_type == "domain").label("domain"),
            func.count().filter(CitationResult.hit_type == "none").label("none"),
            func.count().filter(CitationResult.hit_type == "unverifiable").label("unverifiable"),
            func.max(CitationResult.checked_at).label("last_checked"),
        )
        .where(CitationResult.url.in_(url_subquery))
        .group_by(CitationResult.url)
    )
    rows = result.fetchall()
    return [
        {
            "url": row.url,
            "total": row.total,
            "exact": row.exact,
            "domain": row.domain,
            "none": row.none,
            "unverifiable": row.unverifiable,
            "exact_rate": round(row.exact / row.total, 4) if row.total else 0,
            "domain_rate": round(row.domain / row.total, 4) if row.total else 0,
            "last_checked": row.last_checked.isoformat() if row.last_checked else None,
        }
        for row in rows
    ]


@router.post("/citations/check")
async def check_single_citation(
    req: CitationCheckRequest,
    client_id: str = Depends(get_current_client_id),
    db: AsyncSession = Depends(get_db),
):
    """手动触发单个 URL 的 AI 采信检测，返回完整结果。"""
    checker = CitationChecker(db)
    try:
        result = await checker.check_url(req.url, client_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"采信检测执行失败：{exc}")

    return {
        "url": req.url,
        "summary": result.get("summary"),
        "purpose": result.get("purpose"),
        "questions": result.get("questions"),
        "provider_capabilities": result.get("provider_capabilities"),
        "results_count": len(result.get("results", [])),
    }


@router.get("/citations/detail")
async def get_citation_detail(
    url: str,
    client_id: str = Depends(get_current_client_id),
    db: AsyncSession = Depends(get_db),
):
    """返回指定 URL 的所有采信检测明细记录。"""
    # 验证 URL 属于当前客户（admin 可查看任意 URL）
    if _is_admin(client_id):
        ownership = await db.execute(
            select(IndexResult.url).where(IndexResult.url == url)
        )
    else:
        ownership = await db.execute(
            select(IndexResult.url).where(IndexResult.client_id == client_id, IndexResult.url == url)
        )
    if not ownership.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="URL 不属于当前客户或不存在")

    result = await db.execute(
        select(CitationResult).where(CitationResult.url == url).order_by(CitationResult.checked_at.desc())
    )
    records = result.scalars().all()
    return [
        {
            "id": str(r.id),
            "url": r.url,
            "model": r.model,
            "question": r.question,
            "answer": r.answer,
            "hit_type": r.hit_type,
            "sources": r.sources,
            "checked_at": r.checked_at.isoformat() if r.checked_at else None,
        }
        for r in records
    ]


# 修复任务 1 - 验证辅助：在 /api/v1 前缀下暴露 /health，
# 供 vite proxy 验证步骤 curl http://localhost:3000/api/v1/health 使用。
# 不影响 main.py 根路径 /health，也不影响 Task 4 既有 4 路由。
@router.get("/health")
async def api_health():
    return {"status": "healthy"}
