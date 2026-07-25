"""Redis 客户端单例（异步）。

用于 SSO state 存储（防 CSRF）。监测系统已有 Redis 容器（docker-compose redis 服务），
``config.py`` 已有 ``REDIS_HOST/PORT/PASSWORD`` 配置，但此前未实际使用。

设计要点
========

1. **惰性创建**：首次调用 ``get_redis()`` 才创建客户端，避免 import 时连接；
2. **单例**：模块级 ``_redis_client`` 全局共享，避免每次请求都新建连接池；
3. **decode_responses=True**：返回 str 而非 bytes，与 ``setex("1")`` 这种值匹配；
4. **close_redis()**：``lifespan`` shutdown 阶段调用，释放连接池（参考
   ``http_client.close()`` 模式）。

测试 mock 策略
==============

测试不依赖真实 Redis（避免环境依赖），用 ``unittest.mock`` / ``monkeypatch``
替换 ``app.api.sso_routes.get_redis`` 返回 fake async client（见
``tests/integration/test_sso_flow.py::FakeRedis``）。
"""
import redis.asyncio as redis

from app.core.config import settings

_redis_client: redis.Redis | None = None


def get_redis() -> redis.Redis:
    """获取 Redis 异步客户端单例。

    首次调用时根据 ``settings.REDIS_*`` 创建客户端，后续调用直接返回同一实例。
    ``decode_responses=True`` 让所有返回值为 ``str`` 而非 ``bytes``，
    与 ``setex(key, ttl, "1")`` 这种简单标记值的用法匹配。
    """
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            password=settings.REDIS_PASSWORD,
            decode_responses=True,
        )
    return _redis_client


async def close_redis() -> None:
    """关闭 Redis 连接（lifespan shutdown 时调用）。

    重置 ``_redis_client`` 为 ``None``，下次 ``get_redis()`` 会重新创建——
    便于测试或在重启场景下重新初始化。
    """
    global _redis_client
    if _redis_client is not None:
        await _redis_client.close()
        _redis_client = None
