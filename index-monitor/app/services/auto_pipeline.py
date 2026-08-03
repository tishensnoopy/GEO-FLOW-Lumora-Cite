"""自动联动管道：新文章入库 → AI 收录检测 → 问题监测。

链式异步回调，两阶段独立执行，错误隔离。
手动添加文章后由 asyncio.create_task 触发，不阻塞 HTTP 响应。
"""
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session
from app.models.client_question import ClientQuestion
from app.services.ai_index_checker import AIIndexChecker
from app.services.citation_checker import CitationChecker

logger = logging.getLogger(__name__)


class AutoPipeline:
    """新文章入库自动联动管道。"""

    async def trigger_for_url(self, url: str, client_id: str) -> None:
        """对新文章触发完整联动链路。

        阶段 1: AI 收录检测（可选，该 URL × 所有配置模型，单模型失败不阻塞）
        阶段 2: 引用检测——直接执行，不依赖收录检测结果，
                仅以客户是否配置 active 问题为门槛
        """
        logger.info("自动联动启动: %s (client=%s)", url, client_id)

        # ──────── 阶段 1: AI 收录检测 ────────
        await self._run_ai_index_check(url)

        # ──────── 阶段 2: 自动衔接判定 + 问题监测 ────────
        await self._auto_trigger_citation_check(url, client_id)

    async def _run_ai_index_check(self, url: str) -> None:
        """阶段 1：对该 URL × 所有配置模型执行收录检测。单模型失败不阻塞。"""
        async with async_session() as db:
            checker = AIIndexChecker(db)
            models = checker._get_configured_models()
            if not models:
                logger.warning("自动联动-收录检测 %s：无配置模型，跳过", url)
                return

            for model in models:
                try:
                    await checker.check_url(url, model)
                except Exception as exc:
                    logger.error(
                        "自动联动-收录检测失败 %s [%s]: %s", url, model, exc
                    )
                    # 单模型失败不阻塞其他模型

    async def _auto_trigger_citation_check(
        self, url: str, client_id: str
    ) -> None:
        """阶段 2：引用检测。直接执行，不依赖收录检测结果。

        仅以客户是否配置 active 问题为门槛——有则执行引用检测，无则跳过。
        收录检测（阶段 1）为可选前置，其结果不影响本阶段是否执行。
        """
        async with async_session() as db:
            # 查询客户是否有 active 问题
            q_result = await db.execute(
                select(ClientQuestion.id).where(
                    ClientQuestion.client_id == client_id,
                    ClientQuestion.status == "active",
                ).limit(1)
            )
            if q_result.scalar_one_or_none() is None:
                logger.warning(
                    "自动联动-跳过问题监测 %s：客户 %s 未配置监测问题",
                    url, client_id,
                )
                return

        # 引用检测（独立 session）
        async with async_session() as db:
            try:
                checker = CitationChecker(db)
                await checker.check_url(url, client_id)
                logger.info("自动联动-问题监测完成: %s", url)
            except Exception as exc:
                logger.error("自动联动-问题监测失败 %s: %s", url, exc)


# 模块级便捷函数，供路由层 asyncio.create_task 调用
async def trigger_for_url(url: str, client_id: str) -> None:
    """模块级便捷函数：触发自动联动。"""
    pipeline = AutoPipeline()
    await pipeline.trigger_for_url(url, client_id)
