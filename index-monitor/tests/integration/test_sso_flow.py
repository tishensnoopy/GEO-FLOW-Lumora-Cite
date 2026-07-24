"""Task 11：SSO callback + JWT 签发集成测试（TDD RED 阶段先写）。

验证目标
========

1. ``GET /sso/login`` 重定向到 GEOFlow ``/sso/authorize``，Location 头包含
   ``redirect_uri``；
2. ``GET /sso/callback?code=...`` 用有效 code 调 ``SsoService.exchange_code``
   换取 ``SsoUserinfo``，签发 admin JWT，返回 ``{access_token, token_type, user}``；
3. ``GET /sso/callback`` 缺少 ``code`` 参数 → 400；
4. ``GET /sso/callback?code=invalid`` 当 ``exchange_code`` 抛异常 → 401。

Mock 策略
========

- ``SsoService.exchange_code`` 用 ``unittest.mock.patch`` 替换，不真实调用
  GEOFlow API（避免外部依赖 + 一次性 code 不可复现问题）；
- ``client`` fixture 见 ``conftest.py``，用 ``httpx.AsyncClient + ASGITransport``
  直连 FastAPI ASGI 应用。

JWT 一致性
==========

本测试与 ``tests/unit/test_admin_auth.py`` 共享 JWT 契约：
- payload: ``sub`` / ``name`` / ``role`` / ``type="admin"`` / ``exp`` / ``iat``；
- 算法 HS256；密钥 ``settings.SSO_JWT_SECRET``。
callback 签发的 token 应能被 ``verify_admin_jwt`` 解析（一致性已由
``test_admin_auth.py`` 中 ``test_verify_admin_jwt_valid_token`` 间接覆盖）。
"""
import pytest
from unittest.mock import patch

from app.services.sso_service import SsoUserinfo


@pytest.mark.asyncio
async def test_sso_callback_valid_code_signs_jwt(client, db_session):
    """验证 SSO callback 用有效 code 签发 JWT。"""
    mock_userinfo = SsoUserinfo(
        user_id=1, name="测试管理员", email="admin@test.com", role="super_admin"
    )

    with patch(
        "app.services.sso_service.SsoService.exchange_code",
        return_value=mock_userinfo,
    ):
        response = await client.get("/sso/callback?code=valid-code")

    assert response.status_code == 200, f"期望 200，实际 {response.status_code}: {response.text}"
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["user"]["name"] == "测试管理员"
    assert data["user"]["role"] == "super_admin"
    assert data["user"]["user_id"] == 1
    assert data["user"]["email"] == "admin@test.com"

    # 签发的 token 必须能被 verify_admin_jwt 解析（签发 / 验证一致性）
    import jwt
    from app.core.config import settings
    from app.core.auth import verify_admin_jwt

    decoded = verify_admin_jwt(data["access_token"])
    assert decoded["user_id"] == 1
    assert decoded["name"] == "测试管理员"
    assert decoded["role"] == "super_admin"

    # 同时直接 jwt.decode 校验 type 字段（避免 verify_admin_jwt 隐藏字段缺失）
    raw = jwt.decode(data["access_token"], settings.SSO_JWT_SECRET, algorithms=["HS256"])
    assert raw["type"] == "admin"


@pytest.mark.asyncio
async def test_sso_callback_invalid_code_returns_401(client):
    """验证无效 code 返回 401。"""
    with patch(
        "app.services.sso_service.SsoService.exchange_code",
        side_effect=Exception("invalid"),
    ):
        response = await client.get("/sso/callback?code=invalid-code")

    assert response.status_code == 401, f"期望 401，实际 {response.status_code}: {response.text}"


@pytest.mark.asyncio
async def test_sso_callback_missing_code_returns_400(client):
    """验证缺少 code 参数返回 400。"""
    response = await client.get("/sso/callback")

    assert response.status_code == 400, f"期望 400，实际 {response.status_code}: {response.text}"


@pytest.mark.asyncio
async def test_sso_login_redirects_to_geoflow(client):
    """验证 /sso/login 重定向到 GEOFlow 授权页。"""
    response = await client.get("/sso/login", follow_redirects=False)

    assert response.status_code in (301, 302, 307), (
        f"期望 30x 重定向，实际 {response.status_code}: {response.text}"
    )
    location = response.headers.get("location", "")
    assert "sso/authorize" in location, f"Location 应包含 sso/authorize，实际: {location!r}"
    assert "redirect_uri" in location, f"Location 应包含 redirect_uri，实际: {location!r}"
