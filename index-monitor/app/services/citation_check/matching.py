"""URL normalization and citation hit classification."""

from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


TRACKING_QUERY_KEYS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "spm",
    # 国内常见跟踪参数（阶段 1 - ⑥a 匹配放宽）
    "ref",
    "source",
    "from",
    "scm",
    "un",
    "cid",
    "p",
    "src",
}
TRACKING_QUERY_PREFIXES = ("utm_",)

# 移动/镜像子域前缀，归一时与 www. 同等剥离（同一内容的移动版）
# mip. = 百度 MIP（Mobile Instant Pages）移动加速镜像，与 m./wap. 同类
_MOBILE_SUBDOMAIN_PREFIXES = ("www.", "m.", "mobile.", "wap.", "mip.")


@dataclass(frozen=True)
class CitationHit:
    layer: str
    matched_url: str | None = None


def _is_tracking_key(key: str) -> bool:
    lowered = key.lower()
    return lowered in TRACKING_QUERY_KEYS or lowered.startswith(TRACKING_QUERY_PREFIXES)


def _strip_subdomain(host: str) -> str:
    """剥离 www. / m. / mobile. / wap. / mip. 等子域前缀，归一到主域。

    用于同一内容的桌面版/移动版相互匹配。
    """
    for prefix in _MOBILE_SUBDOMAIN_PREFIXES:
        if host.startswith(prefix):
            return host[len(prefix):]
    return host


def _registrable_domain(url: str) -> str:
    """提取注册域（简化为最后两段），用于 tier3 同主域判定。

    覆盖 info. 等内容子站镜像场景：_strip_subdomain 只剥离已知移动/镜像前缀，
    对 info. 等通用子站名不做剥离（避免误伤 info.com 这类主域本身就是 info. 开头
    的站点）。tier3 改用注册域比较，才能把 info.b2b168.com 与 mip.b2b168.com
    识别为同主域 b2b168.com。

    简化实现取最后两段，对 .com / .cn 等常见单段 TLD 适用；对复合 TLD
    （.com.cn / .co.uk）会把 com.cn 当作注册域，可能偏宽，但 domain 命中本为
    宽松判定，且国内 B2B 站点多为 .com，可接受。
    """
    try:
        parsed = urlsplit(url if "://" in url else f"https://{url}")
        host = (parsed.hostname or "").lower()
        if not host:
            return ""
        parts = host.split(".")
        if len(parts) <= 2:
            return host
        return ".".join(parts[-2:])
    except (TypeError, ValueError):
        return ""


def normalize_url(url: str) -> str:
    """Normalize a URL without collapsing content-identifying query params."""
    raw = (url or "").strip()
    if not raw:
        return ""
    try:
        parsed = urlsplit(raw if "://" in raw else f"https://{raw}")
        scheme = parsed.scheme.lower()
        host = _strip_subdomain((parsed.hostname or "").lower())
        port = parsed.port
        if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
            host = f"{host}:{port}"
        path = parsed.path or "/"
        if path != "/":
            path = path.rstrip("/")
        query_pairs = [
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if not _is_tracking_key(key)
        ]
        query = urlencode(sorted(query_pairs))
        return urlunsplit((scheme, host, path, query, ""))
    except (TypeError, ValueError):
        return raw.rstrip("/")


def url_domain(url: str) -> str:
    try:
        parsed = urlsplit(url if "://" in url else f"https://{url}")
        host = (parsed.hostname or "").lower()
        return _strip_subdomain(host)
    except (TypeError, ValueError):
        return ""


def _path_prefix_match(a: str, b: str) -> bool:
    """同域同路径前缀（父/子关系）判定。

    仅当一方路径是另一方的真前缀时返回 True（如 /articles/x 与 /articles/x/summary）。
    相等不算（相等已由 tier1 精确匹配处理），避免同 path 不同 query 误判。
    """
    sa, sb = urlsplit(a), urlsplit(b)
    if sa.netloc != sb.netloc:
        return False
    pa, pb = sa.path.rstrip("/"), sb.path.rstrip("/")
    if not pa or not pb or pa == pb:
        return False
    return pa.startswith(pb + "/") or pb.startswith(pa + "/")


def classify_citation_hit(
    target_urls: list[str],
    source_urls: list[str],
    *,
    verifiable: bool = True,
) -> CitationHit:
    """Classify a model answer as exact, domain, none, or unverifiable.

    匹配层级（阶段 1 - ⑥a 放宽）：
    - tier1：跟踪参数剥离后精确相等 → exact
    - tier2：同域同路径前缀（父/子关系）→ exact（AI 引用同内容层级页面）
    - tier3：同域不同 path → domain
    - 其他 → none
    不做"去全部 query 兜底"：query 可能是内容标识（?id=1 vs ?id=2），激进剥离会误判。
    """
    if not verifiable:
        return CitationHit("unverifiable")

    normalized_targets = {normalize_url(url) for url in target_urls if normalize_url(url)}
    # tier3 用注册域（eTLD+1 简化版）判定，覆盖 info./mip. 等内容子站镜像：
    # _strip_subdomain 只剥离 www./m./mip. 等已知前缀，无法识别 info. 等通用子站，
    # 改用 _registrable_domain 取最后两段比较，确保同主域不同子域均判 domain。
    target_reg_domains = {
        rd for url in target_urls if (rd := _registrable_domain(url))
    }

    # tier1：归一后精确相等
    for source in source_urls:
        if normalize_url(source) in normalized_targets:
            return CitationHit("exact", source)

    # tier2：同域同路径前缀（父/子）
    normalized_sources = [normalize_url(s) for s in source_urls]
    for ns in normalized_sources:
        for nt in normalized_targets:
            if _path_prefix_match(ns, nt):
                return CitationHit("exact", ns)

    # tier3：同注册域 → domain
    for source in source_urls:
        if _registrable_domain(source) in target_reg_domains:
            return CitationHit("domain", source)
    return CitationHit("none")
