"""Task 11：SSO callback + JWT 签发集成测试 + SSO CSRF state 参数测试。

验证目标
========

1. ``GET /sso/login`` 重定向到 GEOFlow ``/sso/authorize``，Location 头包含
   ``redirect_uri`` 与 ``state``，state 同时存入 Redis（``sso:state:{state}``）；
2. ``GET /sso/callback?code=...&state=...`` 先验证 state（GETDEL 一次性消费），
   再用有效 code 调 ``SsoService.exchange_code`` 换取 ``SsoUserinfo``，签发 admin JWT，
   返回 ``{access_token, token_type, user}``；
3. ``GET /sso/callback`` 缺少 ``state`` → 400 ``missing_state``；
4. ``GET /sso/callback?state=...`` state 不在 Redis → 401 ``invalid_state``；
5. ``GET /sso/callback?state=valid&...`` 缺 ``code`` → 400 ``missing_code``；
6. ``GET /sso/callback?state=valid&code=invalid`` ``exchange_code`` 抛异常 → 401 ``invalid_code``。

State 验证顺序
==============

state 验证在 code 验证之前（先确认会话合法性再消费 code）：
state 缺失 / 无效 → 直接 4xx，不调用 ``exchange_code``；
state 有效则一次性 GETDEL 消费，即便后续 code 交换失败 state 也不会回滚
（避免被重复使用，符合"一次性消费"语义）。

Mock 策略
========

- ``SsoService.exchange_code`` 用 ``unittest.mock.patch`` 替换，不真实调用
  GEOFlow API（避免外部依赖 + 一次性 code 不可复现问题）；
- Redis 用 ``FakeRedis``（本文件内的最小 async fake，dict 模拟 setex/getdel）
  通过 ``monkeypatch.setattr("app.api.sso_routes.get_redis", ...)`` 注入，
  避免引入 fakeredis 依赖（保持测试依赖最小）；
- ``client`` fixture 见 ``conftest.py``，用 ``httpx.AsyncClient + ASGITransport``
  直连 FastAPI ASGI 应用，且不调用 lifespan（不触发调度器 / 真实 Redis 连接）。

JWT 一致性
==========

本测试与 ``tests/unit/test_admin_auth.py`` 共享 JWT 契约：
- payload: ``sub`` / ``name`` / ``role`` / ``type="admin"`` / ``exp`` / ``iat``；
- 算法 HS256；密钥 ``settings.SSO_JWT_SECRET``。
callback 签发的 token 应能被 ``verify_admin_jwt`` 解析（一致性已由
``test_admin_auth.py`` 中 ``test_verify_admin_jwt_valid_token`` 间接覆盖）。
"""
import pytest
from urllib.parse import urlparse, parse_qs
from unittest.mock import patch

from app.services.sso_service import SsoUserinfo


class FakeRedis:
    """最小化的异步 Redis fake，用 dict 模拟 setex / getdel / close。

    不依赖 fakeredis，保持测试依赖最小。仅覆盖 SSO state 流程用到的方法。
    """

    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    async def setex(self, key: str, ttl: int, value: str) -> None:
        self.data[key] = value

    async def getdel(self, key: str) -> str | None:
        return self.data.pop(key, None)

    async def close(self) -> None:
        pass


@pytest.fixture
def fake_redis(monkeypatch):
    """注入 FakeRedis 到 sso_routes.get_redis，返回 fake 实例供测试预填 / 断言。"""
    fake = FakeRedis()
    # sso_routes.py 内 from app.core.redis import get_redis，patch 目标是 sso_routes 模块上的引用
    monkeypatch.setattr("app.api.sso_routes.get_redis", lambda: fake)
    return fake


@pytest.mark.asyncio
async def test_sso_callback_valid_code_signs_jwt(client, db_session, fake_redis):
    """验证 SSO callback 用有效 code + 有效 state 签发 JWT，并一次性消费 state。

    设计变更（2026-07-26）：callback 现返回 HTML 页面（浏览器执行 JS 存 token
    并跳转首页），不再返回 JSON。测试改为从 HTML 中提取 token 并验证。
    """
    import re

    fake_redis.data["sso:state:valid-state"] = "1"
    mock_userinfo = SsoUserinfo(
        user_id=1, name="测试管理员", email="admin@test.com", role="super_admin"
    )

    with patch(
        "app.services.sso_service.SsoService.exchange_code",
        return_value=mock_userinfo,
    ):
        response = await client.get("/sso/callback?code=valid-code&state=valid-state")

    assert response.status_code == 200, f"期望 200，实际 {response.status_code}: {response.text}"

    # callback 现返回 HTML（浏览器执行 JS 把 token 存 localStorage 并跳转首页）
    text = response.text
    assert "localStorage.setItem" in text, f"HTML 应包含 JS 赋值，实际: {text[:200]}"
    assert "window.location.href" in text, f"HTML 应包含跳转，实际: {text[:200]}"

    # 从 HTML 中提取 token（json.dumps 生成双引号字符串）
    token_match = re.search(
        r"localStorage\.setItem\('token',\s*\"([^\"]+)\"\)", text
    )
    assert token_match, f"HTML 应包含 token 赋值，实际: {text[:300]}"
    access_token = token_match.group(1)

    # 验证 role 映射：后端 super_admin → 前端 admin
    role_match = re.search(
        r"localStorage\.setItem\('role',\s*\"([^\"]+)\"\)", text
    )
    assert role_match, f"HTML 应包含 role 赋值，实际: {text[:300]}"
    assert role_match.group(1) == "admin", (
        f"role 应映射为 admin（前端 App.vue 检查 role === 'admin'），实际: {role_match.group(1)}"
    )

    # 验证 user_name
    name_match = re.search(
        r"localStorage\.setItem\('user_name',\s*\"([^\"]+)\"\)", text
    )
    assert name_match, f"HTML 应包含 user_name 赋值，实际: {text[:300]}"
    assert name_match.group(1) == "测试管理员"

    # state 应被一次性消费（GETDEL 后从 Redis 删除）
    assert "sso:state:valid-state" not in fake_redis.data, "state 应被一次性消费"

    # 签发的 token 必须能被 verify_admin_jwt 解析（签发 / 验证一致性）
    import jwt
    from app.core.config import settings
    from app.core.auth import verify_admin_jwt

    decoded = verify_admin_jwt(access_token)
    assert decoded["user_id"] == 1
    assert decoded["name"] == "测试管理员"
    # JWT 内的 role 保持后端原值（super_admin），前端 role 映射只影响 localStorage
    assert decoded["role"] == "super_admin"

    # 同时直接 jwt.decode 校验 type 字段（避免 verify_admin_jwt 隐藏字段缺失）
    raw = jwt.decode(access_token, settings.SSO_JWT_SECRET, algorithms=["HS256"])
    assert raw["type"] == "admin"


