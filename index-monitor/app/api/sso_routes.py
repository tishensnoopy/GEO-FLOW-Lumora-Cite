# index-monitor/app/api/sso_routes.py
"""SSO 路由：login（跳转 GEOFlow 授权页）+ callback（接收 code，签发 admin JWT）。

集成流程
========

1. 浏览器访问 ``GET /sso/login`` → 30x 重定向到 GEOFlow ``/sso/authorize``；
2. GEOFlow 已登录管理员 → 签发一次性 code（30s 过期，GETDEL 单次消费），
   回跳到 ``SSO_REDIRECT_URI?code=xxx``（即 ``GET /sso/callback``）；
3. callback 调 ``SsoService.exchange_code(code)`` 换取 ``SsoUserinfo``；
4. 用 ``_sign_jwt`` 签发 admin JWT，返回
   ``{access_token, token_type, user}``（前端拿到后存 localStorage 并跳首页）。

JWT 契约（与 ``app/core/auth.py`` 共享）
==========================================

- payload: ``sub``（user_id 字符串） / ``name`` / ``role`` / ``type="admin"`` / ``exp`` / ``iat``；
- 算法 HS256；密钥 ``settings.SSO_JWT_SECRET``；
- 有效期 ``settings.SSO_JWT_EXPIRE_DAYS`` 天。

设计要点
========

1. **不挂 ``/api/v1`` 前缀**：SSO callback URL 是 GEOFlow 回跳的目标，
   顶层路径 ``/sso/callback`` 更直观，前端也可直接 ``window.location`` 跳转；
2. **callback 返回 JSON 而非重定向**：前端负责拿到 token 后跳首页，
   后端只做"换 code → 签 JWT"的纯 API 工作；
3. **login 端点用 307 RedirectResponse**：保留 HTTP 方法（GET→GET），
   避免某些浏览器把 POST 改成 GET 的兼容性问题；
4. **异常统一转 HTTPException**：``exchange_code`` 抛任何异常都视作
   "code 无效 / 已用 / 过期 / 网络异常"，统一返回 401（让前端跳重新登录）。
"""
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import jwt
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.core.config import settings
from app.services.sso_service import SsoService, SsoUserinfo

router = APIRouter(prefix="/sso", tags=["sso"])


def _get_sso_service() -> SsoService:
    """构造 SsoService 实例——从 settings 注入 base_url 与 userinfo_url。

    拆成函数便于未来在测试中替换（如需直接 patch 此函数而非 patch 类方法）。
    """
    return SsoService(
        geoflow_base_url=settings.SSO_GEOFLOW_BASE_URL,
        userinfo_url=settings.SSO_GEOFLOW_USERINFO_URL,  # type: ignore[arg-type]
    )


def _sign_jwt(user_id: int, name: str, role: str) -> str:
    """签发 admin JWT。

    与 ``app/core/auth.py::verify_admin_jwt`` 共享 payload schema 与密钥，
    签发 / 验证一致性由 ``tests/integration/test_sso_flow.py::
    test_sso_callback_valid_code_signs_jwt`` 端到端验证（callback 签发后
    立刻用 verify_admin_jwt 解析回校）。
    """
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "name": name,
        "role": role,
        "type": "admin",
        "exp": now + timedelta(days=settings.SSO_JWT_EXPIRE_DAYS),
        "iat": now,
    }
    return jwt.encode(payload, settings.SSO_JWT_SECRET, algorithm="HS256")


@router.get("/login")
async def sso_login(request: Request) -> RedirectResponse:
    """跳转到 GEOFlow SSO 授权页。

    GEOFlow 侧 ``SsoController::authorize`` 接收 ``redirect_uri`` query 参数，
    已登录管理员会自动签发一次性 code 并回跳到 ``redirect_uri?code=xxx``。

    Returns
    -------
    RedirectResponse
        307 重定向到 ``{SSO_GEOFLOW_BASE_URL}/sso/authorize?redirect_uri=...``。
    """
    redirect_uri = settings.SSO_REDIRECT_URI
    authorize_url = f"{settings.SSO_GEOFLOW_BASE_URL.rstrip('/')}/sso/authorize"
    # 用 urlencode 正规化 query string，避免特殊字符破坏 URL
    target = f"{authorize_url}?{urlencode({'redirect_uri': redirect_uri})}"
    return RedirectResponse(url=target, status_code=307)


@router.get("/callback")
async def sso_callback(request: Request) -> dict:
    """SSO callback：用一次性 code 换取 userinfo，签发 admin JWT。

    Parameters
    ----------
    code : str
        GEOFlow 签发的一次性授权 code（query 参数，30s 过期，单次消费）。

    Returns
    -------
    dict
        ``{"access_token": str, "token_type": "bearer", "user": {...}}``。

    Raises
    ------
    HTTPException
        - 400 ``missing_code``：query 缺 ``code`` 参数；
        - 401 ``invalid_code``：``exchange_code`` 抛任何异常
         （code 无效 / 已用 / 过期 / 网络异常）。
    """
    code = request.query_params.get("code")
    if not code:
        raise HTTPException(status_code=400, detail="missing_code")

    sso_service = _get_sso_service()
    try:
        userinfo: SsoUserinfo = await sso_service.exchange_code(code)
    except Exception:
        # 不暴露底层异常细节给前端（可能含 GEOFlow 内部错误信息）
        # 所有 exchange_code 失败都视作 "code 无效"，统一 401 让前端重新走登录流程
        raise HTTPException(status_code=401, detail="invalid_code")

    token = _sign_jwt(userinfo.user_id, userinfo.name, userinfo.role)

    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "user_id": userinfo.user_id,
            "name": userinfo.name,
            "email": userinfo.email,
            "role": userinfo.role,
        },
    }
