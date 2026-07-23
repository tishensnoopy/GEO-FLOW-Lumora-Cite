# index-monitor/app/services/spider.py
import asyncio
from typing import Dict
from bs4 import BeautifulSoup
from app.utils.http_client import http_client
from app.core.config import settings

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
                print(f"百度检测失败: {url}, 错误: {e}")
                return False

    async def check_toutiao(self, url: str) -> bool:
        async with self.semaphore:
            try:
                response = await http_client.get(f"https://so.toutiao.com/search?keyword=site:{url}")
                soup = BeautifulSoup(response.text, 'lxml')
                return len(soup.find_all('div', class_='result')) > 0
            except Exception as e:
                print(f"头条检测失败: {url}, 错误: {e}")
                return False

    async def check_sogou(self, url: str) -> bool:
        async with self.semaphore:
            try:
                response = await http_client.get(f"https://www.sogou.com/web?query=site:{url}")
                soup = BeautifulSoup(response.text, 'lxml')
                return len(soup.find_all('div', class_='rb')) > 0
            except Exception as e:
                print(f"搜狗检测失败: {url}, 错误: {e}")
                return False

    async def check_so360(self, url: str) -> bool:
        async with self.semaphore:
            try:
                response = await http_client.get(f"https://www.so.com/s?q=site:{url}")
                soup = BeautifulSoup(response.text, 'lxml')
                return len(soup.find_all('li', class_='res-list')) > 0
            except Exception as e:
                print(f"360检测失败: {url}, 错误: {e}")
                return False

    async def check_bing(self, url: str) -> bool:
        async with self.semaphore:
            try:
                response = await http_client.get(f"https://www.bing.com/search?q=site:{url}")
                soup = BeautifulSoup(response.text, 'lxml')
                return len(soup.find_all('li', class_='b_algo')) > 0
            except Exception as e:
                print(f"必应检测失败: {url}, 错误: {e}")
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