@pytest.mark.asyncio
async def test_sso_callback_invalid_code_returns_401(client, fake_redis):
    """验证无效 code 返回 HTML 错误页（state 有效先被消费，再 code 交换失败）。

    设计变更：SSO callback 按产品要求返回 HTML 错误页（含"重新登录"按钮），
    而非 raw JSON 401。测试断言需适配 HTML 响应（200 + 错误码在 HTML body 中）。
    """
    fake_redis.data["sso:state:valid-state"] = "1"
    with patch(
        "app.services.sso_service.SsoService.exchange_code",
        side_effect=Exception("invalid"),
    ):
        response = await client.get("/sso/callback?code=invalid-code&state=valid-state")

    assert response.status_code == 200, f"期望 200 HTML，实际 {response.status_code}: {response.text}"
    assert "invalid_code" in response.text, f"HTML 应含错误码 invalid_code: {response.text}"
    assert "重新登录" in response.text, f"HTML 应含重新登录按钮: {response.text}"
    # state 已被一次性消费（即使 code 交换失败也不回滚）
    assert "sso:state:valid-state" not in fake_redis.data


@pytest.mark.asyncio
async def test_sso_callback_missing_code_returns_400(client, fake_redis):
    """验证缺少 code 参数返回 HTML 错误页 missing_code（state 有效，进入 code 验证后报错）。"""
    fake_redis.data["sso:state:valid-state"] = "1"
    response = await client.get("/sso/callback?state=valid-state")

    assert response.status_code == 200, f"期望 200 HTML，实际 {response.status_code}: {response.text}"
    assert "missing_code" in response.text, f"HTML 应含错误码 missing_code: {response.text}"
    # state 仍被消费（验证通过即消费，不论后续是否因 code 缺失报错）
    assert "sso:state:valid-state" not in fake_redis.data


@pytest.mark.asyncio
async def test_sso_callback_missing_state_returns_400(client):
    """验证 callback 缺少 state 参数返回 HTML 错误页 missing_state（先于 code 检查）。"""
    # 注意：不注入 fake_redis——state 缺失应在调用 get_redis 之前就报错
    response = await client.get("/sso/callback?code=valid-code")

    assert response.status_code == 200, f"期望 200 HTML，实际 {response.status_code}: {response.text}"
    assert "missing_state" in response.text, f"HTML 应含错误码 missing_state: {response.text}"


@pytest.mark.asyncio
async def test_sso_callback_invalid_state_returns_401(client, fake_redis):
    """验证 callback state 不在 Redis 返回 HTML 错误页 invalid_state。"""
    # fake_redis 默认空，state 不存在
    response = await client.get("/sso/callback?code=valid-code&state=invalid-state")

    assert response.status_code == 200, f"期望 200 HTML，实际 {response.status_code}: {response.text}"
    assert "invalid_state" in response.text, f"HTML 应含错误码 invalid_state: {response.text}"


@pytest.mark.asyncio
async def test_sso_login_redirects_to_geoflow(client, fake_redis):
    """验证 /sso/login 重定向到 GEOFlow 授权页，并生成 state 存 Redis。"""
    response = await client.get("/sso/login", follow_redirects=False)

    assert response.status_code in (301, 302, 307), (
        f"期望 30x 重定向，实际 {response.status_code}: {response.text}"
    )
    location = response.headers.get("location", "")
    assert "sso/authorize" in location, f"Location 应包含 sso/authorize，实际: {location!r}"
    assert "redirect_uri" in location, f"Location 应包含 redirect_uri，实际: {location!r}"
    assert "state=" in location, f"Location 应包含 state，实际: {location!r}"

    # 验证 state 存在 Redis 中（key 形如 sso:state:{state}）
    qs = parse_qs(urlparse(location).query)
    assert "state" in qs, f"Location query 应有 state 参数，实际: {location!r}"
    state = qs["state"][0]
    assert len(state) >= 16, f"state 应有足够长度（>=16），实际: {state!r}"
    redis_key = f"sso:state:{state}"
    assert redis_key in fake_redis.data, (
        f"state 应存入 Redis（key={redis_key}），实际 Redis 内容: {fake_redis.data}"
    )
    assert fake_redis.data[redis_key] == "1"
