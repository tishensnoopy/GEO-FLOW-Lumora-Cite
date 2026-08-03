"""腾讯元宝网页端模拟器。

元宝（yuanbao.tencent.com）无公开 API，通过 Playwright 模拟用户在网页端搜索。

依赖：
- Playwright 1.61+（已安装）
- Chromium 浏览器（playwright install chromium）
- 登录 cookie：通过环境变量 ``YUANBAO_COOKIE`` 配置，格式为浏览器原始
  Cookie 头字符串（"name=value; name2=value2"）。未配置时仍可访问，但
  元宝部分功能可能受限。

重要：元宝页面选择器可能因前端迭代而失效。选择器全部集中在 ``SELECTORS``
类常量中，失效时只需更新选择器，无需改动主流程。
"""
import logging
import os
from typing import Optional
from urllib.parse import urlsplit

from app.services.web_simulation.base import BaseWebSimulator, SimulationResult

logger = logging.getLogger(__name__)


class YuanbaoSimulator(BaseWebSimulator):
    """腾讯元宝网页端模拟器。"""

    platform_id = "yuanbao"
    platform_name = "元宝"
    homepage_url = "https://yuanbao.tencent.com/"

    # 页面选择器（集中管理，方便后续维护）。
    # 注意：这些选择器基于元宝常见页面结构，可能随前端迭代失效。
    SELECTORS = {
        "input_box": "textarea",
        "send_button": "button[data-testid='send_button']",
        "answer_container": ".agent-chat__msg__content",
        "source_links": ".chat-card-source a",
        "loading_indicator": ".loading-dot",
    }

    async def simulate_search(
        self,
        question: str,
        target_urls: list[str],
        timeout: int = 60,
    ) -> SimulationResult:
        """模拟在元宝搜索关键词。"""
        from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

        result = SimulationResult()
        browser = None
        page = None

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                    viewport={"width": 1280, "height": 720},
                    locale="zh-CN",
                )

                # 设置登录 cookie（如果配置了）——直接同步读取环境变量，
                # os.getenv 不阻塞，无需 run_in_executor。
                cookie_str = os.getenv("YUANBAO_COOKIE", "")
                if cookie_str:
                    cookies = self._parse_cookie_header(cookie_str, self.homepage_url)
                    if cookies:
                        await context.add_cookies(cookies)

                page = await context.new_page()

                # 1. 打开元宝首页
                logger.info("元宝模拟：打开首页 %s", self.homepage_url)
                await page.goto(self.homepage_url, wait_until="networkidle", timeout=30000)
                await page.wait_for_timeout(2000)

                # 2. 输入问题
                input_box = page.locator(self.SELECTORS["input_box"]).first
                await input_box.wait_for(state="visible", timeout=15000)
                await input_box.fill(question)
                await page.wait_for_timeout(500)

                # 3. 发送（优先 Enter，失败则尝试发送按钮）
                try:
                    await input_box.press("Enter")
                except Exception:
                    send_btn = page.locator(self.SELECTORS["send_button"])
                    if await send_btn.count() > 0:
                        await send_btn.first.click()
                    else:
                        raise RuntimeError("找不到发送按钮，无法提交问题")

                # 4. 等待回答完成
                try:
                    await page.wait_for_selector(
                        self.SELECTORS["answer_container"],
                        timeout=timeout * 1000,
                    )
                    # 等待流式输出稳定（loading 指示器消失或固定时间）
                    await self._wait_for_answer_stable(page, timeout=timeout)
                except PlaywrightTimeoutError:
                    result.error = "等待元宝回答超时"
                    await self._take_screenshot(page, question, result)
                    return result

                # 5. 抓取回答文本
                answer_elements = await page.locator(self.SELECTORS["answer_container"]).all()
                answer_texts = []
                for elem in answer_elements:
                    text = await elem.inner_text()
                    if text.strip():
                        answer_texts.append(text.strip())
                result.answer = "\n".join(answer_texts)

                # 6. 抓取引用来源
                source_links = await page.locator(self.SELECTORS["source_links"]).all()
                sources = []
                seen_urls = set()
                for link in source_links:
                    href = await link.get_attribute("href")
                    title = await link.inner_text()
                    if href and href not in seen_urls:
                        seen_urls.add(href)
                        sources.append({"url": href, "title": title.strip()})
                result.sources = sources

                # 7. 判定命中类型（辅助参考，engine 层会重新判定）
                result.hit_type = self._classify_hit(sources, target_urls)
                result.success = True

                # 8. 截图存证（默认开启，便于客户核查与失败排查）
                await self._take_screenshot(page, question, result)

                await browser.close()
                browser = None

        except Exception as exc:
            logger.error("元宝模拟失败: %s", exc, exc_info=True)
            result.error = str(exc)
            result.success = False
            # 尽量留一张截图辅助排查
            if page is not None:
                await self._take_screenshot(page, question, result)
            if browser is not None:
                try:
                    await browser.close()
                except Exception:
                    pass

        return result

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------

    async def _wait_for_answer_stable(self, page, *, timeout: int) -> None:
        """等待流式回答稳定。

        策略：等 loading 指示器消失（最多 timeout/2 秒），再固定等 3 秒让 DOM 稳定。
        loading 指示器不出现或选择器失效时降级为固定等待。
        """
        try:
            await page.wait_for_selector(
                self.SELECTORS["loading_indicator"],
                state="hidden",
                timeout=min(timeout * 500, 15000),
            )
        except Exception:
            # loading 指示器选择器可能不准，降级为固定等待
            logger.debug("元宝模拟：loading 指示器未出现或选择器失效，降级为固定等待")
        await page.wait_for_timeout(3000)

    async def _take_screenshot(self, page, question: str, result: SimulationResult) -> None:
        """截图存证。失败时仅记日志，不影响主流程。"""
        try:
            import hashlib
            digest = hashlib.md5(question.encode("utf-8")).hexdigest()[:8]
            path = f"/tmp/yuanbao_{digest}.png"
            await page.screenshot(path=path, full_page=True)
            result.screenshot_path = path
            logger.info("元宝模拟截图已保存: %s", path)
        except Exception as exc:
            logger.debug("元宝模拟截图失败（已忽略）: %s", exc)

    @staticmethod
    def _parse_cookie_header(cookie_str: str, base_url: str) -> list[dict]:
        """将浏览器原始 Cookie 头解析为 Playwright cookie 格式。

        Args:
            cookie_str: "name1=value1; name2=value2" 格式的 cookie 字符串。
            base_url: 用于推导 cookie 的 domain/path。

        Returns:
            Playwright ``add_cookies`` 所需的 list[dict]。
        """
        parsed = urlsplit(base_url)
        domain = (parsed.hostname or "").lstrip(".")
        if not domain:
            return []
        cookies: list[dict] = []
        for pair in cookie_str.split(";"):
            pair = pair.strip()
            if not pair or "=" not in pair:
                continue
            name, value = pair.split("=", 1)
            name = name.strip()
            value = value.strip()
            if not name:
                continue
            cookies.append({
                "name": name,
                "value": value,
                "domain": domain,
                "path": "/",
                "httpOnly": False,
                "secure": parsed.scheme == "https",
                "sameSite": "Lax",
            })
        return cookies
