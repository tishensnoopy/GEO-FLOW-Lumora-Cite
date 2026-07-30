# index-monitor/app/api/routes.py
import asyncio
import logging
import urllib.request
import urllib.error
import json

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

logger = logging.getLogger(__name__)
# Q2 修复：配置变更后需清空探测缓存，否则旧的探测结果（如 Key 失效时的 failed）
# 会被复用，导致新配置的模型仍不被触发。invalidate_probe_cache 来自 citation_check.engine。
from app.services.citation_check.engine import invalidate_probe_cache, probe_adapter_capability
# Q4 修复：API Key 测试需复用引用检测适配器（providers）与默认探测问题。
from app.services.citation_check.providers import default_adapters

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

# Q4：API Key 配置项 → 引用检测 provider_id 与对应环境变量名映射。
# DeepSeek 无引用检测适配器（仅作问题生成模型），单独走 chat 兼容测试。
_KEY_TO_PROVIDER = {
    "ai_dashscope_api_key": ("qwen", "DASHSCOPE_API_KEY"),
    "ai_ark_api_key": ("doubao", "ARK_API_KEY"),
    "ai_baidu_api_key": ("ernie", "BAIDU_API_KEY"),
    "ai_openai_api_key": ("openai", "OPENAI_API_KEY"),
    "ai_gemini_api_key": ("gemini", "GEMINI_API_KEY"),
    "ai_anthropic_api_key": ("claude", "ANTHROPIC_API_KEY"),
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
    # 记录本次是否触碰到 AI 相关配置（Key 或引用检测模型列表），用于决定是否清探测缓存
    touched_ai_config = False
    for key, value in payload.items():
        # lumora-cite 集成：API Key 字段如果是脱敏占位（含 ****），跳过不覆盖
        if key in _API_KEY_CONFIG_KEYS and "****" in str(value):
            continue
        if key in _API_KEY_CONFIG_KEYS or key in ("ai_citation_models", "ai_question_model"):
            touched_ai_config = True
        result = await db.execute(select(SystemConfig).where(SystemConfig.config_key == key))
        cfg = result.scalar_one_or_none()
        if cfg is None:
            # 前端会回传整个 config dict；未知 key 跳过（不创建，避免污染配置表）
            continue
        cfg.config_value = str(value)
    await db.commit()
    # Q2 修复：AI 配置变更后清空引用检测模型探测缓存。
    # 背景：探测结果（模型是否支持联网搜索）按 provider_id:model_id 缓存 1 小时。
    # 若用户更新了失效的 API Key，旧缓存仍标记模型不可用，导致新 Key 不被触发，
    # 表现为"配置了多个模型但只触发千问"。清缓存后下次扫描会重新探测所有模型。
    if touched_ai_config:
        invalidate_probe_cache(None)
    return await _load_config_typed(db)


# Q4：API Key 即时测试端点。
# - 引用检测模型（千问/豆包/文心/OpenAI/Gemini/Claude）：复用 citation_check 适配器
#   与探测逻辑（probe_adapter_capability, force_refresh=True），既验证 Key 有效性，
#   又验证该模型是否支持联网搜索（引用检测的前提）。
# - DeepSeek（问题生成模型）：无引用检测适配器，单独走 OpenAI 兼容 chat 测试。
@router.post("/config/test-key")
async def test_api_key(payload: dict, db: AsyncSession = Depends(get_db)):
    key_type = payload.get("key_type", "")
    submitted = payload.get("api_key", "") or ""

    # 输入框是脱敏占位（含 ****）或为空 → 用服务端已存储的 Key 测试
    if "****" in submitted or not submitted:
        result = await db.execute(
            select(SystemConfig).where(SystemConfig.config_key == key_type)
        )
        cfg = result.scalar_one_or_none()
        api_key = cfg.config_value if cfg else ""
    else:
        api_key = submitted

    if not api_key:
        return {"success": False, "message": "未配置 API Key，无法测试"}

    # DeepSeek：问题生成模型，走 OpenAI 兼容 chat/completions 最小请求验证
    if key_type == "ai_deepseek_api_key":
        # 取问题生成模型名（默认 deepseek-v4-flash）
        qm_result = await db.execute(
            select(SystemConfig).where(SystemConfig.config_key == "ai_question_model")
        )
        qm_cfg = qm_result.scalar_one_or_none()
        model_name = (qm_cfg.config_value if qm_cfg else "") or "deepseek-v4-flash"
        return await asyncio.to_thread(_test_deepseek_key, api_key, model_name)

    # 引用检测模型：复用适配器探测
    mapping = _KEY_TO_PROVIDER.get(key_type)
    if not mapping:
        return {"success": False, "message": f"不支持的 Key 类型：{key_type}"}
    provider_id, env_var = mapping
    # providers.default_adapters 通过 os.getenv 读取 Key，因此先写入环境变量
    import os
    os.environ[env_var] = api_key
    return await asyncio.to_thread(_test_citation_key, provider_id)


def _test_deepseek_key(api_key: str, model_name: str) -> dict:
    """DeepSeek Key 测试：发一个 max_tokens=5 的最小 chat 请求，2xx 视为可用。"""
    url = "https://api.deepseek.com/chat/completions"
    body = json.dumps({
        "model": model_name,
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 5,
    }).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp.read()
        return {"success": True, "message": f"DeepSeek Key 可用（模型 {model_name} 连接成功）"}
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")[:300]
        return {"success": False, "message": f"DeepSeek Key 不可用：HTTP {exc.code} - {body_text}"}
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "message": f"DeepSeek Key 测试失败：{exc}"}


