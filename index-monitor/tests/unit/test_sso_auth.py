"""Task 10：监测系统 SSO 服务测试（TDD RED 阶段先写）。

验证目标：
1. SsoService.exchange_code(code) 调用 GEOFlow /api/sso/userinfo 换取用户信息；
2. 成功响应 → 返回 SsoUserinfo(user_id, name, email, role)；
3. 无效 code（HTTP 4xx）→ 抛 httpx.HTTPStatusError；
4. 网络异常 → 抛 httpx.RequestError；
5. code 作为 query 参数 ``code`` 传给 GEOFlow userinfo 端点；
6. GEOFlow 未返回 role 时默认 'admin'（与 GEOFlow SsoController 约定一致）；
7. （任务 4 审查建议）Settings 中 SSO_GEOFLOW_USERINFO_URL 应从 SSO_GEOFLOW_BASE_URL
   派生，避免硬编码 URL 不一致。

Mock 策略
=========
用真实 ``httpx.Response`` 对象作为 mock 返回值——比 ``AsyncMock`` 模拟属性更准确，
因为真实 ``httpx.Response.json()`` 和 ``raise_for_status()`` 都是同步方法，
AsyncMock 会让它们返回 coroutine，与真实行为不符。
"""
import pytest
from unittest.mock import AsyncMock, patch

import httpx

from app.services.sso_service import SsoService, SsoUserinfo


@pytest.mark.asyncio
async def test_exchange_code_for_userinfo_success():
    """验证 code 换取 userinfo 成功。"""
    service = SsoService(
        geoflow_base_url="https://geoflow.test",
        userinfo_url="https://geoflow.test/api/sso/userinfo",
    )
    # 真实 httpx.Response——json() / raise_for_status() 行为与生产一致。
    # 必须传 request 参数，否则 raise_for_status() 会因 _request 为 None 抛 RuntimeError。
    mock_response = httpx.Response(
        200,
        json={
            "user_id": 1,
            "name": "测试管理员",
            "email": "admin@test.com",
            "role": "super_admin",
        },
        request=httpx.Request("GET", "https://geoflow.test/api/sso/userinfo"),
    )

    with patch("httpx.AsyncClient.get", return_value=mock_response):
        userinfo = await service.exchange_code("valid-code")

    assert isinstance(userinfo, SsoUserinfo)
    assert userinfo.user_id == 1
    assert userinfo.name == "测试管理员"
    assert userinfo.email == "admin@test.com"
    assert userinfo.role == "super_admin"


@pytest.mark.asyncio
async def test_exchange_code_invalid_raises_error():
    """验证无效 code（HTTP 400）抛 httpx.HTTPStatusError。"""
    service = SsoService(
        geoflow_base_url="https://geoflow.test",
        userinfo_url="https://geoflow.test/api/sso/userinfo",
    )
    mock_response = httpx.Response(
        400,
        json={"error": "invalid_code"},
        request=httpx.Request("GET", "https://geoflow.test/api/sso/userinfo"),
    )

    with patch("httpx.AsyncClient.get", return_value=mock_response):
        with pytest.raises(httpx.HTTPStatusError):
            await service.exchange_code("invalid-code")


@pytest.mark.asyncio
async def test_exchange_code_network_error_raises():
    """验证网络异常（httpx.RequestError）向上抛出。"""
    service = SsoService(
        geoflow_base_url="https://geoflow.test",
        userinfo_url="https://geoflow.test/api/sso/userinfo",
    )

    with patch("httpx.AsyncClient.get", side_effect=httpx.ConnectError("connection refused")):
        with pytest.raises(httpx.RequestError):
            await service.exchange_code("any-code")


