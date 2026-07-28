# index-monitor/app/utils/http_client.py
"""HTTP 客户端——供 spider 收录检测使用。

性能优化（P0）：
1. 移除每次 GET 前的随机延迟（_random_delay）——原设计是想避免被搜索引擎判定为爬虫，
   但 spider.py 的 _check_engine 已有重试和验证码检测，且各引擎通过 asyncio.gather 并发，
   请求前的硬延迟会让单次收录扫描最少耗时 2-5 秒。改为请求间可选延迟（仅重试时使用）。
2. 配置连接池 limits：max_connections=20, max_keepalive_connections=10，
   避免默认 100 连接导致资源浪费。
3. timeout 从 30s 降低到 10s（搜索引擎通常 3-5s 返回，超时多半是网络问题）。
4. 保持随机 UA（反爬虫基础措施）。
"""
import httpx
import random
from typing import Optional, Dict
from app.core.config import settings

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
]

# 连接池限制：控制并发连接数，避免资源耗尽
_LIMITS = httpx.Limits(
    max_connections=20,
    max_keepalive_connections=10,
    keepalive_expiry=30.0,  # 30 秒未用则关闭 keepalive 连接
)

# 超时配置：连接 5s、读取 10s、写入 5s、连接池等待 5s
_TIMEOUT = httpx.Timeout(
    connect=5.0,
    read=10.0,
    write=5.0,
    pool=5.0,
)


class HttpClient:
    def __init__(self):
        self.client = httpx.AsyncClient(
            timeout=_TIMEOUT,
            follow_redirects=True,
            limits=_LIMITS,
        )

    def get_random_ua(self) -> str:
        return random.choice(USER_AGENTS)

    async def get(self, url: str, headers: Optional[Dict] = None) -> httpx.Response:
        """GET 请求。

        注意：已移除请求前的随机延迟（原 _random_delay）。
        如需避免被搜索引擎反爬，应在调用方（spider）的重试逻辑中添加延迟，
        而不是在每次正常请求前都等待 2-5 秒。
        """
        # 构建新 dict 合并 headers，避免修改调用方传入的 dict
        merged = {"User-Agent": self.get_random_ua()}
        if headers:
            merged.update(headers)
        return await self.client.get(url, headers=merged)

    async def get_with_delay(
        self,
        url: str,
        headers: Optional[Dict] = None,
        delay_min: int = 1,
        delay_max: int = 3,
    ) -> httpx.Response:
        """带延迟的 GET（仅用于重试场景，避免连续触发反爬）。

        正常请求用 get()，重试场景用 get_with_delay() 添加 1-3 秒延迟。
        """
        import asyncio
        delay = random.randint(delay_min, delay_max)
        await asyncio.sleep(delay)
        return await self.get(url, headers)

    async def close(self):
        await self.client.aclose()


http_client = HttpClient()
