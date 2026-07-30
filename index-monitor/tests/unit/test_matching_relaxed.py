# index-monitor/tests/unit/test_matching_relaxed.py
"""匹配放宽的单元测试（阶段 1 - ⑥a）。

覆盖：
- 扩充的国内跟踪参数被剥离（ref/source/from/scm/un/cid/p/src）
- mobile 子域归一（m./mobile./wap. 与 www. 同等剥离）
- path 前缀匹配 → exact（AI 引用同域同路径前缀页面视为同一内容）
- 去全部 query 兜底匹配 → exact（仅 path 相同即视为命中）
- 原有行为不破：精确相等 exact、域名命中 domain、无命中 none
"""
import pytest

from app.services.citation_check.matching import (
    classify_citation_hit,
    normalize_url,
    url_domain,
)


# ---------- normalize_url：跟踪参数剥离 ----------

@pytest.mark.parametrize("tracking", ["ref", "source", "from", "scm", "un", "cid", "p", "src"])
def test_normalize_strips_domestic_tracking_params(tracking):
    """国内常见跟踪参数应被剥离。

    断言用 `f"{tracking}="` 检查参数键，避免单字符参数（如 p）误判为
    域名/路径的子串（example 含字母 p）。"""
    url = f"https://example.com/article/123?{tracking}=abc&utm_source=x"
    norm = normalize_url(url)
    assert f"{tracking}=" not in norm
    assert "utm_source" not in norm
    # 两个参数都是跟踪参数，剥离后应无 query
    assert "?" not in norm


def test_normalize_preserves_content_query_params():
    """非跟踪参数（如分页 id）应保留。"""
    norm = normalize_url("https://example.com/list?id=42")
    assert "id=42" in norm


# ---------- normalize_url：mobile 子域归一 ----------

@pytest.mark.parametrize("prefix", ["m.", "mobile.", "wap."])
def test_normalize_strips_mobile_subdomain(prefix):
    """mobile 子域应被剥离，与 www. 同等处理。"""
    norm = normalize_url(f"https://{prefix}example.com/article/1")
    assert norm.startswith("https://example.com/")


def test_normalize_strips_www():
    """www. 剥离保持不变（回归）。"""
    assert normalize_url("https://www.example.com/a").startswith("https://example.com/a")


# ---------- classify_citation_hit：path 前缀匹配 → exact ----------

def test_classify_path_prefix_match_is_exact():
    """AI 返回的来源 URL 是目标 URL 的路径前缀 → exact（同一内容层级）。"""
    target = "https://example.com/articles/geo-strategy"
    source = "https://example.com/articles/geo-strategy/summary"
    hit = classify_citation_hit([target], [source])
    assert hit.layer == "exact"


def test_classify_path_prefix_reverse_is_exact():
    """反向：目标是来源的路径前缀 → 也算 exact。"""
    target = "https://example.com/articles/geo-strategy/summary"
    source = "https://example.com/articles/geo-strategy"
    hit = classify_citation_hit([target], [source])
    assert hit.layer == "exact"


def test_classify_different_path_not_exact_prefix():
    """同域但路径无前缀关系 → 不应因 path 前缀规则误判 exact（落 domain）。"""
    target = "https://example.com/articles/geo-strategy"
    source = "https://example.com/articles/seo-tips"
    hit = classify_citation_hit([target], [source])
    assert hit.layer == "domain"


# ---------- classify_citation_hit：非跟踪 query 差异不应误判 exact ----------

def test_classify_non_tracking_query_difference_is_domain():
    """同域同 path，仅非跟踪 query 不同（如 ?category=geo vs ?tag=ai）→ domain。

    不做"去全部 query 兜底"：query 可能是内容标识（如 ?id=1 vs ?id=2 是不同
    文章），激进剥离会引入误判。仅跟踪参数差异由 tier1 归一处理。"""
    target = "https://example.com/article?category=geo"
    source = "https://example.com/article?tag=ai"
    hit = classify_citation_hit([target], [source])
    assert hit.layer == "domain"


# ---------- 原有行为回归 ----------

def test_classify_exact_url_match():
    """精确 URL 相等 → exact（回归）。"""
    hit = classify_citation_hit(
        ["https://example.com/a"],
        ["https://example.com/a"],
    )
    assert hit.layer == "exact"


def test_classify_domain_match():
    """同域不同 path → domain（回归）。"""
    hit = classify_citation_hit(
        ["https://example.com/a"],
        ["https://example.com/b"],
    )
    assert hit.layer == "domain"


def test_classify_none():
    """无任何来源 → none（回归）。"""
    hit = classify_citation_hit(["https://example.com/a"], [])
    assert hit.layer == "none"


def test_classify_unverifiable():
    """不可验证 → unverifiable（回归）。"""
    hit = classify_citation_hit(
        ["https://example.com/a"],
        ["https://other.com/x"],
        verifiable=False,
    )
    assert hit.layer == "unverifiable"


def test_classify_tracking_param_difference_is_exact():
    """目标与来源仅差跟踪参数 → exact（归一后相等）。"""
    target = "https://example.com/a?utm_source=feed"
    source = "https://example.com/a?from=app"
    hit = classify_citation_hit([target], [source])
    assert hit.layer == "exact"


# ---------- classify_citation_hit：内容子站/移动镜像同主域判定 ----------
# 回归场景：b2b168 平台 info.b2b168.com（资讯子站）与 mip.b2b168.com（百度 MIP
# 移动版）承载同一内容，AI 常返回 mip. 镜像作为来源，应识别为同主域命中，
# 而非因 _strip_subdomain 未剥离 info./mip. 误判为 none。


def test_classify_info_and_mip_subdomain_is_domain():
    """info. 子站与 mip. 移动镜像同主域、同路径 → domain 命中。

    info. 不是移动前缀不做归一剥离，但二者注册域（b2b168.com）相同，
    tier3 同主域判定应识别为 domain，而非 none。
    """
    target = "https://info.b2b168.com/s168-316846386.html"
    source = "https://mip.b2b168.com/s168-316846386.html"
    hit = classify_citation_hit([target], [source])
    assert hit.layer == "domain"


def test_classify_mip_and_www_same_path_is_exact():
    """mip. 移动镜像与 www. 桌面版同路径 → exact（归一后精确相等）。

    mip. 作为移动版前缀应与 www./m. 同等剥离，归一后二者 host 与 path
    完全一致，走 tier1 精确匹配。
    """
    target = "https://www.b2b168.com/s168-316846386.html"
    source = "https://mip.b2b168.com/s168-316846386.html"
    hit = classify_citation_hit([target], [source])
    assert hit.layer == "exact"


def test_classify_info_and_other_info_subdomain_is_domain():
    """两个 info. 子域同主域不同 path → domain（注册域相同）。"""
    target = "https://info.b2b168.com/s168-316846386.html"
    source = "https://info.b2b168.com/s168-999999999.html"
    hit = classify_citation_hit([target], [source])
    assert hit.layer == "domain"
