"""客户端只读 API 路由。

所有端点用 get_current_client_id 鉴权，client_id 强制从 JWT 取。
数据范围限制：仅返回该客户自己的数据，隐藏 pending/not_indexed/未引用。
"""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func, case
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_client_id
from app.core.database import get_db
from app.integration.geoflow import GeoflowRepository
from app.models.ai_index_result import AIIndexResult
from app.models.article_question_mapping import ArticleQuestionMapping
from app.models.citation_result import CitationResult
from app.models.client_question import ClientQuestion
from app.models.manual_distribution import ManualDistribution
from app.models.client import ClientSite
from app.models.index_result import IndexResult
from app.utils.validators import normalize_domain

logger = logging.getLogger(__name__)
router = APIRouter()

# AI 平台 model code → 中文展示名（与 citation_check/providers.py、report.html 对齐）。
# 雷达图 / 可见度得分用此映射把 model 字段翻译成用户可读标签。
MODEL_DISPLAY_NAMES: dict[str, str] = {
    "doubao": "豆包",
    "qwen": "千问",
    "ernie": "文心",
    "wenxin": "文心",
    "openai": "OpenAI",
    "chatgpt": "ChatGPT",
    "gemini": "Gemini",
    "claude": "Claude",
    "deepseek": "DeepSeek",
    "glm": "智谱GLM",
    "spark": "讯飞星火",
    "baichuan": "百川",
    "minimax": "MiniMax",
    "moonshot": "月之暗面",
    "kimi": "Kimi",
}

# 被视为"被引用"的 hit_type 集合（与 citation_evidence 端点的 != 'none' 互补，
# 这里更严格：只有 exact / domain 算真正引用，mention / none 不计入引用率分子）。
CITED_HIT_TYPES: tuple[str, ...] = ("exact", "domain")


async def _get_client_urls(db: AsyncSession, client_id: str) -> set[str]:
    """获取属于该客户的所有 URL（手动录入 + GEOFlow 分发匹配 ClientSite）。"""
    # 1. 手动录入
    manual = await db.execute(
        select(ManualDistribution.remote_url).where(
            ManualDistribution.client_id == client_id,
            ManualDistribution.status == "synced",
        )
    )
    urls = {row[0] for row in manual.fetchall() if row[0]}

    # 2. GEOFlow 分发（按 ClientSite.domain 匹配）
    try:
        repo = GeoflowRepository(db)
        geoflow_urls = await repo.get_synced_distribution_urls()
        sites = await db.execute(
            select(ClientSite).where(
                ClientSite.client_id == client_id,
                ClientSite.status == "active",
            )
        )
        domains = {normalize_domain(s.domain) for s in sites.scalars().all()}
        urls.update(u for u in geoflow_urls if normalize_domain(u) in domains)
    except Exception as exc:
        # asyncpg 在查询失败后会把当前事务置为 aborted 状态，后续 SQL 全部报
        # "current transaction is aborted" —— 必须 rollback 才能继续用此 session。
        # 本端点为只读，rollback 不会丢数据；上面 manual 查询结果已在 urls 集合中。
        await db.rollback()
        logger.warning("客户端 URL 归属判定-GEOFlow 查询失败: %s", exc)

    return urls


