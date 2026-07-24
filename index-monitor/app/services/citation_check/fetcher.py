"""Safe public URL fetching and lightweight article extraction."""

from dataclasses import dataclass
from html.parser import HTMLParser
import ipaddress
import json
import os
import re
import socket
import subprocess
import urllib.error
import urllib.request
from urllib.parse import urljoin, urlsplit

from .suitability import SuitabilityResult, evaluate_content_suitability


MAX_RESPONSE_BYTES = 2_000_000
CHROME_CANDIDATES = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
)


class UnsafeUrlError(ValueError):
    pass


@dataclass(frozen=True)
class FetchedContent:
    requested_url: str
    resolved_url: str
    canonical_url: str | None
    title: str
    text: str
    suitability: SuitabilityResult
    extraction_method: str = "html"


class _ArticleHtmlParser(HTMLParser):
    """Dependency-free fallback for lightweight article extraction."""

    SUPPRESSED = {"script", "style", "nav", "footer", "header", "aside", "form", "noscript"}

    def __init__(self):
        super().__init__()
        self.suppressed_depth = 0
        self.in_title = False
        self.in_h1 = False
        self.title_parts: list[str] = []
        self.h1_parts: list[str] = []
        self.text_parts: list[str] = []
        self.canonical: str | None = None

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag in self.SUPPRESSED:
            self.suppressed_depth += 1
        if tag == "title":
            self.in_title = True
        if tag == "h1":
            self.in_h1 = True
        if tag == "link" and "canonical" in str(attributes.get("rel", "")).lower():
            self.canonical = attributes.get("href")

    def handle_endtag(self, tag):
        if tag in self.SUPPRESSED and self.suppressed_depth:
            self.suppressed_depth -= 1
        if tag == "title":
            self.in_title = False
        if tag == "h1":
            self.in_h1 = False

    def handle_data(self, data):
        text = data.strip()
        if not text:
            return
        if self.in_title:
            self.title_parts.append(text)
        if self.in_h1:
            self.h1_parts.append(text)
        if not self.suppressed_depth and not self.in_title:
            self.text_parts.append(text)


