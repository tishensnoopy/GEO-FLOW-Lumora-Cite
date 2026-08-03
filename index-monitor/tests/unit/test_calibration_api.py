# index-monitor/tests/unit/test_calibration_api.py
"""校准 API 端点测试（阶段 4 任务 3）。

验证：
1. POST /api/v1/admin/calibration/trigger 触发校准，返回各平台采样统计
2. GET /api/v1/admin/calibration/results 查看各平台置信度概览

JWT 鉴权用 admin token（SSO_JWT_SECRET 签发，payload type='admin'），
与 test_scan_estimate.py 一致。CalibrationService 的方法用 AsyncMock patch，
避免依赖真实网页端模拟平台。
"""
import pytest
import pytest_asyncio
import jwt
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, AsyncMock

from app.core.config import settings


@pytest_asyncio.fixture(autouse=True)
async def _override_app_db():
    """为每个测试 override get_db 依赖，使用当前事件循环的全新 engine。

    与 test_scan_estimate.py::_override_app_db 一致，解决 pytest-asyncio strict
    模式下模块级 engine 跨事件循环复用问题。
    """
    from app.main import app
    from app.core.database import get_db
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
    from sqlalchemy.pool import NullPool

    engine = create_async_engine(settings.DATABASE_URL, echo=False, poolclass=NullPool)
    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async def _get_db_override():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _get_db_override
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


def _admin_headers() -> dict:
    """生成 admin JWT 鉴权头，与 test_scan_estimate.py 一致。"""
    payload = {
        "sub": "1",
        "name": "测试管理员",
        "role": "admin",
        "type": "admin",
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        "iat": datetime.now(timezone.utc),
    }
    return {
        "Authorization": f"Bearer {jwt.encode(payload, settings.SSO_JWT_SECRET, algorithm='HS256')}"
    }


@pytest.mark.asyncio
async def test_trigger_calibration(client):
    """POST /admin/calibration/trigger 触发校准，返回各平台采样统计。"""
    with patch(
        "app.services.calibration_service.CalibrationService.run_calibration",
        new_callable=AsyncMock,
        return_value={
            "yuanbao": {
                "sampled": 5,
                "calibrated": 5,
                "matched": 4,
                "match_rate": 80.0,
            }
        },
    ):
        resp = await client.post(
            "/api/v1/admin/calibration/trigger",
            headers=_admin_headers(),
            params={"sample_rate": 0.1},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert "yuanbao" in data
    assert data["yuanbao"]["sampled"] == 5
    assert data["yuanbao"]["calibrated"] == 5
    assert data["yuanbao"]["matched"] == 4
    assert data["yuanbao"]["match_rate"] == 80.0


@pytest.mark.asyncio
async def test_get_calibration_results(client):
    """GET /admin/calibration/results 查看校准结果（各平台置信度）。"""
    with patch(
        "app.services.calibration_service.CalibrationService.get_all_confidence",
        new_callable=AsyncMock,
        return_value=[
            {
                "model": "yuanbao",
                "confidence": 80,
                "level": "high",
                "total_calibrations": 10,
                "matched": 8,
            }
        ],
    ):
        resp = await client.get(
            "/api/v1/admin/calibration/results",
            headers=_admin_headers(),
        )

    assert resp.status_code == 200
    data = resp.json()
    assert "platforms" in data
    assert len(data["platforms"]) == 1
    assert data["platforms"][0]["model"] == "yuanbao"
    assert data["platforms"][0]["level"] == "high"
    assert data["platforms"][0]["confidence"] == 80