@router.get("/ai-index/overview")
async def ai_index_overview(
    client_id: str = Depends(get_current_client_id),
    db: AsyncSession = Depends(get_db),
):
    """我的收录概览（仅已收录，简化）。"""
    if client_id == "admin":
        raise HTTPException(status_code=403, detail="本端点仅供客户使用")

    client_urls = await _get_client_urls(db, client_id)
    if not client_urls:
        return {"total_indexed": 0, "total_not_indexed": 0, "index_rate": 0, "articles": []}

    # 查该客户 URL 的收录结果
    result = await db.execute(
        select(AIIndexResult).where(AIIndexResult.url.in_(client_urls))
    )
    all_records = result.scalars().all()

    indexed_urls = {r.url for r in all_records if r.index_status == "indexed"}
    total_indexed = len(indexed_urls)
    total_not_indexed = len({r.url for r in all_records if r.index_status == "not_indexed"})
    index_rate = total_indexed / (total_indexed + total_not_indexed) if (total_indexed + total_not_indexed) > 0 else 0

    # 获取 URL → title 映射（I2 修复：与 citation_evidence 对齐，补全 title 字段）
    indexed_url_set = {r.url for r in all_records if r.index_status == "indexed"}
    title_map: dict[str, str] = {}
    if indexed_url_set:
        title_result = await db.execute(
            select(IndexResult.url, IndexResult.content_title).where(
                IndexResult.url.in_(indexed_url_set)
            )
        )
        title_map = {row[0]: row[1] or "" for row in title_result.fetchall()}

    # 仅返回 indexed 的文章（隐藏 pending/not_indexed 详情）
    articles = [
        {
            "url": r.url,
            "title": title_map.get(r.url) or "",
            "model": r.model,
            "index_status": r.index_status,
            "checked_at": r.checked_at.isoformat() if r.checked_at else None,
        }
        for r in all_records
        if r.index_status == "indexed"
    ]

    return {
        "total_indexed": total_indexed,
        "total_not_indexed": total_not_indexed,
        "index_rate": index_rate,
        "articles": articles,
    }


@router.get("/citations/evidence")
async def citation_evidence(
    client_id: str = Depends(get_current_client_id),
    db: AsyncSession = Depends(get_db),
):
    """我的引用证据（仅被引用的 Q&A，hit_type != 'none'）。"""
    if client_id == "admin":
        raise HTTPException(status_code=403, detail="本端点仅供客户使用")

    client_urls = await _get_client_urls(db, client_id)
    if not client_urls:
        return []

    result = await db.execute(
        select(CitationResult).where(
            CitationResult.url.in_(client_urls),
            CitationResult.hit_type != "none",
        ).order_by(CitationResult.created_at.desc())
    )
    records = result.scalars().all()

    # 获取 URL → title 映射
    title_result = await db.execute(
        select(IndexResult.url, IndexResult.content_title).where(
            IndexResult.url.in_({r.url for r in records})
        )
    )
    title_map = {row[0]: row[1] for row in title_result.fetchall()}

    return [
        {
            "id": str(r.id),
            "url": r.url,
            "title": title_map.get(r.url, ""),
            "model": r.model,
            "question": r.question,
            "answer": r.answer,
            "hit_type": r.hit_type,
            "sources": r.sources,
            "checked_at": r.checked_at.isoformat() if r.checked_at else None,
        }
        for r in records
    ]


@router.get("/stats")
async def client_stats(
    client_id: str = Depends(get_current_client_id),
    db: AsyncSession = Depends(get_db),
):
    """我的统计卡片数据。"""
    if client_id == "admin":
        raise HTTPException(status_code=403, detail="本端点仅供客户使用")

    client_urls = await _get_client_urls(db, client_id)
    if not client_urls:
        return {
            "ai_indexed_count": 0,
            "ai_cited_count": 0,
            "ai_mention_rate": 0,
            "total_articles": 0,
            "index_rate": 0,
        }

    # AI 收录数（distinct URL with indexed）
    indexed_result = await db.execute(
        select(func.count(func.distinct(AIIndexResult.url))).where(
            AIIndexResult.url.in_(client_urls),
            AIIndexResult.index_status == "indexed",
        )
    )
    ai_indexed_count = indexed_result.scalar() or 0

    # AI 提及数（distinct URL with cited）
    cited_result = await db.execute(
        select(func.count(func.distinct(CitationResult.url))).where(
            CitationResult.url.in_(client_urls),
            CitationResult.hit_type != "none",
        )
    )
    ai_cited_count = cited_result.scalar() or 0

    # AI 提及率
    ai_mention_rate = ai_cited_count / ai_indexed_count if ai_indexed_count > 0 else 0

    # 文章总数
    total_articles = len(client_urls)

    # 搜索引擎收录率
    idx_result = await db.execute(
        select(
            func.count(IndexResult.id).label("total"),
            func.sum(case(
                ((IndexResult.baidu_status == "indexed")
                 | (IndexResult.toutiao_status == "indexed")
                 | (IndexResult.sogou_status == "indexed")
                 | (IndexResult.so360_status == "indexed")
                 | (IndexResult.bing_status == "indexed"), 1),
                else_=0,
            )).label("indexed"),
        ).where(IndexResult.url.in_(client_urls))
    )
    row = idx_result.one()
    idx_total = row.total or 0
    idx_indexed = int(row.indexed or 0)
    index_rate = idx_indexed / idx_total if idx_total > 0 else 0

    return {
        "ai_indexed_count": ai_indexed_count,
        "ai_cited_count": ai_cited_count,
        "ai_mention_rate": ai_mention_rate,
        "total_articles": total_articles,
        "index_rate": index_rate,
    }