def _is_public_ip(ip_text: str) -> bool:
    ip = ipaddress.ip_address(ip_text)
    benchmark_proxy = ipaddress.ip_network("198.18.0.0/15")
    if ip in benchmark_proxy and os.getenv("CITATION_ALLOW_BENCHMARK_PROXY") == "1":
        return True
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def validate_public_url(url: str) -> str:
    parsed = urlsplit((url or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise UnsafeUrlError("只支持公开的 HTTP/HTTPS URL")
    try:
        default_port = 443 if parsed.scheme == "https" else 80
        addresses = socket.getaddrinfo(parsed.hostname, parsed.port or default_port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise UnsafeUrlError("域名无法解析") from exc
    if not addresses or not any(_is_public_ip(item[4][0]) for item in addresses):
        raise UnsafeUrlError("URL 指向非公开网络地址")
    return url


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _extract_article(html: str, resolved_url: str) -> tuple[str, str, str | None, str]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        parser = _ArticleHtmlParser()
        parser.feed(html)
        title = " ".join(parser.h1_parts or parser.title_parts).strip()
        text = " ".join(" ".join(parser.text_parts).split())
        canonical = urljoin(resolved_url, parser.canonical) if parser.canonical else None
        return title, text, canonical, _infer_page_kind(title, text)

    soup = BeautifulSoup(html, "html.parser")
    title = ""
    if soup.title and soup.title.string:
        title = soup.title.string.strip()
    heading = soup.find("h1")
    if heading and heading.get_text(" ", strip=True):
        title = heading.get_text(" ", strip=True)

    canonical = None
    canonical_tag = soup.find("link", rel=lambda value: value and "canonical" in value)
    if canonical_tag and canonical_tag.get("href"):
        canonical = urljoin(resolved_url, canonical_tag["href"])

    for node in soup(["script", "style", "nav", "footer", "header", "aside", "form", "noscript"]):
        node.decompose()
    root = soup.find("article") or soup.find("main") or soup.body or soup
    text = " ".join(root.get_text(" ", strip=True).split())

    return title, text, canonical, _infer_page_kind(title, text)


def _infer_page_kind(title: str, text: str) -> str:
    page_kind = "article"
    lowered_title = title.lower()
    if any(marker in lowered_title for marker in ("404", "not found", "页面不存在")):
        page_kind = "error"
    elif any(marker in lowered_title for marker in ("登录", "login", "sign in")) and len(text) < 800:
        page_kind = "login"
    return page_kind


def _fetch_known_public_api(url: str, timeout: int) -> FetchedContent | None:
    """Use documented/public content endpoints for known JavaScript article pages."""
    parsed = urlsplit(url)
    match = re.fullmatch(r"/articles/([^/]+)", parsed.path.rstrip("/"))
    if parsed.hostname != "app.lumora.top" or not match:
        return None

    api_url = f"https://app.lumora.top/api/articles/{match.group(1)}"
    validate_public_url(api_url)
    request = urllib.request.Request(
        api_url,
        headers={
            "User-Agent": "LumoraCitationCheck/0.1",
            "Accept": "application/json",
            "Accept-Encoding": "identity",
        },
    )
    opener = urllib.request.build_opener(_SafeRedirectHandler())
    try:
        with opener.open(request, timeout=timeout) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise ValueError("页面内容超过抓取大小限制")
            payload = json.loads(raw.decode(response.headers.get_content_charset() or "utf-8", errors="replace"))
    except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError):
        return None

    title = str(payload.get("title") or "").strip()
    content = str(payload.get("content") or "")
    _, text, _, page_kind = _extract_article(content, url)
    suitability = evaluate_content_suitability(title=title, text=text, page_kind=page_kind)
    return FetchedContent(url, url, url, title, text, suitability, "public_api")


def _fetch_with_headless_browser(url: str, timeout: int) -> FetchedContent | None:
    """Render a public page without cookies/login, then extract the resulting DOM."""
    chrome = next((candidate for candidate in CHROME_CANDIDATES if os.path.exists(candidate)), None)
    if not chrome:
        return None
    validate_public_url(url)
    try:
        result = subprocess.run(
            [
                chrome,
                "--headless=new",
                "--incognito",
                "--disable-gpu",
                "--disable-extensions",
                "--no-first-run",
                "--no-default-browser-check",
                "--virtual-time-budget=8000",
                "--dump-dom",
                url,
            ],
            capture_output=True,
            text=True,
            timeout=max(timeout, 15),
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    title, text, canonical, page_kind = _extract_article(result.stdout, url)
    suitability = evaluate_content_suitability(title=title, text=text, page_kind=page_kind)
    if not suitability.suitable:
        return None
    return FetchedContent(url, url, canonical, title, text, suitability, "headless_browser")


def fetch_public_content(url: str, timeout: int = 15) -> FetchedContent:
    """Fetch a public HTML page and evaluate whether it is testable."""
    validate_public_url(url)
    opener = urllib.request.build_opener(_SafeRedirectHandler())
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "LumoraCitationCheck/0.1",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Encoding": "identity",
        },
    )
    try:
        with opener.open(request, timeout=timeout) as response:
            resolved_url = response.geturl()
            validate_public_url(resolved_url)
            content_type = response.headers.get_content_type()
            if content_type not in {"text/html", "application/xhtml+xml"}:
                suitability = evaluate_content_suitability(
                    title="",
                    text="",
                    access_issue="页面不是可检测的 HTML 内容",
                )
                return FetchedContent(url, resolved_url, None, "", "", suitability)
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise ValueError("页面内容超过抓取大小限制")
            charset = response.headers.get_content_charset() or "utf-8"
            html = raw.decode(charset, errors="replace")
    except urllib.error.HTTPError as exc:
        if exc.code == 403:
            suitability = SuitabilityResult(
                False,
                "blocked_by_site",
                "网站拒绝自动抓取（HTTP 403）。本工具不会绕过访问限制，请粘贴正文后继续检测。",
            )
        else:
            suitability = evaluate_content_suitability(title="", text="", access_issue=f"页面访问失败：{exc}")
        return FetchedContent(url, url, None, "", "", suitability)
    except (urllib.error.URLError, TimeoutError) as exc:
        suitability = evaluate_content_suitability(title="", text="", access_issue=f"页面访问失败：{exc}")
        return FetchedContent(url, url, None, "", "", suitability)

    title, text, canonical, page_kind = _extract_article(html, resolved_url)
    resolved_path = urlsplit(resolved_url).path or "/"
    if resolved_path in {"", "/"}:
        page_kind = "homepage"
    suitability = evaluate_content_suitability(title=title, text=text, page_kind=page_kind)
    if not suitability.suitable and suitability.rejection_code in {"no_text", "insufficient_information"}:
        fallback = _fetch_known_public_api(resolved_url, timeout)
        if fallback:
            return fallback
        fallback = _fetch_with_headless_browser(resolved_url, timeout)
        if fallback:
            return fallback
        suitability = SuitabilityResult(
            False,
            "dynamic_content_unavailable",
            "页面正文由 JavaScript 动态加载，但浏览器渲染后仍未提取到可用正文。请上传文档或粘贴正文后继续检测。",
        )
    return FetchedContent(url, resolved_url, canonical, title, text, suitability)
