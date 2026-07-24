# index-monitor/app/services/sso_service.py
"""SSO 服务：调 GEOFlow API 用一次性 code 换取用户信息。

集成契约
========

GEOFlow 侧（``GEOFlow-main/app/Http/Controllers/SsoController.php``）：

1. 监测系统浏览器跳到 ``{GEOFLOW_BASE_URL}/sso/authorize?redirect_uri=...``；
2. GEOFlow 已登录管理员 → 签发一次性 code（30s 过期，GETDEL 一次性消费），
   回跳到 ``redirect_uri?code=xxx``；
3. 监测系统后端 ``SsoService.exchange_code(code)`` 调
   ``{GEOFLOW_BASE_URL}/api/sso/userinfo?code=xxx`` 换取用户信息；
4. GEOFlow 返回 ``{user_id, name, email, role}``，无效 code 返回 400。

后续 JWT 签发由监测系统的 auth 路由消费 SsoUserinfo 完成（不在本任务范围）。
"""
from dataclasses import dataclass

import httpx


@dataclass
class SsoUserinfo:
    """SSO 用户信息。

    字段契约与 GEOFlow ``SsoController::userinfo`` 返回体一致：
    - ``user_id``：GEOFlow admins.id
    - ``name`` / ``email``：管理员基础信息
    - ``role``：管理员角色（admin / super_admin；GEOFlow 默认 'admin'）
    """

    user_id: int
    name: str
    email: str
    role: str  # admin / super_admin


class SsoService:
    """调 GEOFlow ``/api/sso/userinfo`` 用 code 换取 SsoUserinfo。

    Notes
    -----
    - ``userinfo_url`` 默认应从 ``Settings.SSO_GEOFLOW_USERINFO_URL`` 传入
      （后者在 config.py 中从 ``SSO_GEOFLOW_BASE_URL`` 派生，避免硬编码两处）；
    - 用 ``httpx.AsyncClient`` 异步调用，与 FastAPI 整体 async 风格一致；
    - 不在此层做 JWT 签发——保持单一职责，JWT 在调用方（auth 路由）完成；
    - 异常处理：HTTP 4xx/5xx 由 ``raise_for_status`` 抛 ``HTTPStatusError``，
      网络异常透传 ``httpx.RequestError``；调用方可按需捕获并转 HTTPException。
    """

    def __init__(
        self,
        geoflow_base_url: str,
        userinfo_url: str,
        timeout: float = 10.0,
    ):
        """
        Parameters
        ----------
        geoflow_base_url : str
            GEOFlow 站点根 URL，例如 ``https://zkeeeai.com``。
            保留此字段供调用方扩展（如未来需要调其他 GEOFlow 端点）。
        userinfo_url : str
            GEOFlow userinfo 端点完整 URL，由 Settings 派生后传入。
        timeout : float
            HTTP 调用超时（秒）。
        """
        self.geoflow_base_url = geoflow_base_url.rstrip("/")
        self.userinfo_url = userinfo_url
        self.timeout = timeout

    async def exchange_code(self, code: str) -> SsoUserinfo:
        """用一次性 code 向 GEOFlow 换取用户信息。

        Parameters
        ----------
        code : str
            GEOFlow 签发的一次性授权 code（30s 过期，单次消费）。

        Returns
        -------
        SsoUserinfo
            含 user_id/name/email/role 的用户信息。

        Raises
        ------
        httpx.HTTPStatusError
            GEOFlow 返回 4xx/5xx（如 code 无效/已用/过期 → 400）。
        httpx.RequestError
            网络层异常（DNS、连接、超时等）。
        """
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                self.userinfo_url,
                params={"code": code},
            )
            response.raise_for_status()
            data = response.json()

        return SsoUserinfo(
            user_id=int(data["user_id"]),
            name=data["name"],
            email=data["email"],
            # GEOFlow SsoController 默认 'admin'，此处同样做防御性兜底
            role=data.get("role", "admin"),
        )
