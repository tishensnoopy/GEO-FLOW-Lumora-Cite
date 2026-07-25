# index-monitor/app/api/sso_routes.py
"""SSO 路由：login（跳转 GEOFlow 授权页）+ callback（接收 code，签发 admin JWT）。

集成流程
========

1. 浏览器访问 ``GET /sso/login`` → 生成 ``state`` 存 Redis（5 分钟 TTL）→
   30x 重定向到 GEOFlow ``/sso/authorize?redirect_uri=...&state=...``；
2. GEOFlow 已登录管理员 → 签发一次性 code（30s 过期，GETDEL 单次消费），
   回跳到 ``SSO_REDIRECT_URI?code=xxx&state=yyy``（透传 state，即 ``GET /sso/callback``）；
3. callback 先 ``GETDEL`` 验证 state（一次性消费，防登录 CSRF），再调
   ``SsoService.exchange_code(code)`` 换取 ``SsoUserinfo``；
4. 用 ``_sign_jwt`` 签发 admin JWT，返回
   ``{access_token, token_type, user}``（前端拿到后存 localStorage 并跳首页）。

State 参数（防登录 CSRF）
========================

登录 CSRF 场景：攻击者诱导受害者浏览器完成一次攻击者发起的 SSO 登录
（受害者不知情用攻击者账号登录监测系统，可能泄露受害者后续操作给攻击者）。

- ``sso_login`` 生成 ``state = secrets.token_urlsafe(32)``，存 Redis
  ``sso:state:{state}`` → ``"1"``，TTL=300s（5 分钟，覆盖用户在 GEOFlow 登录的时间，
  比 code 的 30s 长），附加到 authorize URL；
- ``sso_callback`` 用 ``GETDEL`` 一次性消费 state：state 缺失 → 400 ``missing_state``，
  state 不在 Redis → 401 ``invalid_state``；
- state 验证在 code 验证之前（先确认会话合法性再消费 code）。

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
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import jwt
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.core.config import settings
from app.core.redis import get_redis
from app.services.sso_service import SsoService, SsoUserinfo

# SSO state 在 Redis 中的 key 前缀与 TTL。
# - TTL=300s（5 分钟）覆盖用户在 GEOFlow 登录的时间，比 GEOFlow code 的 30s 长，
#   避免用户在 GEOFlow 登录耗时过久导致 state 先过期。
SSO_STATE_KEY_PREFIX = "sso:state:"
SSO_STATE_TTL_SECONDS = 300

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
    """跳转到 GEOFlow SSO 授权页，并附带 state 防 CSRF。

    流程：
    1. 生成 ``state = secrets.token_urlsafe(32)``；
    2. 存 Redis ``sso:state:{state}`` → ``"1"``，TTL=300s（5 分钟）；
    3. 307 重定向到 ``{SSO_GEOFLOW_BASE_URL}/sso/authorize?redirect_uri=...&state=...``。

    GEOFlow 侧 ``SsoController::authorize`` 接收 ``redirect_uri`` + ``state`` query 参数，
    已登录管理员会自动签发一次性 code 并回跳到 ``redirect_uri?code=xxx&state=yyy``
    （state 透传，由 callback 端验证）。

    Returns
    -------
    RedirectResponse
        307 重定向到 ``{SSO_GEOFLOW_BASE_URL}/sso/authorize?redirect_uri=...&state=...``。
    """
    redirect_uri = settings.SSO_REDIRECT_URI
    authorize_url = f"{settings.SSO_GEOFLOW_BASE_URL.rstrip('/')}/sso/authorize"

    # 生成 state 防 CSRF（登录 CSRF：攻击者诱导受害者用攻击者 code 登录）
    state = secrets.token_urlsafe(32)
    redis_client = get_redis()
    await redis_client.setex(
        f"{SSO_STATE_KEY_PREFIX}{state}", SSO_STATE_TTL_SECONDS, "1"
    )

    # 用 urlencode 正规化 query string，避免特殊字符破坏 URL
    target = f"{authorize_url}?{urlencode({'redirect_uri': redirect_uri, 'state': state})}"
    return RedirectResponse(url=target, status_code=307)


@router.get("/callback")
async def sso_callback(request: Request) -> dict:
    """SSO callback：先验证 state（防 CSRF），再用一次性 code 换取 userinfo，签发 admin JWT。

    Parameters
    ----------
    state : str
        ``sso_login`` 生成并存 Redis 的 state（query 参数，5 分钟过期，单次消费）。
        缺失 → 400 ``missing_state``；不存在于 Redis → 401 ``invalid_state``。
    code : str
        GEOFlow 签发的一次性授权 code（query 参数，30s 过期，单次消费）。

    Returns
    -------
    dict
        ``{"access_token": str, "token_type": "bearer", "user": {...}}``。

    Raises
    ------
    HTTPException
        - 400 ``missing_state``：query 缺 ``state`` 参数；
        - 401 ``invalid_state``：state 不在 Redis（GETDEL 一次性消费，None 即无效）；
        - 400 ``missing_code``：query 缺 ``code`` 参数；
        - 401 ``invalid_code``：``exchange_code`` 抛任何异常
          （code 无效 / 已用 / 过期 / 网络异常）。

    Notes
    -----
    state 验证在 code 验证之前（先确认会话合法性再消费 code）。
    state 通过 ``GETDEL`` 一次性消费——即使后续 code 交换失败 / code 缺失，
    state 也不会回滚（避免被重复使用，符合"一次性消费"语义）。
    """
    # 1. 验证 state（防 CSRF）——先于 code 验证
    state = request.query_params.get("state")
    if not state:
        raise HTTPException(status_code=400, detail="missing_state")

    redis_client = get_redis()
    # GETDEL 一次性消费：state 用过即删，防重放
    stored = await redis_client.getdel(f"{SSO_STATE_KEY_PREFIX}{state}")
    if stored is None:
        raise HTTPException(status_code=401, detail="invalid_state")

    # 2. 验证 code
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
