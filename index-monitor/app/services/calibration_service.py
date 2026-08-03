# index-monitor/app/services/calibration_service.py
"""引用检测校准服务（阶段 4）。

采样 citation_results，用网页端模拟重新检测，对比 API vs 网页端结果，
计算平台置信度。
"""
import logging
import random
from uuid import UUID
from typing import Optional

from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.citation_result import CitationResult
from app.models.citation_calibration import CitationCalibration
from app.services.web_simulation import get_web_simulation_manager

logger = logging.getLogger(__name__)

CITED_HIT_TYPES = ("exact", "domain")
DEFAULT_SAMPLE_RATE = 0.1
MIN_SAMPLE_SIZE = 5


def compare_hits(api_hit: str, web_hit: str) -> bool:
    """对比 API 与网页端命中类型是否一致。

    一致定义：两者都判定为"被引用"（exact/domain）或都"未被引用"（none）。
    不区分 exact 和 domain——两者都算被引用。
    """
    api_cited = api_hit in CITED_HIT_TYPES
    web_cited = web_hit in CITED_HIT_TYPES
    return api_cited == web_cited


def get_confidence_level(confidence: int) -> str:
    """置信度分级。

    -1 → uncalibrated（无校准数据）
    ≥80 → high
    50-79 → medium
    <50 → low
    """
    if confidence < 0:
        return "uncalibrated"
    if confidence >= 80:
        return "high"
    if confidence >= 50:
        return "medium"
    return "low"


