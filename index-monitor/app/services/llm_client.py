# index-monitor/app/services/llm_client.py
"""LLM 客户端：使用 DeepSeek OpenAI 兼容 API 进行问题生成和目的推断。

lumora-cite 的 generate_candidates / parse_purpose_response 需要一个同步的
call_generator(prompt) -> str 可调用对象。本模块封装 DeepSeek API 调用，
并提供 make_call_generator 工厂供 citation_checker 使用。
"""
import asyncio
import logging
from typing import Callable

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.system_config import SystemConfig

logger = logging.getLogger(__name__)

# DeepSeek OpenAI 兼容 API
DEEPSEEK_API_BASE = "https://api.deepseek.com/v1"
# 注意：deepseek-chat 模型名已被 DeepSeek API 废弃（2026年），
# 当前支持的模型名为 deepseek-v4-pro / deepseek-v4-flash。
# flash 版本更快更省，适合问题生成；pro 版本推理更强，适合复杂分析。
DEFAULT_QUESTION_MODEL = "deepseek-v4-flash"
DEFAULT_TIMEOUT = 120  # 秒，问题生成/目的推断可能较慢


async def get_ai_config(db: AsyncSession, key: str) -> str:
    """从 system_config 表读取指定 AI 配置值。"""
    result = await db.execute(
        select(SystemConfig).where(SystemConfig.config_key == key)
    )
    cfg = result.scalar_one_or_none()
    return cfg.config_value if cfg else ""


async def load_ai_configs(db: AsyncSession, keys: list[str]) -> dict[str, str]:
    """批量读取 AI 配置，返回 {config_key: config_value} 字典。"""
    result = await db.execute(
        select(SystemConfig).where(SystemConfig.config_key.in_(keys))
    )
    rows = result.scalars().all()
    return {row.config_key: row.config_value for row in rows}


def call_deepseek_sync(
    api_key: str,
    model: str,
    prompt: str,
    timeout: int = DEFAULT_TIMEOUT,
) -> str:
    """同步调用 DeepSeek API，返回文本响应。

    使用 httpx 同步客户端，适合在 asyncio.to_thread() 中调用。
    """
    with httpx.Client(timeout=timeout) as client:
        response = client.post(
            f"{DEEPSEEK_API_BASE}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.7,
                "max_tokens": 4096,
            },
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]


async def call_deepseek(api_key: str, model: str, prompt: str) -> str:
    """异步调用 DeepSeek API（通过 asyncio.to_thread 包装同步调用）。"""
    return await asyncio.to_thread(call_deepseek_sync, api_key, model, prompt)


def make_call_generator(api_key: str, model: str) -> Callable[[str], str]:
    """创建供 lumora-cite generate_candidates 使用的 call_generator 可调用对象。

    lumora-cite 的 generate_candidates 签名：
        generate_candidates(*, title, text, purpose, call_generator, candidate_count)
    其中 call_generator(prompt: str) -> str 是同步函数。
    """
    def call_generator(prompt: str) -> str:
        return call_deepseek_sync(api_key, model, prompt)

    return call_generator
