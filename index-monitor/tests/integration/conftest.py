"""集成测试共享 fixture。

本文件提供跨任务复用的鉴权 fixture（admin_auth_headers / client_auth_headers），
后续任务 3/4/6/7 的集成测试可直接依赖。同时提供 ``_clean_client_questions``
autouse fixture 清理 ``monitor.client_questions`` 表，保证测试间数据隔离。

JWT 双轨制（参考 ``app/api/deps.py``）：
- admin JWT：用 ``SSO_JWT_SECRET`` 签发，payload ``type='admin'``，对应
  ``get_current_admin`` 鉴权依赖；
- client JWT：用 ``SECRET_KEY`` 签发，payload ``type='client'``，对应
  ``get_current_client_id`` 鉴权依赖（仅解 JWT 返回 sub，不查 Client 表）。
"""
import uuid  # noqa: F401  # 保留供后续任务扩展使用
from datetime import datetime, timedelta, timezone

import jwt
import pytest_asyncio

from app.core.config import settings


@pytest_asyncio.fixture
async def admin_auth_headers() -> dict:
    """构造 admin JWT 请求头（用 SSO_JWT_SECRET 签发，对应 get_current_admin）。

    payload 字段对齐 ``app/core/auth.py::verify_admin_jwt`` 的校验逻辑：
    sub / name / role / type='admin' / exp / iat 均必填。
    """
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


@pytest_asyncio.fixture
async def client_auth_headers() -> dict:
    """构造 client JWT 请求头（用 SECRET_KEY 签发，sub=DEMO001）。

    ``get_current_client_id`` 只解 JWT 返回 sub，不查 Client 表，
    所以无需 DEMO001 客户在 DB 中存在。参考 ``test_distribution_endpoint.py``
    的 ``_client_headers`` 同款模式。
    """
    payload = {
        "sub": "DEMO001",
        "type": "client",
        "role": "client",
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
    }
    return {
        "Authorization": f"Bearer {jwt.encode(payload, settings.SECRET_KEY, algorithm='HS256')}"
    }


@pytest_asyncio.fixture
async def client_a_headers() -> dict:
    """构造 client JWT 请求头（用 SECRET_KEY 签发，sub=DEMO001）。

    Task 7 客户端只读 API 数据隔离测试需要同时持有两个客户的鉴权头，
    本 fixture 与 ``client_auth_headers`` 等价（DEMO001），命名上加 ``_a``
    后缀与 ``client_b_headers``（DEMO002）对齐，便于测试中直观区分。
    """
    payload = {
        "sub": "DEMO001",
        "type": "client",
        "role": "client",
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
    }
    return {
        "Authorization": f"Bearer {jwt.encode(payload, settings.SECRET_KEY, algorithm='HS256')}"
    }


@pytest_asyncio.fixture
async def client_b_headers() -> dict:
    """构造 client JWT 请求头（用 SECRET_KEY 签发，sub=DEMO002）。

    用于 Task 7 数据隔离测试：验证 DEMO001 客户无法看到 DEMO002 的数据。
    """
    payload = {
        "sub": "DEMO002",
        "type": "client",
        "role": "client",
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
    }
    return {
        "Authorization": f"Bearer {jwt.encode(payload, settings.SECRET_KEY, algorithm='HS256')}"
    }


@pytest_asyncio.fixture(autouse=True)
async def _clean_client_questions(db_session):
    """每个测试前清理 ``monitor.client_questions`` 表，避免数据污染。

    ``db_session`` fixture 仅做事件循环隔离（每测试新建 engine），不做数据回滚；
    本文件所有 client_question 相关测试共用 client_id="DEMO001"，若不清理会相互污染
    （如 create_question 自动 sort_order 的 max(sort_order) 受前置测试影响）。

    autouse 设计：放在 ``tests/integration/conftest.py`` 顶层，对目录下所有集成测试
    生效。对不操作 ``client_questions`` 表的测试，DELETE 一张空表是无害的 no-op。
    """
    from sqlalchemy import text

    await db_session.execute(text("DELETE FROM monitor.client_questions"))
    await db_session.commit()
    yield