# ============================================================================
# Phase 2：客户工作报告 / 回答快照 / AI 可见度得分
# 设计文档第 5.4 节客户端只读 API 扩展。所有端点同样拒绝 admin token，
# 数据范围严格限制在 client_id 自己的发稿与问题。
# ============================================================================


@router.get("/client/work-report")
async def client_work_report(
    client_id: str = Depends(get_current_client_id),
    db: AsyncSession = Depends(get_db),
):
    """客户工作报告：发稿量统计 + 发稿列表（含关联问题和引用检测结果）。

    返回结构：
    - summary：总量/本月/问题数/被引用次数/引用率
    - items：每篇发稿关联的问题（article_question_mappings）和引用检测命中
      （citation_results，通过 url = remote_url 关联）
    """
    if client_id == "admin":
        raise HTTPException(status_code=403, detail="本端点仅供客户使用")

    # 1. 客户发稿记录（仅 synced，与 _get_client_urls 的口径一致）
    dist_result = await db.execute(
        select(ManualDistribution).where(
            ManualDistribution.client_id == client_id,
            ManualDistribution.status == "synced",
        ).order_by(ManualDistribution.created_at.desc())
    )
    distributions = dist_result.scalars().all()

    # 2. 客户 active 问题数
    q_count_result = await db.execute(
        select(func.count(ClientQuestion.id)).where(
            ClientQuestion.client_id == client_id,
            ClientQuestion.status == "active",
        )
    )
    total_questions = q_count_result.scalar() or 0

    # 3. 引用率统计（citation_results 通过 url = remote_url 关联）
    dist_urls = [d.remote_url for d in distributions if d.remote_url]
    total_cited = 0
    total_detections = 0
    citation_by_url: dict[str, list[CitationResult]] = {}
    if dist_urls:
        cit_result = await db.execute(
            select(CitationResult).where(CitationResult.url.in_(dist_urls))
        )
        all_citations = cit_result.scalars().all()
        total_detections = len(all_citations)
        total_cited = sum(1 for c in all_citations if c.hit_type in CITED_HIT_TYPES)
        for c in all_citations:
            citation_by_url.setdefault(c.url, []).append(c)

    citation_rate = (total_cited / total_detections) if total_detections > 0 else 0

    # 4. 本月发稿量（按 UTC 当月判定，与 server_default=func.now() 的时区一致）
    now = datetime.now(timezone.utc)
    this_month_distributions = sum(
        1 for d in distributions
        if d.created_at is not None
        and d.created_at.year == now.year
        and d.created_at.month == now.month
    )

    # 5. 关联问题：批量查 article_question_mappings + client_questions
    dist_ids = [d.id for d in distributions]
    questions_by_dist: dict[str, list[dict]] = {}
    if dist_ids:
        mapping_result = await db.execute(
            select(
                ArticleQuestionMapping.distribution_id,
                ArticleQuestionMapping.client_question_id,
                ArticleQuestionMapping.relevance_score,
                ClientQuestion.id.label("q_id"),
                ClientQuestion.question,
            ).outerjoin(
                ClientQuestion,
                ClientQuestion.id == ArticleQuestionMapping.client_question_id,
            ).where(
                ArticleQuestionMapping.distribution_id.in_(dist_ids)
            ).order_by(ArticleQuestionMapping.relevance_score.desc())
        )
        for row in mapping_result.fetchall():
            dist_id_str = str(row.distribution_id)
            questions_by_dist.setdefault(dist_id_str, []).append({
                "id": str(row.q_id) if row.q_id is not None else None,
                "question": row.question,
                "relevance_score": row.relevance_score,
            })

    # 6. 组装 items
    items = []
    for d in distributions:
        items.append({
            "id": str(d.id),
            "title": d.content_title or d.note or "",
            "url": d.remote_url,
            "distributed_at": d.created_at.isoformat() if d.created_at else None,
            "questions": questions_by_dist.get(str(d.id), []),
            "citation_results": [
                {
                    "model": c.model,
                    "question": c.question,
                    "hit_type": c.hit_type,
                    "checked_at": c.checked_at.isoformat() if c.checked_at else None,
                }
                for c in citation_by_url.get(d.remote_url, [])
            ],
        })

    return {
        "summary": {
            "total_distributions": len(distributions),
            "this_month_distributions": this_month_distributions,
            "total_questions": total_questions,
            "total_cited": total_cited,
            "citation_rate": round(citation_rate, 2),
        },
        "items": items,
    }


