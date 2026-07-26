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
import json
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import jwt
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

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


def _map_frontend_role(backend_role: str) -> str:
    """后端 role → 前端 role 映射。

    前端 ``App.vue`` 用 ``localStorage.getItem('role') === 'admin'`` 判断管理员，
    而后端 ``SsoUserinfo.role`` 可能是 ``super_admin`` / ``admin``。
    统一映射为 ``admin`` 以匹配前端逻辑；其他角色透传。
    """
    if backend_role in ("super_admin", "admin"):
        return "admin"
    return backend_role


def _json_js(value: str) -> str:
    """将 Python 字符串转为 JS 安全的字符串字面量。

    - ``ensure_ascii=False``：保留中文可读性（浏览器原生支持 UTF-8）；
    - 替换 ``</`` → ``<\\/``：防止 ``</script>`` XSS 注入
      （``json.dumps`` 不转义 ``/``，需手动处理）。
    """
    return json.dumps(value, ensure_ascii=False).replace("</", "<\\/")


# SSO 响应一律不缓存：callback URL 每次携带不同的 code/state，
# 浏览器若缓存旧响应会导致跳转异常（如"网址无法显示/重定向"）。
SSO_NO_CACHE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}


def _render_sso_success_html(
    token: str, frontend_role: str, userinfo: SsoUserinfo
) -> HTMLResponse:
    """渲染 SSO 登录成功的 HTML 页面。

    浏览器执行内嵌 JS 把 token / role 存入 localStorage 并跳转首页。

    设计原因：SSO callback 由浏览器直接访问（GEOFlow 302 回跳到
    ``/sso/callback?code=...&state=...``），后端无法用前端路由处理，
    因此返回 HTML 让浏览器自动存储 token 并跳转，而不是返回 JSON
    让浏览器显示原始 JSON。

    安全考虑：所有动态值通过 ``_json_js`` 转义后嵌入 JS 字符串字面量，
    避免 XSS 注入（``</script>`` 替换 + 引号转义）。

    缓存控制：附加 ``Cache-Control: no-store`` 等头，防止浏览器缓存
    含 token 的成功页或旧的错误响应，避免 SSO 跳转异常。
    """
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>登录成功</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", sans-serif;
           text-align: center; padding: 80px 20px; background: #f0f2f5; color: #333; margin: 0; }}
    .card {{ max-width: 400px; margin: 0 auto; background: #fff; padding: 40px;
            border-radius: 8px; box-shadow: 0 2px 12px rgba(0,0,0,0.1); }}
    .icon {{ font-size: 48px; color: #67c23a; margin-bottom: 16px; }}
    .title {{ font-size: 20px; margin-bottom: 8px; }}
    .desc {{ color: #666; font-size: 14px; margin-bottom: 20px; }}
    .spinner {{ display: inline-block; width: 24px; height: 24px;
               border: 3px solid #e0e0e0; border-top-color: #409eff;
               border-radius: 50%; animation: spin 0.8s linear infinite; }}
    @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
  </style>
</head>
<body>
  <div class="card">
    <div class="icon">&#10003;</div>
    <div class="title">登录成功</div>
    <div class="desc">正在跳转到控制台...</div>
    <div class="spinner"></div>
  </div>
  <script>
    localStorage.setItem('token', {_json_js(token)});
    localStorage.setItem('role', {_json_js(frontend_role)});
    localStorage.setItem('user_name', {_json_js(userinfo.name)});
    window.location.href = '/';
  </script>
</body>
</html>"""
    return HTMLResponse(content=html, headers=SSO_NO_CACHE_HEADERS)


def _render_sso_error_html(error_code: str, message: str) -> HTMLResponse:
    """渲染 SSO 错误页面（HTML 而非 JSON，避免浏览器显示原始 JSON）。

    设计原因：SSO callback 由浏览器直接访问，HTTPException 默认返回 JSON，
    浏览器会显示原始 JSON 字符串而非友好错误页。改为返回 HTML 错误页，
    提供"重新登录"按钮让用户可以重试。
    """
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>登录失败</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", sans-serif;
           text-align: center; padding: 80px 20px; background: #f0f2f5; color: #333; margin: 0; }}
    .card {{ max-width: 400px; margin: 0 auto; background: #fff; padding: 40px;
            border-radius: 8px; box-shadow: 0 2px 12px rgba(0,0,0,0.1); }}
    .icon {{ font-size: 48px; color: #f56c6c; margin-bottom: 16px; }}
    .title {{ font-size: 20px; margin-bottom: 8px; color: #f56c6c; }}
    .desc {{ color: #666; font-size: 14px; margin-bottom: 24px; line-height: 1.6; }}
    .btn {{ display: inline-block; padding: 10px 28px; background: #409eff;
           color: #fff; text-decoration: none; border-radius: 4px; font-size: 14px; }}
    .btn:hover {{ background: #66b1ff; }}
    .error-code {{ color: #999; font-size: 12px; margin-top: 16px; }}
  </style>
</head>
<body>
  <div class="card">
    <div class="icon">&#10007;</div>
    <div class="title">登录失败</div>
    <div class="desc">{message}</div>
    <a href="/login" class="btn">重新登录</a>
    <div class="error-code">错误码: {error_code}</div>
  </div>
</body>
</html>"""
    return HTMLResponse(content=html, status_code=200, headers=SSO_NO_CACHE_HEADERS)


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
    # 307 重定向也不缓存：浏览器若缓存旧 307 会导致跳转到过期的 state（已 GETDEL 消费）
    # 形成"无效 state"循环。
    return RedirectResponse(
        url=target, status_code=307, headers=SSO_NO_CACHE_HEADERS
    )


@router.get("/callback")
async def sso_callback(request: Request) -> HTMLResponse:
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
    HTMLResponse
        成功时返回 HTML 页面（浏览器执行 JS 把 token 存 localStorage 并跳转首页）。
        错误时抛 ``HTTPException``（JSON 响应，前端可识别错误码）。

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

    设计变更（2026-07-26）：
    - callback 原返回 JSON，但 SSO callback 由浏览器直接访问（GEOFlow 302 回跳），
      浏览器会显示原始 JSON 而非跳转。改为返回 HTML 页面，内嵌 JS 把 token 存
      localStorage 并跳转首页。
    - 错误情况也改为返回 HTML 错误页（而非 JSON HTTPException），提供"重新登录"
      按钮让用户可以重试，避免浏览器显示原始 JSON 错误信息。
    """
    # 1. 验证 state（防 CSRF）——先于 code 验证
    state = request.query_params.get("state")
    if not state:
        return _render_sso_error_html("missing_state", "缺少 state 参数，可能是链接已失效。")

    redis_client = get_redis()
    # GETDEL 一次性消费：state 用过即删，防重放
    stored = await redis_client.getdel(f"{SSO_STATE_KEY_PREFIX}{state}")
    if stored is None:
        return _render_sso_error_html(
            "invalid_state",
            "登录状态已过期或已被使用，请重新登录。",
        )

    # 2. 验证 code
    code = request.query_params.get("code")
    if not code:
        return _render_sso_error_html("missing_code", "缺少授权码，可能是 GEOFlow 回跳异常。")

    sso_service = _get_sso_service()
    try:
        userinfo: SsoUserinfo = await sso_service.exchange_code(code)
    except Exception:
        # 不暴露底层异常细节给前端（可能含 GEOFlow 内部错误信息）
        # 所有 exchange_code 失败都视作 "code 无效"，返回 HTML 错误页让前端重新登录
        return _render_sso_error_html(
            "invalid_code",
            "授权码无效、已过期或已被使用，请重新登录。",
        )

    token = _sign_jwt(userinfo.user_id, userinfo.name, userinfo.role)

    # 前端 role 映射：super_admin / admin → admin（前端 App.vue 检查 role === 'admin'）
    frontend_role = _map_frontend_role(userinfo.role)

    # 返回 HTML 页面：浏览器执行 JS 把 token 存 localStorage 并跳转首页
    # （SSO callback 由浏览器直接访问，无法用前端路由处理）
    return _render_sso_success_html(token, frontend_role, userinfo)
