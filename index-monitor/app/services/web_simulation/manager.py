"""网页端模拟器管理器——注册、查询与统一调度。"""
import logging
from typing import Optional

from app.services.web_simulation.base import BaseWebSimulator, SimulationResult
from app.services.web_simulation.yuanbao import YuanbaoSimulator

logger = logging.getLogger(__name__)


class WebSimulationManager:
    """网页端模拟器管理器。

    统一注册、查询与调度各平台网页端模拟器。模拟失败时返回带 error 的
    SimulationResult，不抛异常，避免阻塞其他平台的引用检测。
    """

    def __init__(self):
        self._simulators: dict[str, BaseWebSimulator] = {}
        self._register_defaults()

    def _register_defaults(self) -> None:
        """注册默认模拟器。"""
        self.register(YuanbaoSimulator())

    def register(self, simulator: BaseWebSimulator) -> None:
        """注册一个模拟器（按 platform_id 索引，后注册的覆盖前者）。"""
        if not simulator.platform_id:
            raise ValueError("模拟器必须定义非空 platform_id")
        self._simulators[simulator.platform_id] = simulator

    def get(self, platform_id: str) -> Optional[BaseWebSimulator]:
        """按 platform_id 获取模拟器，不存在返回 None。"""
        return self._simulators.get(platform_id)

    def available_platforms(self) -> list[str]:
        """返回已注册的平台 id 列表。"""
        return list(self._simulators.keys())

    async def simulate(
        self,
        platform_id: str,
        question: str,
        target_urls: list[str],
        timeout: int = 60,
    ) -> SimulationResult:
        """调度指定平台的模拟器执行搜索。

        模拟器内部异常会被捕获并包装成 SimulationResult.error 返回，
        不向上抛异常——保证引用检测流程中单个平台失败不阻塞其他平台。
        """
        simulator = self.get(platform_id)
        if simulator is None:
            return SimulationResult(error=f"不支持的平台: {platform_id}")

        try:
            return await simulator.simulate_search(question, target_urls, timeout)
        except Exception as exc:
            logger.error("网页端模拟失败 [%s]: %s", platform_id, exc, exc_info=True)
            return SimulationResult(error=str(exc))


# 全局单例：模块级实例化，进程内复用（Playwright 浏览器按需启动/关闭）
_manager = WebSimulationManager()


def get_web_simulation_manager() -> WebSimulationManager:
    """获取全局 WebSimulationManager 单例。"""
    return _manager