@pytest.mark.asyncio
async def test_exchange_code_passes_code_as_query_param():
    """验证 code 作为 query 参数 code 传给 GEOFlow userinfo 端点。"""
    service = SsoService(
        geoflow_base_url="https://geoflow.test",
        userinfo_url="https://geoflow.test/api/sso/userinfo",
    )
    mock_response = httpx.Response(
        200,
        json={
            "user_id": 7,
            "name": "Alice",
            "email": "alice@geoflow.test",
            "role": "admin",
        },
        request=httpx.Request("GET", "https://geoflow.test/api/sso/userinfo"),
    )

    with patch("httpx.AsyncClient.get", return_value=mock_response) as mock_get:
        await service.exchange_code("the-code")

    mock_get.assert_awaited_once()
    # AsyncClient.get(url, params=...) 调用参数
    call_args = mock_get.call_args
    # 关键字参数应包含 params={"code": "the-code"}
    assert call_args.kwargs.get("params") == {"code": "the-code"}, (
        f"期望 params={{'code': 'the-code'}}，实际 {call_args.kwargs.get('params')!r}"
    )


@pytest.mark.asyncio
async def test_exchange_code_defaults_role_to_admin_when_missing():
    """验证 GEOFlow 未返回 role 时默认为 'admin'（与 GEOFlow SsoController 约定一致）。"""
    service = SsoService(
        geoflow_base_url="https://geoflow.test",
        userinfo_url="https://geoflow.test/api/sso/userinfo",
    )
    mock_response = httpx.Response(
        200,
        json={
            "user_id": 2,
            "name": "无角色用户",
            "email": "norole@test.com",
            # 故意不返回 role
        },
        request=httpx.Request("GET", "https://geoflow.test/api/sso/userinfo"),
    )

    with patch("httpx.AsyncClient.get", return_value=mock_response):
        userinfo = await service.exchange_code("some-code")

    assert userinfo.role == "admin"


# --------------------------------------------------------------------------- #
# 任务 4 审查建议：SSO_GEOFLOW_USERINFO_URL 应从 SSO_GEOFLOW_BASE_URL 派生       #
# --------------------------------------------------------------------------- #
def test_settings_userinfo_url_derived_from_base_url():
    """验证 Settings.SSO_GEOFLOW_USERINFO_URL 从 SSO_GEOFLOW_BASE_URL 派生，
    避免硬编码两处 URL 不一致。

    实现方式：Pydantic model_validator（mode='after'）。
    验证点：base_url 改变时 userinfo_url 自动跟随。
    """
    from pydantic import TypeAdapter
    from app.core.config import Settings

    adapter = TypeAdapter(Settings)
    custom = adapter.validate_python(
        {"SSO_GEOFLOW_BASE_URL": "https://custom.geoflow.test"}
    )
    assert custom.SSO_GEOFLOW_USERINFO_URL == "https://custom.geoflow.test/api/sso/userinfo", (
        f"USERINFO_URL 应从 BASE_URL 派生，实际：{custom.SSO_GEOFLOW_USERINFO_URL!r}"
    )

    # 默认配置也应正确派生
    default_settings = Settings()
    assert default_settings.SSO_GEOFLOW_USERINFO_URL == (
        f"{default_settings.SSO_GEOFLOW_BASE_URL}/api/sso/userinfo"
    ), (
        f"默认 USERINFO_URL 应从默认 BASE_URL 派生，实际："
        f"{default_settings.SSO_GEOFLOW_USERINFO_URL!r}"
    )


def test_settings_userinfo_url_env_override_still_derived():
    """验证 env 注入 SSO_GEOFLOW_BASE_URL 时 USERINFO_URL 仍正确派生。"""
    from pydantic import TypeAdapter
    from app.core.config import Settings

    custom_base = "https://env-override.geoflow.test"
    adapter = TypeAdapter(Settings)
    custom = adapter.validate_python(
        {"SSO_GEOFLOW_BASE_URL": custom_base}
    )
    assert custom.SSO_GEOFLOW_USERINFO_URL == f"{custom_base}/api/sso/userinfo"


def test_settings_userinfo_url_explicit_override_respected():
    """验证显式注入 SSO_GEOFLOW_USERINFO_URL 时优先使用注入值（向后兼容内网代理场景）。"""
    from pydantic import TypeAdapter
    from app.core.config import Settings

    adapter = TypeAdapter(Settings)
    custom = adapter.validate_python({
        "SSO_GEOFLOW_BASE_URL": "https://default.geoflow.test",
        "SSO_GEOFLOW_USERINFO_URL": "https://internal-proxy.test/sso/userinfo",
    })
    assert custom.SSO_GEOFLOW_USERINFO_URL == "https://internal-proxy.test/sso/userinfo"
