# index-monitor/tests/unit/test_calibration_service.py
"""CalibrationService 校准服务测试。"""
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from app.services.calibration_service import CalibrationService, compare_hits, get_confidence_level


def test_compare_hits_both_cited_exact():
    """API exact vs 网页 exact → 一致。"""
    assert compare_hits("exact", "exact") is True


def test_compare_hits_both_cited_mixed():
    """API exact vs 网页 domain → 一致（都算被引用）。"""
    assert compare_hits("exact", "domain") is True


def test_compare_hits_both_none():
    """API none vs 网页 none → 一致。"""
    assert compare_hits("none", "none") is True


def test_compare_hits_api_cited_web_none():
    """API cited vs 网页 none → 不一致。"""
    assert compare_hits("exact", "none") is False


def test_compare_hits_api_none_web_cited():
    """API none vs 网页 cited → 不一致。"""
    assert compare_hits("none", "domain") is False


def test_get_confidence_level_high():
    """≥80% → high。"""
    assert get_confidence_level(85) == "high"
    assert get_confidence_level(80) == "high"


def test_get_confidence_level_medium():
    """50-79% → medium。"""
    assert get_confidence_level(79) == "medium"
    assert get_confidence_level(50) == "medium"


def test_get_confidence_level_low():
    """<50% → low。"""
    assert get_confidence_level(49) == "low"
    assert get_confidence_level(0) == "low"


def test_get_confidence_level_uncalibrated():
    """-1 → uncalibrated。"""
    assert get_confidence_level(-1) == "uncalibrated"


@pytest.mark.asyncio
async def test_run_calibration_no_platforms(db_session, monkeypatch):
    """无可用网页端模拟平台时返回空结果。"""
    monkeypatch.setattr(
        "app.services.calibration_service.get_web_simulation_manager",
        lambda: MagicMock(available_platforms=lambda: []),
    )
    service = CalibrationService(db_session)
    result = await service.run_calibration()
    assert result == {}


@pytest.mark.asyncio
async def test_get_platform_confidence_no_data(db_session):
    """无校准数据时返回 uncalibrated。"""
    service = CalibrationService(db_session)
    result = await service.get_platform_confidence("yuanbao")
    assert result["level"] == "uncalibrated"
    assert result["confidence"] == -1
    assert result["total_calibrations"] == 0


@pytest.mark.asyncio
async def test_get_all_confidence_empty(db_session):
    """无校准数据时返回空列表。"""
    service = CalibrationService(db_session)
    result = await service.get_all_confidence()
    assert result == []