@router.get("/client/rankings")
async def client_rankings(
    client_id: str = Depends(get_current_client_id),
    db: AsyncSession = Depends(get_db),
):
    """回答快照：各平台 AI 回答全文展示。

    按客户 active 问题分组，返回每个问题在各 AI 平台的回答全文、来源和命中类型。
    citation_results 通过 client_question_id 关联到问题。
    """
    if client_id == "admin":
        raise HTTPException(status_code=403, detail="本端点仅供客户使用")

    # 1. 客户 active 问题（按 sort_order 排序，与 client_question_service 口径一致）
    q_result = await db.execute(
        select(ClientQuestion).where(
            ClientQuestion.client_id == client_id,
            ClientQuestion.status == "active",
        ).order_by(ClientQuestion.sort_order, ClientQuestion.created_at.desc())
    )
    questions = q_result.scalars().all()

    if not questions:
        return {"questions": []}

    # 2. 批量查这些问题关联的 citation_results
    question_ids = [q.id for q in questions]
    cit_result = await db.execute(
        select(CitationResult).where(
            CitationResult.client_question_id.in_(question_ids)
        ).order_by(CitationResult.checked_at.desc())
    )
    all_citations = cit_result.scalars().all()
    citations_by_qid: dict[str, list[CitationResult]] = {}
    for c in all_citations:
        key = str(c.client_question_id) if c.client_question_id is not None else None
        if key is not None:
            citations_by_qid.setdefault(key, []).append(c)

    # 3. 批量获取置信度（按 model 分组，避免 N+1 查询）
    from app.services.calibration_service import CalibrationService
    cal_service = CalibrationService(db)
    all_confidence = await cal_service.get_all_confidence()
    confidence_by_model = {c["model"]: c for c in all_confidence}

    # 4. 组装
    return {
        "questions": [
            {
                "id": str(q.id),
                "question": q.question,
                "results": [
                    {
                        "model": c.model,
                        "hit_type": c.hit_type,
                        "answer": c.answer or "",
                        "sources": c.sources or [],
                        "checked_at": c.checked_at.isoformat() if c.checked_at else None,
                        "article_url": c.url,
                        "confidence": confidence_by_model.get(c.model, {}).get("confidence", -1),
                        "confidence_level": confidence_by_model.get(c.model, {}).get("level", "uncalibrated"),
                    }
                    for c in citations_by_qid.get(str(q.id), [])
                ],
            }
            for q in questions
        ]
    }


