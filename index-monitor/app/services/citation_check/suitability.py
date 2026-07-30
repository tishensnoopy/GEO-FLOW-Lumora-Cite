"""Content suitability rules for Citation Check."""

from dataclasses import dataclass, field
import re


@dataclass(frozen=True)
class SuitabilityResult:
    suitable: bool
    rejection_code: str | None = None
    rejection_reason: str | None = None
    warnings: list[str] = field(default_factory=list)


# 反爬虫 JS 挑战页的典型代码特征（如 lieju.com 返回的 var arg1='...' 加密页）
# 命中任一即判定为反爬内容，避免把 JS 代码当正文传给问题生成器。
ANTI_SCRAPING_JS_PATTERNS = (
    "var arg1=", "var arg", "arg1='", 'arg1="',
    "document.cookie", "document.location", "window.location",
    "eval(function", "setTimeout(function",
)


def _is_anti_scraping_content(text: str) -> bool:
    """检测是否为反爬虫 JavaScript 加密内容。

    两类特征：
    1. 典型反爬 JS 代码（var arg1=、document.cookie 等）出现在前 300 字符；
    2. 可读文本比例极低：前 300 字符中中文/空格/标点占比 < 15%，
       判定为 base64/hex 编码串等加密内容（如 lieju.com 反爬挑战页的负载）。

    注意：可读比例不算纯英文字母，因为 base64 串含大量字母会干扰判定；
    用中文 + 空格 + 标点作为"人类可读"信号更可靠（正常文章必有分词空格或中文）。
    """
    if not text:
        return False
    sample = text[:300]
    for pattern in ANTI_SCRAPING_JS_PATTERNS:
        if pattern in sample:
            return True
    if len(text) >= 50:
        readable = sum(
            1 for c in sample
            if "\u4e00" <= c <= "\u9fff"  # 中文
            or c.isspace()  # 空格（英文分词）
            or c in "，。、；：！？『』「」\"\"''（）【】《》—….,;:!?()[]{}\"'-"
        )
        if readable / len(sample) < 0.15:
            return True
    return False


def _has_complete_topic(title: str, text: str) -> bool:
    sentences = [part.strip() for part in re.split(r"[。！？.!?]+", text) if len(part.strip()) >= 6]
    factual_signal = bool(re.search(r"\d|年|月|日|%|％|研究|报告|发布|数据显示", text))
    return bool(title.strip()) and (len(sentences) >= 3 or (len(sentences) >= 2 and factual_signal))


def evaluate_content_suitability(
    *,
    title: str,
    text: str,
    page_kind: str = "article",
    access_issue: str | None = None,
    qualified_question_count: int | None = None,
    visual_dependency: bool = False,
    partial_dynamic_content: bool = False,
    recently_published: bool = False,
    niche_topic: bool = False,
) -> SuitabilityResult:
    """Apply the documented reject-vs-warning boundary."""
    clean_text = re.sub(r"\s+", " ", text or "").strip()
    if access_issue:
        return SuitabilityResult(False, "access_issue", access_issue)
    # 反爬虫检测：必须在内容长度/主题检查之前，否则反爬 JS 串（长度通常 > 200）
    # 会骗过 insufficient_information 检查，被误判 suitable=True，进而把 JS 代码
    # 当正文传给问题生成器，生成"网页出现 var arg1 乱码是什么意思"等无关问题。
    if _is_anti_scraping_content(clean_text):
        return SuitabilityResult(
            False,
            "anti_scraping",
            "页面返回反爬虫加密内容，无法提取真实正文。请粘贴正文后继续检测，或更换可正常访问的链接。",
        )
    if page_kind in {"homepage", "directory", "search", "login", "error"}:
        return SuitabilityResult(False, "not_single_content", "输入链接不是可检测的单篇公开内容")
    if not clean_text:
        return SuitabilityResult(False, "no_text", "页面没有可提取的正文")
    if len(clean_text) < 200 and not _has_complete_topic(title, clean_text):
        return SuitabilityResult(False, "insufficient_information", "正文信息不足，无法识别一个完整主题")
    if qualified_question_count is not None and qualified_question_count < 3:
        return SuitabilityResult(False, "insufficient_questions", "无法生成至少 3 个合格自然问题")

    warnings: list[str] = []
    if len(clean_text) < 500:
        warnings.append("正文较短，三问只能覆盖较窄范围")
    if visual_dependency:
        warnings.append("内容高度依赖图片、图表或视频，当前检测可能遗漏视觉信息")
    if partial_dynamic_content:
        warnings.append("页面正文仅部分抓取，检测基于当前可提取内容")
    if recently_published:
        warnings.append("内容发布时间较近，搜索索引和 AI 检索系统可能尚未发现页面")
    if niche_topic:
        warnings.append("内容主题较小众，未命中不代表内容质量较低")
    return SuitabilityResult(True, warnings=warnings)
