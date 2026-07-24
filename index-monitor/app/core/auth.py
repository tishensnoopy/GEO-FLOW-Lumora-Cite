# index-monitor/app/core/auth.py
"""admin JWT 鉴权依赖——与 ``app/api/sso_routes.py`` 共享 JWT 契约。

JWT 契约
========

- payload: ``sub``（user_id 字符串） / ``name`` / ``role`` / ``type="admin"`` / ``exp`` / ``iat``；
- 算法 HS256；密钥 ``settings.SSO_JWT_SECRET``；
- 有效期 ``settings.SSO_JWT_EXPIRE_DAYS`` 天。

签发端在 ``app/api/sso_routes.py::_sign_jwt``，验证端在本模块。两端共享
``settings.SSO_JWT_SECRET`` 与 payload schema，保证签发 / 验证一致。

错误模型
========

- ``token_expired``（401）：JWT 已过期 → ``jwt.ExpiredSignatureError``；
- ``invalid_token``（401）：签名错误 / 格式非法 / 缺字段 → ``jwt.InvalidTokenError``；
- ``not_admin``（403）：``type != "admin"``，token 本身合法但不是管理员类型；
- ``missing_token``（401）：FastAPI 依赖 ``get_current_admin`` 未拿到 Bearer 头。

设计要点
========

1. 用 ``HTTPBearer(auto_error=False)``：让依赖自己处理"缺少 Bearer 头"的 401，
   而不是让 FastAPI 框架直接返回 403（``auto_error=True`` 的默认行为），
   便于前端按 401 跳登录页；
2. ``verify_admin_jwt`` 是纯函数（无依赖注入），便于单元测试与在非 FastAPI
   上下文（如 WebSocket、后台任务）中复用；
3. ``get_current_admin`` 是薄封装，仅供 FastAPI 依赖注入用。
"""
from typing import Any

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import settings

# auto_error=False：缺少 Bearer 头时返回 None 而非框架默认 403，
# 让 get_current_admin 统一抛 401 missing_token（前端按 401 跳登录页）。
_security = HTTPBearer(auto_error=False)


def verify_admin_jwt(token: str) -> dict[str, Any]:
    """验证 admin JWT，返回 ``{user_id, name, role}``。

    Parameters
    ----------
    token : str
        客户端透传的 JWT 字符串（不含 "Bearer " 前缀）。

    Returns
    -------
    dict
        ``{"user_id": int, "name": str, "role": str}``。

    Raises
    ------
    HTTPException
        - 401 ``token_expired``：JWT 已过期；
        - 401 ``invalid_token``：签名错误 / 格式非法 / 缺关键字段；
        - 403 ``not_admin``：``type != "admin"``。
    """
    try:
        payload = jwt.decode(token, settings.SSO_JWT_SECRET, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="token_expired")
    except jwt.InvalidTokenError:
        # DecodeError / InvalidSignatureError / MissingRequiredClaimError 等都继承自 InvalidTokenError
        raise HTTPException(status_code=401, detail="invalid_token")

    if payload.get("type") != "admin":
        raise HTTPException(status_code=403, detail="not_admin")

    # 缺 sub / name / role 视为非法 token（防御性，签发端应保证字段完整）
    sub = payload.get("sub")
    name = payload.get("name")
    role = payload.get("role")
    if sub is None or name is None or role is None:
        raise HTTPException(status_code=401, detail="invalid_token")

    try:
        user_id = int(sub)
    except (TypeError, ValueError):
        raise HTTPException(status_code=401, detail="invalid_token")

    return {"user_id": user_id, "name": name, "role": role}


async def get_current_admin(
    credentials: HTTPAuthorizationCredentials | None = Depends(_security),
) -> dict[str, Any]:
    """FastAPI 依赖：从 Authorization Bearer 头提取并验证 admin JWT。

    用法::

        @router.get("/admin/clients", dependencies=[Depends(get_current_admin)])
        async def list_clients(): ...
    """
    if credentials is None:
        raise HTTPException(status_code=401, detail="missing_token")
    return verify_admin_jwt(credentials.credentials)
