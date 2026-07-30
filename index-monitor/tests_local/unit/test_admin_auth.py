"""Task 12：admin JWT 鉴权依赖单元测试（TDD RED 阶段先写）。

验证目标
========

1. ``verify_admin_jwt(token)`` 能正确解析有效 admin JWT，返回
   ``{user_id, name, role}``；
2. 过期 JWT → 抛 ``HTTPException(401, token_expired)``；
3. ``type`` 字段不是 ``admin`` 的 JWT → 抛 ``HTTPException(403, not_admin)``；
4. 签名错误 / 格式非法的 token → 抛 ``HTTPException(401, invalid_token)``；
5. ``get_current_admin`` 依赖在缺少 Bearer 头时抛 401。

JWT 契约（与 task 11 callback 签发端共享）
==========================================

- payload: ``sub``（user_id 字符串） / ``name`` / ``role`` / ``type="admin"`` / ``exp`` / ``iat``；
- 算法 HS256；密钥 ``settings.SSO_JWT_SECRET``；
- 有效期 ``settings.SSO_JWT_EXPIRE_DAYS`` 天。

实现说明
========

- 用 PyJWT（``import jwt``）直接签发测试 token，不依赖 callback 端点，
  保持单元测试独立性；
- ``verify_admin_jwt`` 应捕获 ``jwt.ExpiredSignatureError`` / ``jwt.InvalidTokenError``
  并转换为 ``HTTPException``，避免底层异常透传到 FastAPI 框架。
"""
import pytest
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import HTTPException

from app.core.auth import get_current_admin, verify_admin_jwt
from app.core.config import settings


def _make_token(
    *,
    sub: str = "1",
    name: str = "管理员",
    role: str = "admin",
    token_type: str = "admin",
    exp_delta: timedelta = timedelta(hours=1),
) -> str:
    """生成测试用 admin JWT。"""
    payload = {
        "sub": sub,
        "name": name,
        "role": role,
        "type": token_type,
        "exp": datetime.now(timezone.utc) + exp_delta,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.SSO_JWT_SECRET, algorithm="HS256")


def test_verify_admin_jwt_valid_token():
    """验证有效 JWT 能正确解析。"""
    token = _make_token(sub="1", name="管理员", role="admin")

    result = verify_admin_jwt(token)
    assert result["user_id"] == 1
    assert result["name"] == "管理员"
    assert result["role"] == "admin"


def test_verify_admin_jwt_expired_raises():
    """验证过期 JWT 抛出 401 HTTPException。"""
    token = _make_token(exp_delta=timedelta(hours=-1))  # 已过期

    with pytest.raises(HTTPException) as exc_info:
        verify_admin_jwt(token)
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "token_expired"


def test_verify_admin_jwt_wrong_type_raises():
    """验证非 admin 类型的 JWT 被拒绝（403）。"""
    token = _make_token(token_type="client", role="client", name="客户")

    with pytest.raises(HTTPException) as exc_info:
        verify_admin_jwt(token)
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "not_admin"


def test_verify_admin_jwt_invalid_signature_raises():
    """验证签名错误的 token 抛 401。"""
    payload = {
        "sub": "1",
        "name": "管理员",
        "role": "admin",
        "type": "admin",
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
    }
    # 用错误的密钥签发
    token = jwt.encode(payload, "wrong-secret", algorithm="HS256")

    with pytest.raises(HTTPException) as exc_info:
        verify_admin_jwt(token)
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "invalid_token"


def test_verify_admin_jwt_malformed_token_raises():
    """验证格式非法的 token 抛 401。"""
    with pytest.raises(HTTPException) as exc_info:
        verify_admin_jwt("not.a.jwt")
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "invalid_token"


@pytest.mark.asyncio
async def test_get_current_admin_missing_credentials_raises():
    """验证 get_current_admin 在缺少 Bearer 头时抛 401。"""
    with pytest.raises(HTTPException) as exc_info:
        await get_current_admin(credentials=None)
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "missing_token"


@pytest.mark.asyncio
async def test_get_current_admin_valid_credentials_returns_user():
    """验证 get_current_admin 在有效 Bearer 头时返回用户信息。"""
    from fastapi.security import HTTPAuthorizationCredentials

    token = _make_token(sub="42", name="超级管理员", role="super_admin")
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    result = await get_current_admin(credentials=credentials)
    assert result["user_id"] == 42
    assert result["name"] == "超级管理员"
    assert result["role"] == "super_admin"
