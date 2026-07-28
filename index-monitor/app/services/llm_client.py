# index-monitor/app/services/llm_client.py
"""LLM 客户端：使用 DeepSeek OpenAI 兼容 API 进行问题生成和目的推断。

lumora-cite 的 generate_candidates / parse_purpose_response 需要一个同步的
call_generator(prompt) -> str 可调用对象。本模块封装 DeepSeek API 调用，
并提供 make_call_generator 工厂供 citation_checker 使用。

P1 修复（子项目 A）：
- DEFAULT_QUESTION_MODEL 从不存在的 deepseek-v4-flash 改为 deepseek-chat
- 新增 _call_with_retry：429/5xx 指数退避重试，4xx 立即抛出
- 新增 call_deepseek_with_parse_retry：调用成功但 JSON 解析失败时追加提示重调
- 新增 make_parse_retry_generator：包装 make_call_generator + 解析重试
"""
import asyncio
import logging
import time
from typing import Callable

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.system_config import SystemConfig

logger = logging.getLogger(__name__)

# DeepSeek OpenAI 兼容 API
DEEPSEEK_API_BASE = "https://api.deepseek.com/v1"
# 注意：deepseek-chat 是 DeepSeek 官方 API 实际支持的模型名（V3）。
# 此前用的 deepseek-v4-flash / deepseek-v4-pro 在官方 API 和 DashScope 上都不存在，
# 会导致 API 调用 400 失败，采信检测整体失灵。
DEFAULT_QUESTION_MODEL = "deepseek-chat"
DEFAULT_TIMEOUT = 120  # 秒，问题生成/目的推断可能较慢
DEFAULT_MAX_TOKENS = 8192  # 目的推断 + 10 个候选问题 JSON 容易超 4K
DEFAULT_TEMPERATURE = 0.3  # 结构化 JSON 输出更稳定


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


def _is_retryable_http_error(exc: httpx.HTTPStatusError) -> bool:
    """判断 HTTP 错误是否值得重试。

    重试：429（限流）、5xx（服务器临时错误）
    不重试：4xx 非 429（400 参数错误、401 认证失败、403 禁止访问等，重试无意义）
    """
    code = exc.response.status_code
    return code == 429 or code >= 500


def _call_with_retry(
    func: Callable,
    *args,
    max_retries: int = 2,
    base_delay: float = 1.0,
    retry_on: tuple = (httpx.HTTPStatusError, httpx.TimeoutException, httpx.TransportError),
    **kwargs,
):
    """通用重试包装：对可重试异常指数退避重试。

    - max_retries=2：1 次首调 + 2 次重试 = 最多 3 次调用
    - 指数退避：base_delay * (2 ** attempt)，第 0/1/2 次重试前等 1s/2s/4s
    - HTTPStatusError 仅对 429 和 5xx 重试，4xx 立即抛出
    """
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return func(*args, **kwargs)
        except retry_on as exc:
            last_exc = exc
            # HTTPStatusError 需进一步判断状态码
            if isinstance(exc, httpx.HTTPStatusError) and not _is_retryable_http_error(exc):
                raise
            if attempt >= max_retries:
                raise
            delay = base_delay * (2 ** attempt)
            logger.warning(
                "调用失败（第 %d 次），%s 秒后重试: %s",
                attempt + 1, delay, exc,
            )
            time.sleep(delay)
    raise last_exc  # 理论上不会执行到


def call_deepseek_sync(
    api_key: str,
    model: str,
    prompt: str,
    timeout: int = DEFAULT_TIMEOUT,
) -> str:
    """同步调用 DeepSeek API，返回文本响应。

    使用 httpx 同步客户端，适合在 asyncio.to_thread() 中调用。
    429/5xx 通过 _call_with_retry 指数退避重试（最多 3 次）。
    """
    def do_post() -> str:
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
                    "temperature": DEFAULT_TEMPERATURE,
                    "max_tokens": DEFAULT_MAX_TOKENS,
                },
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]

    return _call_with_retry(do_post, max_retries=2)


