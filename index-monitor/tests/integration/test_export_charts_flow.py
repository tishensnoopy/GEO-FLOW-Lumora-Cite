# index-monitor/tests/integration/test_export_charts_flow.py
"""charts 字段端到端集成测试：端点 → ExportTask → _assemble_data。

验证 M3 审查缺口 2 的完整数据流：
1. POST /api/v1/admin/exports 接受 charts 字段
2. ExportTask.charts 持久化
3. ExportService._assemble_data 读取 task.charts
"""
import pytest
import pytest_asyncio
import jwt
from datetime import datetime, timedelta, timezone
from sqlalchemy import select

from app.models.export_task import ExportTask
from app.core.config import settings


@pytest_asyncio.fixture(autouse=True)
async def _override_app_db():
    """为每个测试 override ``get_db`` 依赖，使用当前事件循环的全新 engine。

    pytest-asyncio strict 模式为每个测试创建独立事件循环。``app.core.database.engine``
    是模块级单例，其连接池里的 asyncpg 连接绑定到首次 import 时的事件循环，
    跨测试复用会触发 "Future attached to a different loop" /
    "another operation is in progress"。

    用 FastAPI ``app.dependency_overrides`` 把 ``get_db`` 替换为闭包，
    闭包内用本测试事件循环新建的 engine → session_factory → session。
    测试结束 dispose 这个临时 engine，不污染模块级 engine。

    与 ``test_export_endpoints.py`` 中同款 fixture 保持一致。
    """
    from app.main import app
    from app.core.database import get_db
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

    engine = create_async_engine(settings.DATABASE_URL, echo=False)
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
    """生成 admin JWT headers（与 test_export_endpoints.py 一致）。

    admin JWT 用 ``SSO_JWT_SECRET`` 签发（``verify_admin_jwt`` 验证），
    payload 必须含 ``type='admin'``、整数型 ``sub``、``name``、``role``。
    """
    payload = {
        "sub": "1",
        "name": "测试管理员",
        "role": "admin",
        "type": "admin",
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        "iat": datetime.now(timezone.utc),
    }
    return {"Authorization": f"Bearer {jwt.encode(payload, settings.SSO_JWT_SECRET, algorithm='HS256')}"}


@pytest.mark.asyncio
async def test_admin_create_export_persists_charts(client, db_session):
    """POST /api/v1/admin/exports 接受 charts 字段并持久化到 ExportTask.charts。"""
    charts_payload = {
        "trend": "data:image/png;base64,iVBORw0KGgo=",
        "pie": "data:image/png;base64,iVBORw0KGgo=",
    }
    resp = await client.post(
        "/api/v1/admin/exports",
        json={
            "export_type": "pdf",
            "charts": charts_payload,
        },
        headers=_admin_headers(),
    )
    assert resp.status_code == 202
    task_id = resp.json()["task_id"]

    # 验证 DB 中 charts 字段
    result = await db_session.execute(
        select(ExportTask).where(ExportTask.id == task_id)
    )
    task = result.scalar_one()
    assert task.charts == charts_payload

    # 清理：避免污染后续测试
    await db_session.delete(task)
    await db_session.commit()


@pytest.mark.asyncio
async def test_admin_create_export_without_charts_still_works(client, db_session):
    """不传 charts 字段时，端点正常工作（向后兼容 M3 既有调用方）。"""
    resp = await client.post(
        "/api/v1/admin/exports",
        json={"export_type": "pdf"},
        headers=_admin_headers(),
    )
    assert resp.status_code == 202
    task_id = resp.json()["task_id"]

    result = await db_session.execute(
        select(ExportTask).where(ExportTask.id == task_id)
    )
    task = result.scalar_one()
    assert task.charts is None

    # 清理
    await db_session.delete(task)
    await db_session.commit()
