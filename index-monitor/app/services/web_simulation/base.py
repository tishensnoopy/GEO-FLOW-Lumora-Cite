"""网页端模拟器基类与结果数据类。"""
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class SimulationResult:
    """网页端模拟检测结果。

    Attributes:
        answer: AI 回答文本（多段以换行拼接）。
        sources: 引用来源列表，每项形如 {"url": "...", "title": "..."}。
        hit_type: 命中类型（exact / domain / none）。注意：engine.run_citation_check
            会基于 target_urls 重新做命中判定，此字段仅作辅助参考。
        screenshot_path: 截图文件路径（失败时用于排查）。
        error: 失败时的错误描述，成功时为 None。
        success: 是否成功拿到 AI 回答。
    """
    answer: str = ""
    sources: list[dict] = field(default_factory=list)
    hit_type: str = "none"
    screenshot_path: Optional[str] = None
    error: Optional[str] = None
    success: bool = False


class BaseWebSimulator(ABC):
    """AI 平台网页端模拟器基类。

    子类需实现 ``simulate_search``，并用类常量定义页面选择器，
    方便后续在页面结构变化时集中维护。
    """

    platform_id: str = ""
    platform_name: str = ""
    homepage_url: str = ""

    @abstractmethod
    async def simulate_search(
        self,
        question: str,
        target_urls: list[str],
        timeout: int = 60,
    ) -> SimulationResult:
        """模拟用户在网页版搜索关键词，返回 AI 回答和引用判定。

        Args:
            question: 搜索关键词/问题。
            target_urls: 客户文章 URL 列表（用于判定是否被引用）。
                注意：实际命中判定由 engine.run_citation_check 统一完成，
                此处传入仅供模拟器内部辅助使用。
            timeout: 整体超时秒数。

        Returns:
            SimulationResult
        """
        ...

    def _classify_hit(self, sources: list[dict], target_urls: list[str]) -> str:
        """判定引用命中类型（复用 matching.py 的逻辑）。

        供模拟器内部参考使用；engine 层会基于返回的 sources 重新判定。
        """
        from app.services.citation_check.matching import classify_citation_hit
        source_urls = [s.get("url", "") for s in sources if s.get("url")]
        hit = classify_citation_hit(target_urls, source_urls)
        return hit.layer