def _test_citation_key(provider_id: str) -> dict:
    """引用检测模型 Key 测试：构建单个适配器并强制重新探测联网能力。"""
    import os
    adapters = default_adapters([provider_id])
    if not adapters:
        env_ok = bool(os.getenv({
            "qwen": "DASHSCOPE_API_KEY", "doubao": "ARK_API_KEY", "ernie": "BAIDU_API_KEY",
            "openai": "OPENAI_API_KEY", "gemini": "GEMINI_API_KEY", "claude": "ANTHROPIC_API_KEY",
        }.get(provider_id, ""), ""))
        return {"success": False, "message": f"未找到 {provider_id} 适配器（env_ok={env_ok}），请检查 Key 是否已写入"}
    adapter = adapters[0]
    probe = probe_adapter_capability(adapter, force_refresh=True)
    status = probe.get("status")
    if status == "verified":
        return {
            "success": True,
            "message": f"{probe['model']}（{probe['model_id']}）Key 可用，已通过联网搜索验证",
        }
    if status == "error":
        return {"success": False, "message": f"{probe['model']} Key 不可用：{probe.get('error', '未知错误')}"}
    # search_without_sources / no_search：Key 本身有效，但模型未返回联网来源
    return {
        "success": False,
        "message": (
            f"{probe['model']} Key 有效，但未检测到联网搜索能力"
            f"（web_search={probe.get('web_search')}, sources={bool(probe.get('sample_sources'))}）。"
            "该模型可能无法用于引用检测，建议更换支持联网搜索的模型。"
        ),
    }


