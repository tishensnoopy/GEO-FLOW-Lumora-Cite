"""鉴权依赖集合。

职责分工
========

- ``app/core/auth.py``：admin JWT 验证（``verify_admin_jwt`` + ``get_current_admin``），
  用 ``SSO_JWT_SECRET``，HS256；
- ``app/api/deps.py``（本文件）：
  - ``get_current_client_id``：旧入口，从 client JWT 提取 client_id（向后兼容）；
  - ``get_current_super_admin``：在 ``get_current_admin`` 基础上要求 super_admin 角色；
  - ``get_current_user``：统一鉴权入口，按 JWT payload 的 ``type`` 字段分流
    admin / client，返回 ``(user, role)`` 元组供调用方判断权限边界。

JWT 双轨制
==========

- admin JWT：SSO 签发，用 ``SSO_JWT_SECRET``，payload ``type='admin'``；
- client JWT：客户登录签发，用 ``SECRET_KEY``，payload ``type='client'``。

变更说明
========

Task 7（裁定 1：增量修改，不完整替换）：
- 保留原 ``oauth2_scheme`` + ``get_current_client_id``（向后兼容，旧路由仍可用）；
- 追加 ``_security = HTTPBearer(auto_error=False)`` 作为统一入口的 Bearer 提取器；
- 追加 ``get_current_super_admin``（依赖 ``get_current_admin``）；
- 追加 ``get_current_user``（依赖 ``_security`` + ``get_db``）；
- 顶部 import 补充（裁定 2）：``jwt`` / ``select`` / ``AsyncSession`` /
  ``HTTPAuthorizationCredentials`` / ``HTTPBearer`` / ``get_current_admin`` /
  ``verify_admin_jwt`` / ``get_db`` / ``Client``。
"""
from typing import Any, Union

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import (
    HTTPAuthorizationCredentials,
    HTTPBearer,
    OAuth2PasswordBearer,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_admin, verify_admin_jwt
from app.core.config import settings
from app.core.database import get_db
from app.core.security import decode_token
from app.models.client import Client

# 向后兼容：旧路由用 OAuth2PasswordBearer 接收 client token
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")

# 统一入口用 HTTPBearer(auto_error=False)：缺少 Bearer 头时返回 None 而非框架默认 403，
# 让 get_current_user 统一抛 401 missing_token（前端按 401 跳登录页）。
_security = HTTPBearer(auto_error=False)


async def get_current_client_id(token: str = Depends(oauth2_scheme)) -> str:
    """从 client JWT 提取 client_id（向后兼容，旧路由仍可用）。"""
    payload = decode_token(token)
    client_id = payload.get("sub")
    if not client_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="无效或过期的 token")
    return client_id


async def get_current_super_admin(
    admin: dict = Depends(get_current_admin),
) -> dict[str, Any]:
    """要求 super_admin 角色。admin 已由 ``get_current_admin`` 验证。"""
    if admin["role"] != "super_admin":
        raise HTTPException(status_code=403, detail="需要超级管理员权限")
    return admin


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_security),
    db: AsyncSession = Depends(get_db),
) -> tuple[Union[dict, Client], str]:
    """统一鉴权入口：返回 ``(user, role)``。

    根据 JWT payload 的 ``type`` 字段分流：

    - ``type='admin'``：调用 ``verify_admin_jwt`` 复用完整校验逻辑
      （包含 type/role/sub 校验 + 过期检查），返回 ``(admin_dict, role)``；
    - ``type='client'``（或 admin 解码失败回退）：用 ``SECRET_KEY`` 解码，
      查 ``monitor.clients`` 表，返回 ``(Client 对象, 'client')``。

    调用方根据 ``role`` 判断权限边界。
    """
    if credentials is None:
        raise HTTPException(status_code=401, detail="missing_token")

    token = credentials.credentials

    # 先尝试用 SSO_JWT_SECRET 解码（admin token）
    try:
        payload = jwt.decode(token, settings.SSO_JWT_SECRET, algorithms=["HS256"])
        if payload.get("type") == "admin":
            # admin token：直接调用 verify_admin_jwt 复用完整校验逻辑
            # （包含 type/role/sub 校验 + 过期检查）
            admin = verify_admin_jwt(token)
            return admin, admin["role"]
    except jwt.InvalidTokenError:
        pass  # 不是 admin token，尝试 client token

    # client token：用 SECRET_KEY 解码
    payload = decode_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="invalid_token")

    client_id = payload.get("sub")
    if not client_id:
        raise HTTPException(status_code=401, detail="invalid_token")

    result = await db.execute(
        select(Client).where(Client.client_id == client_id)
    )
    client = result.scalar_one_or_none()
    if not client or client.status != "active":
        raise HTTPException(status_code=401, detail="客户账号不存在或已禁用")

    return client, "client"
