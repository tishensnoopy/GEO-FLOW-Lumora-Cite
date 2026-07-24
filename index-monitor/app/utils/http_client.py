# index-monitor/app/utils/http_client.py
import httpx
import random
import asyncio
from typing import Optional, Dict
from app.core.config import settings

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
]

class HttpClient:
    def __init__(self):
        self.client = httpx.AsyncClient(timeout=30.0, follow_redirects=True)

    def get_random_ua(self) -> str:
        return random.choice(USER_AGENTS)

    async def get(self, url: str, headers: Optional[Dict] = None) -> httpx.Response:
        # 不修改调用方传入的 headers dict，构建新 dict 合并
        merged = {"User-Agent": self.get_random_ua()}
        if headers:
            merged.update(headers)
        await self._random_delay()
        return await self.client.get(url, headers=merged)

    async def _random_delay(self):
        delay = random.randint(settings.SPIDER_INTERVAL_MIN, settings.SPIDER_INTERVAL_MAX)
        await asyncio.sleep(delay)

    async def close(self):
        await self.client.aclose()

http_client = HttpClient()
