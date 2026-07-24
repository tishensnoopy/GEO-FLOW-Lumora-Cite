"""Content suitability rules for Citation Check."""

from dataclasses import dataclass, field
import re


@dataclass(frozen=True)
class SuitabilityResult:
    suitable: bool
    rejection_code: str | None = None
    rejection_reason: str | None = None
    warnings: list[str] = field(default_factory=list)


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
