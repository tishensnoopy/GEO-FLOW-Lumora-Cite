# index-monitor/app/services/spider.py
import asyncio
import logging
from typing import Dict
from bs4 import BeautifulSoup
from app.utils.http_client import http_client
from app.core.config import settings

logger = logging.getLogger(__name__)

class IndexSpider:
    def __init__(self):
        self.semaphore = asyncio.Semaphore(settings.SPIDER_CONCURRENT)

    async def check_baidu(self, url: str) -> bool:
        async with self.semaphore:
            try:
                response = await http_client.get(f"https://www.baidu.com/s?wd=site:{url}")
                soup = BeautifulSoup(response.text, 'lxml')
                return len(soup.find_all('div', class_='result')) > 0
            except Exception as e:
                logger.warning("百度检测失败: %s, 错误: %s", url, e)
                return False

    async def check_toutiao(self, url: str) -> bool:
        async with self.semaphore:
            try:
                response = await http_client.get(f"https://so.toutiao.com/search?keyword=site:{url}")
                soup = BeautifulSoup(response.text, 'lxml')
                return len(soup.find_all('div', class_='result')) > 0
            except Exception as e:
                logger.warning("头条检测失败: %s, 错误: %s", url, e)
                return False

    async def check_sogou(self, url: str) -> bool:
        async with self.semaphore:
            try:
                response = await http_client.get(f"https://www.sogou.com/web?query=site:{url}")
                soup = BeautifulSoup(response.text, 'lxml')
                return len(soup.find_all('div', class_='rb')) > 0
            except Exception as e:
                logger.warning("搜狗检测失败: %s, 错误: %s", url, e)
                return False

    async def check_so360(self, url: str) -> bool:
        async with self.semaphore:
            try:
                response = await http_client.get(f"https://www.so.com/s?q=site:{url}")
                soup = BeautifulSoup(response.text, 'lxml')
                return len(soup.find_all('li', class_='res-list')) > 0
            except Exception as e:
                logger.warning("360检测失败: %s, 错误: %s", url, e)
                return False

    async def check_bing(self, url: str) -> bool:
        async with self.semaphore:
            try:
                response = await http_client.get(f"https://www.bing.com/search?q=site:{url}")
                soup = BeautifulSoup(response.text, 'lxml')
                return len(soup.find_all('li', class_='b_algo')) > 0
            except Exception as e:
                logger.warning("必应检测失败: %s, 错误: %s", url, e)
                return False

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