async def call_deepseek(api_key: str, model: str, prompt: str) -> str:
    """异步调用 DeepSeek API（通过 asyncio.to_thread 包装同步调用）。"""
    return await asyncio.to_thread(call_deepseek_sync, api_key, model, prompt)


def call_deepseek_with_parse_retry(
    api_key: str,
    model: str,
    prompt: str,
    *,
    parser: Callable[[str], object],
    max_parse_retries: int = 2,
    timeout: int = DEFAULT_TIMEOUT,
):
    """调用 DeepSeek 并在 JSON 解析失败时重试。

    - 首次用原 prompt 调用
    - 若 parser(text) 抛 ValueError，在 prompt 末尾追加"请严格只返回 JSON"重新调用
    - 最多 max_parse_retries 次解析重试（共 max_parse_retries + 1 次调用）
    - parser 无异常时直接返回 parser(text) 的结果
    """
    last_error: Exception | None = None
    current_prompt = prompt
    for attempt in range(max_parse_retries + 1):
        text = call_deepseek_sync(api_key, model, current_prompt, timeout=timeout)
        try:
            return parser(text)
        except (ValueError, KeyError, TypeError) as exc:
            last_error = exc
            if attempt >= max_parse_retries:
                logger.error(
                    "DeepSeek 响应解析失败（已重试 %d 次）: %s\n原始响应: %s",
                    attempt, exc, text[:500],
                )
                raise
            logger.warning(
                "DeepSeek 响应解析失败（第 %d 次），追加 JSON 提示重试: %s",
                attempt + 1, exc,
            )
            current_prompt = prompt + "\n\n请严格只返回 JSON，不要任何解释文字。"
    raise last_error  # 理论上不会执行到


def make_call_generator(api_key: str, model: str) -> Callable[[str], str]:
    """创建供 lumora-cite generate_candidates 使用的 call_generator 可调用对象。

    lumora-cite 的 generate_candidates 签名：
        generate_candidates(*, title, text, purpose, call_generator, candidate_count)
    其中 call_generator(prompt: str) -> str 是同步函数。
    """
    def call_generator(prompt: str) -> str:
        return call_deepseek_sync(api_key, model, prompt)

    return call_generator


def make_parse_retry_generator(
    api_key: str,
    model: str,
    *,
    parser: Callable[[str], object],
    max_parse_retries: int = 2,
) -> Callable[[str], str]:
    """创建带解析重试的 call_generator，供 generate_candidates 使用。

    包装 call_deepseek_sync + 解析重试，但仍返回 str（与 generate_candidates
    的契约一致）。内部逻辑：调用 → 尝试解析 → 失败则追加 JSON 提示重调 →
    返回最后一次成功解析的 raw text（让 generate_candidates 再解析一次，幂等）。

    generate_candidates 的契约是 call_generator(prompt) -> str，它自己再解析。
    本函数把"重调 LLM 直到可解析"的职责前移，让 generate_candidates 拿到的
    raw text 一定是可解析的——它的二次解析只是验证。
    """
    def call_generator(prompt: str) -> str:
        current_prompt = prompt
        last_error: Exception | None = None
        for attempt in range(max_parse_retries + 1):
            text = call_deepseek_sync(api_key, model, current_prompt)
            try:
                parser(text)
                return text  # 解析成功，返回 raw text 供 generate_candidates 二次解析
            except (ValueError, KeyError, TypeError) as exc:
                last_error = exc
                if attempt >= max_parse_retries:
                    logger.error(
                        "DeepSeek 响应解析失败（已重试 %d 次）: %s\n原始响应: %s",
                        attempt, exc, text[:500],
                    )
                    raise
                logger.warning(
                    "DeepSeek 响应解析失败（第 %d 次），追加 JSON 提示重试: %s",
                    attempt + 1, exc,
                )
                current_prompt = prompt + "\n\n请严格只返回 JSON，不要任何解释文字。"
        raise last_error  # 理论上不会执行到

    return call_generator
