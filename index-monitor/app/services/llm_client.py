# index-monitor/app/services/llm_client.py
"""LLM 客户端配置加载。

Phase 2 清理后仅保留 ``load_ai_configs``（通用 AI 配置加载器）。
问题生成相关的 LLM 调用函数（call_deepseek / make_call_generator /
build_question_providers 等）已随问题生成阶段一并删除——3 阶段流程不再
需要目的推断和问题生成。
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.system_config import SystemConfig


async def load_ai_configs(db: AsyncSession, keys: list[str]) -> dict[str, str]:
    """从 system_config 表批量加载指定 key 的配置，返回 {config_key: config_value}。"""
    result = await db.execute(
        select(SystemConfig).where(SystemConfig.config_key.in_(keys))
    )
    rows = result.scalars().all()
    return {row.config_key: row.config_value for row in rows}
