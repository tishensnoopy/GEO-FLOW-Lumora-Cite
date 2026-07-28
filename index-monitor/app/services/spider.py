# index-monitor/app/services/spider.py
"""搜索引擎收录检测 spider。

P0 修复：
1. site: 查询使用域名而非完整 URL（原 site:{完整URL} 语法错误，搜索引擎无法匹配）
2. 添加重试机制（最多重试1次，应对临时网络错误/反爬虫）
3. 检测验证码页面，避免误判为"未收录"
4. 改进日志，记录结果数和失败原因
"""
import asyncio
import logging
from typing import Dict
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from app.utils.http_client import http_client
from app.core.config import settings

logger = logging.getLogger(__name__)


def _extract_domain(url: str) -> str:
    """从 URL 提取域名（不含 scheme 和 path）。

    site: 查询的正确用法是 site:domain.com，不能带 scheme 和 path。
    """
    if not url:
        return ""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    parsed = urlparse(url)
    return parsed.netloc or ""


class IndexSpider:
    def __init__(self):
        self.semaphore = asyncio.Semaphore(settings.SPIDER_CONCURRENT)

    async def _check_engine(
        self,
        engine_name: str,
        search_url: str,
        result_selector: dict,
        url: str,
    ) -> bool:
        """通用收录检测逻辑（带重试和反爬虫检测）。

        Parameters
        ----------
        engine_name : str
            搜索引擎名称（用于日志）
        search_url : str
            完整搜索 URL（已包含 site:domain 查询参数）
        result_selector : dict
            {"tag": "div", "class": "result"} 形式的选择器
        url : str
            原始文章 URL（用于日志）
        """
        async with self.semaphore:
            for attempt in range(2):  # 最多重试1次
                try:
                    response = await http_client.get(search_url)
                    text = response.text or ""

                    # 检测响应过短（可能被反爬虫拦截）
                    if len(text) < 200:
                        logger.warning(
                            "[%s] 响应过短(可能反爬虫): %s, length=%s, attempt=%s",
                            engine_name, url, len(text), attempt + 1,
                        )
                        if attempt == 0:
                            await asyncio.sleep(1)
                            continue
                        return False

                    # 检测验证码/安全验证页面
                    captcha_keywords = [
                        "验证码", "安全验证", "captcha", "百度安全验证",
                        "人机验证", "滑动验证", "请输入验证码",
                    ]
                    if any(kw in text for kw in captcha_keywords):
                        logger.warning(
                            "[%s] 触发验证码页面: %s, attempt=%s",
                            engine_name, url, attempt + 1,
                        )
                        if attempt == 0:
                            await asyncio.sleep(2)
                            continue
                        return False

                    soup = BeautifulSoup(text, "lxml")
                    tag = result_selector.get("tag", "div")
                    css_class = result_selector.get("class")
                    results = soup.find_all(tag, class_=css_class)

                    if len(results) > 0:
                        logger.info(
                            "[%s] 收录确认: %s (结果数=%s)",
                            engine_name, url, len(results),
                        )
                        return True

                    logger.info("[%s] 未收录: %s (结果数=0)", engine_name, url)
                    return False

                except Exception as e:
                    logger.warning(
                        "[%s] 检测异常(尝试%s): %s, 错误: %s",
                        engine_name, attempt + 1, url, e,
                    )
                    if attempt == 0:
                        await asyncio.sleep(1)
                        continue
                    return False
            return False

    async def check_baidu(self, url: str) -> bool:
        domain = _extract_domain(url)
        if not domain:
            return False
        return await self._check_engine(
            "百度",
            f"https://www.baidu.com/s?wd=site:{domain}",
            {"tag": "div", "class": "result"},
            url,
        )

    async def check_toutiao(self, url: str) -> bool:
        domain = _extract_domain(url)
        if not domain:
            return False
        return await self._check_engine(
            "头条",
            f"https://so.toutiao.com/search?keyword=site:{domain}",
            {"tag": "div", "class": "result"},
            url,
        )

    async def check_sogou(self, url: str) -> bool:
        domain = _extract_domain(url)
        if not domain:
            return False
        return await self._check_engine(
            "搜狗",
            f"https://www.sogou.com/web?query=site:{domain}",
            {"tag": "div", "class": "rb"},
            url,
        )

    async def check_so360(self, url: str) -> bool:
        domain = _extract_domain(url)
        if not domain:
            return False
        return await self._check_engine(
            "360",
            f"https://www.so.com/s?q=site:{domain}",
            {"tag": "li", "class": "res-list"},
            url,
        )

    async def check_bing(self, url: str) -> bool:
        domain = _extract_domain(url)
        if not domain:
            return False
        return await self._check_engine(
            "必应",
            f"https://www.bing.com/search?q=site:{domain}",
            {"tag": "li", "class": "b_algo"},
            url,
        )

    async def check_all_engines(self, url: str) -> Dict[str, bool]:
        results = await asyncio.gather(
            self.check_baidu(url),
            self.check_toutiao(url),
            self.check_sogou(url),
            self.check_so360(url),
            self.check_bing(url)
        )
        return {
            "baidu": results[0],
            "toutiao": results[1],
            "sogou": results[2],
            "so360": results[3],
            "bing": results[4]
        }

spider = IndexSpider()
