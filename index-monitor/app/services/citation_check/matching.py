"""URL normalization and citation hit classification."""

from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


TRACKING_QUERY_KEYS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "spm",
}
TRACKING_QUERY_PREFIXES = ("utm_",)


@dataclass(frozen=True)
class CitationHit:
    layer: str
    matched_url: str | None = None


def _is_tracking_key(key: str) -> bool:
    lowered = key.lower()
    return lowered in TRACKING_QUERY_KEYS or lowered.startswith(TRACKING_QUERY_PREFIXES)


def normalize_url(url: str) -> str:
    """Normalize a URL without collapsing content-identifying query params."""
    raw = (url or "").strip()
    if not raw:
        return ""
    try:
        parsed = urlsplit(raw if "://" in raw else f"https://{raw}")
        scheme = parsed.scheme.lower()
        host = (parsed.hostname or "").lower()
        if host.startswith("www."):
            host = host[4:]
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
        return host[4:] if host.startswith("www.") else host
    except (TypeError, ValueError):
        return ""


def classify_citation_hit(
    target_urls: list[str],
    source_urls: list[str],
    *,
    verifiable: bool = True,
) -> CitationHit:
    """Classify a model answer as exact, domain, none, or unverifiable."""
    if not verifiable:
        return CitationHit("unverifiable")

    normalized_targets = {normalize_url(url) for url in target_urls if normalize_url(url)}
    target_domains = {url_domain(url) for url in target_urls if url_domain(url)}

    for source in source_urls:
        if normalize_url(source) in normalized_targets:
            return CitationHit("exact", source)
    for source in source_urls:
        if url_domain(source) in target_domains:
            return CitationHit("domain", source)
    return CitationHit("none")