# 修复任务 1 - Fix 4：POST /scan/trigger/{type}
#   阶段 4 - ⑤/①：异步化，返回 task_id 供 ScanPanel 实时展示进度。
#   原同步实现阻塞事件循环（检测耗时数分钟 → HTTP 超时），且无 task_id
#   使前端无法看到检测过程。现改为：获取 pending → create_task → 后台执行 → 返回 task_id。
#   后台执行用独立 session（避免请求级 session 生命周期耦合），透传 task_id
#   让 check_url 的 progress 回调把 5 阶段进度 + 模型 probe 状态写入活动窗口。
@router.post("/scan/trigger/{scan_type}")
async def trigger_scan(scan_type: str, db: AsyncSession = Depends(get_db)):
    if scan_type not in ("index", "citation"):
        raise HTTPException(
            status_code=400,
            detail=f"不支持的扫描类型: {scan_type}（支持: index, citation）",
        )

    # 阶段 3 - ②：同步预检 advisory lock。若已有同类型扫描在运行，立即返回 409，
    # 给用户即时反馈，而非创建任务后又在后台跳过。预检只查 pg_locks 不获取锁，
    # 真正的 acquire/release 仍在 _run_scan_background 内完成（后台并发安全）。
    from app.services.scan_lock import is_scan_locked
    if await is_scan_locked(db, scan_type):
        raise HTTPException(
            status_code=409,
            detail=f"已有 {scan_type} 扫描任务在运行，请等待其完成后再触发",
        )

    # 用请求级 db 获取待检测 URL 列表（轻量查询，可同步完成）
    checker = IndexChecker(db) if scan_type == "index" else CitationChecker(db)
    pending = await checker.get_pending_urls()
    if not pending:
        return {
            "task_id": None,
            "message": "没有待检测的 URL（所有已同步文章均已检测或无文章）",
            "queued": 0,
        }

    # 创建活动窗口任务（前端按 task_id 轮询 /admin/scan/status/{task_id}）
    from app.services.scan_task_manager import create_task
    task_id = create_task(scan_type, len(pending), pending)

    # 后台异步执行检测（不阻塞 HTTP 响应）
    asyncio.create_task(_run_scan_background(scan_type, task_id))

    return {
        "task_id": task_id,
        "queued": len(pending),
        "scan_type": scan_type,
        "message": f"已开始检测 {len(pending)} 条链接，结果将异步更新",
    }


async def _run_scan_background(scan_type: str, task_id: str) -> None:
    """后台执行扫描任务（独立 session，透传 task_id 写活动窗口）。

    阶段 4 - ⑤/①：与 admin_routes._run_batch_scan 类似，但面向 /scan/trigger
    入口（全量 pending 检测）。check_all_pending 内部透传 task_id 给 check_url，
    使 5 阶段进度 + 模型 probe 状态实时写入 scan_task_manager。

    阶段 3 - ②：advisory lock 防止与定时任务/其他全量扫描重叠。获取失败则跳过，
    避免重复检测浪费 API 配额。
    """
    from app.core.database import async_session
    from app.services.scan_task_manager import complete_task, add_log
    from app.services.scan_lock import acquire_scan_lock, release_scan_lock

    async with async_session() as task_db:
        # advisory lock：同 scan_type 已有扫描在运行则跳过
        if not await acquire_scan_lock(task_db, scan_type):
            add_log(task_id, "warning", f"已有 {scan_type} 扫描在运行，本次跳过以避免重复检测")
            complete_task(task_id, status="completed")
            return
        try:
            checker = IndexChecker(task_db) if scan_type == "index" else CitationChecker(task_db)
            await checker.check_all_pending(task_id=task_id)
        except Exception as exc:  # noqa: BLE001
            logger.error("后台扫描任务 %s 失败: %s", task_id, exc)
            complete_task(task_id, status="failed")
            return
        finally:
            # advisory lock 必须在同一 session 释放
            await release_scan_lock(task_db, scan_type)
    complete_task(task_id)


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
            # 阶段 1 - ⑥a：命中率分母只计"可判定命中"的有效回答
            # （exact + domain + none），排除 unverifiable（模型未联网/抓取失败等
            # 无法判定命中的记录）。否则 unverifiable 会稀释命中率，使实际被引用
            # 的文章命中率看起来偏低。有效分母为 0 时回退 0，避免除零。
            "exact_rate": round(row.exact / (row.exact + row.domain + row.none), 4) if (row.exact + row.domain + row.none) else 0,
            "domain_rate": round(row.domain / (row.exact + row.domain + row.none), 4) if (row.exact + row.domain + row.none) else 0,
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