class CalibrationService:
    """引用检测校准服务。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def run_calibration(
        self, sample_rate: float = DEFAULT_SAMPLE_RATE
    ) -> dict:
        """执行一轮校准。

        1. 获取已注册的网页端模拟平台
        2. 对每个平台，从 citation_results 采样
        3. 用网页端模拟重新检测
        4. 对比并存入 citation_calibrations
        返回 {platform_id: {sampled, calibrated, matched, match_rate}}
        """
        manager = get_web_simulation_manager()
        platforms = manager.available_platforms()
        if not platforms:
            logger.info("校准跳过：无可用网页端模拟平台")
            return {}

        results: dict[str, dict] = {}
        for platform_id in platforms:
            stats = await self._calibrate_platform(platform_id, sample_rate)
            results[platform_id] = stats

        return results

    async def _calibrate_platform(
        self, platform_id: str, sample_rate: float
    ) -> dict:
        """对单个平台执行校准。"""
        # 1. 采样待校准的 citation_results
        samples = await self._sample_citation_results(platform_id, sample_rate)
        if not samples:
            logger.info("校准跳过 %s：无可校准数据", platform_id)
            return {"sampled": 0, "calibrated": 0, "matched": 0, "match_rate": 0}

        manager = get_web_simulation_manager()
        calibrated = 0
        matched = 0

        for cit in samples:
            # 2. 用网页端模拟重新检测
            target_urls = [cit.url] if cit.url else []
            try:
                sim_result = await manager.simulate(
                    platform_id, cit.question, target_urls, timeout=60,
                )
            except Exception as exc:
                logger.warning("校准 %s 模拟失败 %s: %s", platform_id, cit.id, exc)
                await self._save_calibration(
                    cit, platform_id, "", [], "none",
                    note=f"模拟异常: {exc}", matches=False,
                )
                calibrated += 1
                continue

            if not sim_result.success:
                await self._save_calibration(
                    cit, platform_id, sim_result.answer or "",
                    sim_result.sources, "none",
                    note=sim_result.error or "模拟失败",
                    matches=False,
                )
                calibrated += 1
                continue

            # 3. 判定网页端命中类型
            from app.services.citation_check.matching import classify_citation_hit
            source_urls = [s.get("url", "") for s in sim_result.sources if s.get("url")]
            web_hit = classify_citation_hit(target_urls, source_urls).layer

            # 4. 对比
            is_match = compare_hits(cit.hit_type, web_hit)
            await self._save_calibration(
                cit, platform_id, sim_result.answer,
                sim_result.sources, web_hit,
                note=None, matches=is_match,
            )
            calibrated += 1
            if is_match:
                matched += 1

        match_rate = (matched / calibrated * 100) if calibrated > 0 else 0
        return {
            "sampled": len(samples),
            "calibrated": calibrated,
            "matched": matched,
            "match_rate": round(match_rate, 1),
        }

    async def _sample_citation_results(
        self, platform_id: str, sample_rate: float
    ) -> list[CitationResult]:
        """采样待校准的 citation_results。

        1. 查所有 citation_results（排除已校准的）
        2. 按 sample_rate 随机采样，不低于 MIN_SAMPLE_SIZE
        """
        # 查已校准的 citation_result_id
        calibrated_result = await self.db.execute(
            select(CitationCalibration.citation_result_id).where(
                CitationCalibration.platform_id == platform_id
            )
        )
        calibrated_ids = {row[0] for row in calibrated_result.fetchall()}

        # 查所有 citation_results
        all_result = await self.db.execute(
            select(CitationResult).order_by(CitationResult.checked_at.desc())
        )
        all_citations = all_result.scalars().all()

        # 排除已校准的
        candidates = [c for c in all_citations if c.id not in calibrated_ids]
        if not candidates:
            return []

        # 采样
        sample_size = max(int(len(candidates) * sample_rate), MIN_SAMPLE_SIZE)
        sample_size = min(sample_size, len(candidates))
        return random.sample(candidates, sample_size)

    async def _save_calibration(
        self, cit: CitationResult, platform_id: str,
        web_answer: str, web_sources: list, web_hit_type: str,
        note: Optional[str], matches: bool,
    ) -> None:
        """保存校准结果。"""
        calibration = CitationCalibration(
            citation_result_id=cit.id,
            platform_id=platform_id,
            web_answer=web_answer,
            web_sources=web_sources,
            web_hit_type=web_hit_type,
            api_hit_type=cit.hit_type,
            matches=matches,
            note=note,
        )
        self.db.add(calibration)
        await self.db.commit()

    async def get_platform_confidence(self, model: str) -> dict:
        """获取某平台的置信度。

        model 参数对应 citation_results.model 字段。
        注意：校准平台的 platform_id（如 yuanbao）可能与 citation_results.model
        不同。此处按 citation_calibrations.platform_id 查询。
        """
        result = await self.db.execute(
            select(
                func.count(CitationCalibration.id).label("total"),
                func.count(CitationCalibration.id).filter(
                    CitationCalibration.matches.is_(True)
                ).label("matched"),
            ).where(CitationCalibration.platform_id == model)
        )
        row = result.one()
        total = row.total or 0
        matched = row.matched or 0

        if total == 0:
            return {
                "model": model,
                "confidence": -1,
                "level": "uncalibrated",
                "total_calibrations": 0,
                "matched": 0,
            }

        confidence = round(matched / total * 100)
        return {
            "model": model,
            "confidence": confidence,
            "level": get_confidence_level(confidence),
            "total_calibrations": total,
            "matched": matched,
        }

    async def get_all_confidence(self) -> list[dict]:
        """获取所有有校准数据的平台置信度列表。"""
        result = await self.db.execute(
            select(CitationCalibration.platform_id).distinct()
        )
        platforms = [row[0] for row in result.fetchall()]
        return [await self.get_platform_confidence(p) for p in platforms]

    async def get_result_confidence(
        self, citation_result_id: UUID, hit_type: str
    ) -> dict:
        """获取单条引用检测结果的置信度。

        基于该条所属平台的置信度 × 命中类型权重。
        """
        # 先查该条结果所属的 model
        cit_result = await self.db.execute(
            select(CitationResult.model).where(CitationResult.id == citation_result_id)
        )
        row = cit_result.first()
        if row is None:
            return {"confidence": -1, "level": "uncalibrated"}

        platform_conf = await self.get_platform_confidence(row[0])

        # 命中类型权重
        if hit_type == "exact":
            weight = 1.0
        elif hit_type == "domain":
            weight = 0.8
        else:
            return {"confidence": -1, "level": "uncalibrated"}

        if platform_conf["confidence"] < 0:
            return {"confidence": -1, "level": "uncalibrated"}

        adjusted = round(platform_conf["confidence"] * weight)
        return {
            "confidence": adjusted,
            "level": get_confidence_level(adjusted),
        }
