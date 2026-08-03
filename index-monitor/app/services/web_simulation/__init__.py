"""网页端模拟引擎——为无 API 的 AI 平台提供检测能力。

通过 Playwright 模拟用户在网页版 AI 平台（如腾讯元宝）的搜索行为，
抓取 AI 回答与引用来源，复用 lumora-cite 的 classify_citation_hit 做命中判定。

设计要点：
- 选择器作为类常量，方便后续维护（页面结构变化时只改选择器）
- 登录 cookie 通过环境变量配置（不硬编码）
- 充分错误处理——网页端模拟容易失败，不阻塞其他平台
- 超时控制——网页端模拟可能很慢
- 截图功能——给客户提供证据
"""
from app.services.web_simulation.base import BaseWebSimulator, SimulationResult
from app.services.web_simulation.yuanbao import YuanbaoSimulator
from app.services.web_simulation.manager import WebSimulationManager, get_web_simulation_manager

__all__ = [
    "BaseWebSimulator",
    "SimulationResult",
    "YuanbaoSimulator",
    "WebSimulationManager",
    "get_web_simulation_manager",
]
