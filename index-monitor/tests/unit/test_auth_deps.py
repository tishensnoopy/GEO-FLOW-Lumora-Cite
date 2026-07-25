# index-monitor/tests/unit/test_auth_deps.py
"""鉴权依赖测试：get_current_super_admin + get_current_user。

get_current_admin 已在 app/core/auth.py 实现（Plan 1），本任务补 super_admin 校验。
"""
import pytest
import jwt
from datetime import datetime, timedelta, timezone

from app.core.config import settings


def _make_admin_token(role: str = "admin") -> str:
    """签发测试用 admin JWT。"""
    payload = {
        "sub": "1",
        "name": "测试管理员",
        "role": role,
        "type": "admin",
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.SSO_JWT_SECRET, algorithm="HS256")


@pytest.mark.asyncio
async def test_get_current_super_admin_with_super_admin_token():
    """裁定 1：get_current_super_admin 用 Depends(get_current_admin)，
    签名为 admin: dict。直接调用时先 await get_current_admin 拿到 admin dict，
    再传给 get_current_super_admin 验证 role。"""
    from app.api.deps import get_current_super_admin
    from app.core.auth import get_current_admin
    from fastapi.security import HTTPAuthorizationCredentials
    token = _make_admin_token(role="super_admin")
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    admin = await get_current_admin(credentials=creds)
    result = await get_current_super_admin(admin=admin)
    assert result["role"] == "super_admin"


@pytest.mark.asyncio
async def test_get_current_super_admin_rejects_plain_admin():
    """裁定 1：get_current_super_admin 用 Depends(get_current_admin)，
    签名为 admin: dict。普通 admin token 通过 get_current_admin 验证后，
    传给 get_current_super_admin 应因 role != super_admin 抛 403。"""
    from app.api.deps import get_current_super_admin
    from app.core.auth import get_current_admin
    from fastapi.security import HTTPAuthorizationCredentials
    from fastapi import HTTPException
    token = _make_admin_token(role="admin")
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    admin = await get_current_admin(credentials=creds)
    with pytest.raises(HTTPException) as exc:
        await get_current_super_admin(admin=admin)
    assert exc.value.status_code == 403
    assert "超级管理员" in exc.value.detail


@pytest.mark.asyncio
async def test_get_current_user_returns_admin_dict_for_admin_token():
    from app.api.deps import get_current_user
    from fastapi.security import HTTPAuthorizationCredentials
    token = _make_admin_token(role="admin")
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    user, role = await get_current_user(credentials=creds)
    assert isinstance(user, dict)
    assert role == "admin"


@pytest.mark.asyncio
async def test_get_current_user_returns_client_for_client_token(db_session):
    """client JWT 用 SECRET_KEY 签发，get_current_user 识别 type=client 时查 DB。"""
    from app.api.deps import get_current_user
    from app.core.security import create_access_token
    from app.models.client import Client
    from sqlalchemy import select

    # 自审发现：简报用 "test_client_001" 但该 ID 已被 test_client_lifecycle_fields.py
    # 遗留数据占用（status=active），导致 get_current_user 不抛 401。
    # 改用确定不存在的 client_id 隔离测试数据。
    token = create_access_token({"sub": "task7_nonexistent_client", "role": "client", "type": "client"})
    from fastapi.security import HTTPAuthorizationCredentials
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    # 如果 DB 没有 test_client_001，get_current_user 应抛 401
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        await get_current_user(credentials=creds, db=db_session)
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_get_current_user_missing_token_raises_401():
    """裁定 3 边界测试 1：credentials=None → 401 missing_token。"""
    from app.api.deps import get_current_user
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await get_current_user(credentials=None)
    assert exc.value.status_code == 401
    assert exc.value.detail == "missing_token"


@pytest.mark.asyncio
async def test_get_current_user_invalid_token_raises_401():
    """裁定 3 边界测试 2：credentials=无效字符串 → 401 invalid_token。

    无效字符串既不是合法 admin JWT（SSO_JWT_SECRET 解码失败），
    也不是合法 client JWT（SECRET_KEY 解码失败 → decode_token 返回 {}）。
    """
    from app.api.deps import get_current_user
    from fastapi.security import HTTPAuthorizationCredentials
    from fastapi import HTTPException

    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="not.a.valid.jwt")
    with pytest.raises(HTTPException) as exc:
        await get_current_user(credentials=creds)
    assert exc.value.status_code == 401
    assert exc.value.detail == "invalid_token"
