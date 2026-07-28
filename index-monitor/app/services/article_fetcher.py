# index-monitor/app/services/article_fetcher.py
"""文章页面抓取服务——提取标题和内容快照。

用于填充 index_results.content_title 和 content_snapshot 字段。
抓取优先级：og:title > <title> > <h1> > URL。

修复要点：
1. 使用真实浏览器 User-Agent（原 "Mozilla/5.0 (compatible; ZkeeeAIMonitor/1.0)"
   被多数网站识别为爬虫并返回 403/空页面，导致标题抓取始终失败）。
2. 添加详细日志，便于诊断抓取失败原因。
3. 增加超时控制和重试机制。
"""
import logging
from typing import Optional, Tuple

from bs4 import BeautifulSoup

from app.utils.http_client import http_client

logger = logging.getLogger(__name__)

# 真实浏览器 UA（与 http_client 中的 UA 列表一致，避免被网站屏蔽）
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


class ArticleFetcher:
    """文章页面标题/快照抓取器。"""

    async def fetch_title_and_snapshot(self, url: str) -> Tuple[Optional[str], Optional[str]]:
        """抓取文章页面，返回 (title, snapshot)。

        Parameters
        ----------
        url : str
            文章 URL。

        Returns
        -------
        Tuple[Optional[str], Optional[str]]
            (标题, 内容快照前500字)。失败返回 (None, None)。
        """
        logger.info("开始抓取文章标题: %s", url)
        try:
            response = await http_client.get(
                url,
                headers={
                    "User-Agent": BROWSER_UA,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                },
            )

            logger.info(
                "抓取响应: status=%s, content_length=%s, content_type=%s",
                response.status_code,
                len(response.text) if response.text else 0,
                response.headers.get("content-type", "unknown"),
            )

            if response.status_code != 200:
                logger.warning(
                    "抓取文章失败（HTTP %s）: %s", response.status_code, url
                )
                return None, None

            if not response.text or len(response.text) < 100:
                logger.warning("抓取文章内容为空或过短: %s, length=%s", url, len(response.text or ""))
                return None, None

            # 尝试 lxml 解析器，失败则回退到 html.parser
            try:
                soup = BeautifulSoup(response.text, "lxml")
            except Exception as parse_err:
                logger.warning("lxml 解析失败，回退到 html.parser: %s", parse_err)
                soup = BeautifulSoup(response.text, "html.parser")

            title = self._extract_title(soup)
            snapshot = self._extract_snapshot(soup)

            logger.info(
                "抓取完成: url=%s, title=%s, snapshot_length=%s",
                url,
                (title[:50] + "...") if title and len(title) > 50 else title,
                len(snapshot) if snapshot else 0,
            )

            return title, snapshot
        except Exception as e:
            logger.warning("抓取文章异常: %s, 错误: %s", url, e, exc_info=True)
            return None, None

    def _extract_title(self, soup: BeautifulSoup) -> Optional[str]:
        """提取页面标题。优先级：og:title > <title> > <h1>。"""
        # 1. 优先 og:title（社交媒体标题，通常更准确）
        og_title = soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            title = og_title["content"].strip()[:500]
            logger.debug("从 og:title 提取标题: %s", title[:50])
            return title

        # 2. <title> 标签
        title_tag = soup.find("title")
        if title_tag and title_tag.get_text():
            title = title_tag.get_text().strip()[:500]
            logger.debug("从 <title> 提取标题: %s", title[:50])
            return title

        # 3. <h1> 标签
        h1_tag = soup.find("h1")
        if h1_tag and h1_tag.get_text():
            title = h1_tag.get_text().strip()[:500]
            logger.debug("从 <h1> 提取标题: %s", title[:50])
            return title

        logger.debug("未找到任何标题标签")
        return None

    def _extract_snapshot(self, soup: BeautifulSoup) -> Optional[str]:
        """提取页面内容快照（前 500 字）。"""
        # 移除 script/style 标签
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()

        # 获取正文文本
        text = soup.get_text(separator="\n", strip=True)
        # 压缩空行
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        snapshot = "\n".join(lines)

        # 截取前 500 字
        result = snapshot[:500] if snapshot else None

        # 检测反爬虫 JavaScript 加密内容（如 lieju.com 返回的加密页面）
        # 如果检测到，返回 None 避免 AI 监测用无效内容生成问题
        if result and self._is_anti_scraping_content(result):
            logger.warning("检测到反爬虫加密内容，丢弃快照: %s", result[:80])
            return None

        return result

    def _is_anti_scraping_content(self, text: str) -> bool:
        """检测是否为反爬虫 JavaScript 加密内容。

        常见特征：
        1. 包含典型的 JS 反爬虫代码（var arg1=, document.cookie 等）
        2. 文本主要是 base64/hex 编码字符串，可读文本比例极低
        """
        # 特征1：典型的反爬虫 JavaScript 代码
        js_patterns = [
            "var arg1=", "var arg", "arg1='", "arg1=\"",
            "document.cookie", "document.location", "window.location",
            "eval(function", "setTimeout(function",
        ]
        for pattern in js_patterns:
            if pattern in text[:300]:
                return True

        # 特征2：可读文本比例极低（大量 base64/hex 编码字符串）
        # 如果前 300 字符中，可读中文/英文比例低于 30%，视为加密内容
        if len(text) >= 50:
            sample = text[:300]
            readable = sum(
                1 for c in sample
                if "\u4e00" <= c <= "\u9fff"  # 中文
                or c.isalpha()  # 英文字母
                or c in "，。、；：！？""''（）【】《》—… \n\t"
            )
            if readable / len(sample) < 0.3:
                return True

        return False


# 单例
article_fetcher = ArticleFetcher()