@router.get("/client/visibility")
async def client_visibility(
    client_id: str = Depends(get_current_client_id),
    db: AsyncSession = Depends(get_db),
):
    """AI 可见度得分：引用率翻译成 0-100 分。

    - platform_scores：按 model 分组，cited/total × 100 = 平台得分
    - overall_score：所有平台 cited 之和 / total 之和 × 100（加权平均，避免小样本平台噪声）
    - radar_data：labels = 平台中文名，values = 平台得分
    """
    if client_id == "admin":
        raise HTTPException(status_code=403, detail="本端点仅供客户使用")

    # 1. 客户的所有 citation_results（通过发稿 url 关联）
    client_urls = await _get_client_urls(db, client_id)
    if not client_urls:
        return {
            "overall_score": 0,
            "platform_scores": [],
            "radar_data": {"labels": [], "values": []},
        }

    cit_result = await db.execute(
        select(CitationResult).where(CitationResult.url.in_(client_urls))
    )
    all_citations = cit_result.scalars().all()

    if not all_citations:
        return {
            "overall_score": 0,
            "platform_scores": [],
            "radar_data": {"labels": [], "values": []},
        }

    # 2. 按 model 分组统计
    stats: dict[str, dict[str, int]] = {}
    for c in all_citations:
        s = stats.setdefault(c.model, {"total": 0, "cited": 0})
        s["total"] += 1
        if c.hit_type in CITED_HIT_TYPES:
            s["cited"] += 1

    # 3. 批量获取置信度
    from app.services.calibration_service import CalibrationService
    cal_service = CalibrationService(db)
    all_confidence = await cal_service.get_all_confidence()
    confidence_by_model = {c["model"]: c for c in all_confidence}

    # 4. 计算每个平台得分
    platform_scores = []
    for model, s in stats.items():
        score = (s["cited"] / s["total"] * 100) if s["total"] > 0 else 0
        conf = confidence_by_model.get(model, {})
        platform_scores.append({
            "model": model,
            "score": round(score),
            "total": s["total"],
            "cited": s["cited"],
            "confidence": conf.get("confidence", -1),
            "confidence_level": conf.get("level", "uncalibrated"),
        })
    # 按 score 降序，让前端展示更稳定
    platform_scores.sort(key=lambda x: x["score"], reverse=True)

    # 5. 综合得分（加权平均：总 cited / 总 total × 100）
    grand_total = sum(s["total"] for s in stats.values())
    grand_cited = sum(s["cited"] for s in stats.values())
    overall_score = round(grand_cited / grand_total * 100) if grand_total > 0 else 0

    # 6. 雷达图数据
    radar_labels = [MODEL_DISPLAY_NAMES.get(p["model"], p["model"]) for p in platform_scores]
    radar_values = [p["score"] for p in platform_scores]

    return {
        "overall_score": overall_score,
        "platform_scores": platform_scores,
        "radar_data": {
            "labels": radar_labels,
            "values": radar_values,
        },
    }


# ============================================================================
# 阶段 4：客户端置信度 API
# 基于网页端校准数据，向客户展示各平台置信度，便于评估数据可靠性。
# ============================================================================


@router.get("/client/confidence")
async def client_confidence(
    client_id: str = Depends(get_current_client_id),
    db: AsyncSession = Depends(get_db),
):
    """客户查看各平台置信度。

    返回各平台的置信度分数和分级，以及综合置信度。
    置信度基于网页端校准数据——校准数据越多，置信度越可靠。
    """
    if client_id == "admin":
        raise HTTPException(status_code=403, detail="本端点仅供客户使用")

    from app.services.calibration_service import CalibrationService

    service = CalibrationService(db)
    platforms = await service.get_all_confidence()

    # 综合置信度：有校准数据的平台的加权平均（按校准数量加权）
    calibrated_platforms = [p for p in platforms if p["total_calibrations"] > 0]
    if calibrated_platforms:
        total_weight = sum(p["total_calibrations"] for p in calibrated_platforms)
        weighted_sum = sum(p["confidence"] * p["total_calibrations"] for p in calibrated_platforms)
        overall_confidence = round(weighted_sum / total_weight) if total_weight > 0 else -1
    else:
        overall_confidence = -1

    return {
        "platforms": platforms,
        "overall_confidence": overall_confidence,
    }
