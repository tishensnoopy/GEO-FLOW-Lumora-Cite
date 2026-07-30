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
import os
import time
from dataclasses import dataclass
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


# =========================================================================== #
# 阶段 2 - ⑥b：通用 provider 入口 + fallback                                   #
# --------------------------------------------------------------------------- #
# 解决痛点 6：Stage 2/3 强依赖 DeepSeek，DeepSeek 失效（限流/Key 过期/服务波动）
# 则采信检测全盘失败。新增通用 OpenAI 兼容 /chat/completions 入口，支持
# DeepSeek → 千问 → 豆包 顺序 fallback，任一可用即可继续检测。
# =========================================================================== #


@dataclass(frozen=True)
class LLMProvider:
    """问题生成用的 LLM provider（OpenAI 兼容 chat/completions）。

    Attributes
    ----------
    provider_id : str
        "deepseek" / "qwen" / "doubao"
    api_key : str
        API Key（非空时视为可用）
    model : str
        chat 模型名（如 deepseek-chat / qwen-plus / doubao-pro-32k）
    base_url : str
        OpenAI 兼容 base URL，调用时拼接 /chat/completions
    """

    provider_id: str
    api_key: str
    model: str
    base_url: str

    @property
    def is_available(self) -> bool:
        return bool(self.api_key)


# 问题生成 provider 定义（OpenAI 兼容 chat/completions）。
# 顺序即 fallback 顺序：DeepSeek → 千问 → 豆包。
# 元组：(provider_id, api_key_config_key, model_env, default_model, base_url)
# - DeepSeek 的 model 优先取 ai_question_model 配置（向后兼容），其余取环境变量或默认值
# - base_url 均为各家 OpenAI 兼容端点，调用时拼接 /chat/completions
_QUESTION_PROVIDER_DEFS = [
    (
        "deepseek",
        "ai_deepseek_api_key",
        "QUESTION_DEEPSEEK_MODEL",
        "deepseek-chat",
        "https://api.deepseek.com/v1",
    ),
    (
        "qwen",
        "ai_dashscope_api_key",
        "QUESTION_QWEN_MODEL",
        "qwen-plus",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
    ),
    (
        "doubao",
        "ai_ark_api_key",
        "QUESTION_DOUBAO_MODEL",
        "doubao-pro-32k",
        "https://ark.cn-beijing.volces.com/api/v3",
    ),
]


def build_question_providers(config: dict[str, str]) -> list[LLMProvider]:
    """从 AI 配置构建问题生成 provider 列表（按 fallback 顺序，跳过无 Key 的）。

    - DeepSeek 的 model 取 ``ai_question_model`` 配置（向后兼容旧部署），其余 provider
      的 model 取环境变量（如 ``QUESTION_QWEN_MODEL``）或默认值；
    - 无 API Key 的 provider 被跳过（未配置即不可用，不参与 fallback）。
    """
    providers: list[LLMProvider] = []
    for provider_id, key, model_env, default_model, base_url in _QUESTION_PROVIDER_DEFS:
        api_key = config.get(key, "")
        if not api_key:
            continue
        if provider_id == "deepseek":
            model = config.get("ai_question_model", "") or default_model
        else:
            model = os.getenv(model_env, default_model)
        providers.append(LLMProvider(provider_id, api_key, model, base_url))
    return providers


def _call_llm_sync(provider: LLMProvider, prompt: str, timeout: int = DEFAULT_TIMEOUT) -> str:
    """通用 OpenAI 兼容 ``/chat/completions`` 调用，复用 ``_call_with_retry``。

    返回 ``choices[0].message.content`` 文本。429/5xx 指数退避重试，4xx 立即抛出
    （由上层 ``call_llm_with_parse_retry_fallback`` 捕获后切换 provider）。
    """
    def do_post() -> str:
        with httpx.Client(timeout=timeout) as client:
            response = client.post(
                f"{provider.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {provider.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": provider.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": DEFAULT_TEMPERATURE,
                    "max_tokens": DEFAULT_MAX_TOKENS,
                },
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]

    return _call_with_retry(do_post, max_retries=2)


def call_llm_with_parse_retry_fallback(
    providers: list[LLMProvider],
    prompt: str,
    *,
    parser: Callable[[str], object],
    max_parse_retries: int = 2,
) -> str:
    """按顺序尝试 providers，调用/解析失败则换下一个 provider。

    流程（每个 provider）：
    1. 调用 ``_call_llm_sync`` 取响应文本（429/5xx 内部已退避重试，4xx 立即抛出）；
    2. 用 ``parser`` 解析；解析失败则追加"请严格只返回 JSON"提示重调，最多
       ``max_parse_retries`` 次；
    3. 调用或解析最终失败 → 记录 warning，切换下一个 provider。

    返回首个成功调用且解析通过的 raw text（供调用方二次解析，幂等）。
    全部 provider 都失败时抛最后一个异常；providers 为空时抛 RuntimeError。
    """
    if not providers:
        raise RuntimeError("无可用问题生成 provider（未配置任何 chat 模型 API Key）")

    last_exc: Exception | None = None
    for idx, provider in enumerate(providers):
        try:
            current_prompt = prompt
            for attempt in range(max_parse_retries + 1):
                text = _call_llm_sync(provider, current_prompt)
                try:
                    parser(text)
                    return text  # 解析通过，返回 raw text
                except (ValueError, KeyError, TypeError) as exc:
                    if attempt >= max_parse_retries:
                        logger.warning(
                            "provider %s 响应解析失败（已重试 %d 次），切换下一个 provider: %s",
                            provider.provider_id, attempt, exc,
                        )
                        raise  # 触发外层 except → fallback
                    logger.warning(
                        "provider %s 响应解析失败（第 %d 次），追加 JSON 提示重试",
                        provider.provider_id, attempt + 1,
                    )
                    current_prompt = prompt + "\n\n请严格只返回 JSON，不要任何解释文字。"
        except Exception as exc:  # noqa: BLE001 - 任何异常都尝试下一个 provider
            last_exc = exc
            logger.warning(
                "provider %s 不可用（第 %d/%d 个），尝试下一个: %s",
                provider.provider_id, idx + 1, len(providers), exc,
            )
            continue
    # 全部失败
    if last_exc:
        raise last_exc
    raise RuntimeError("无可用问题生成 provider")  # 理论上不会执行到


def make_fallback_parse_retry_generator(
    providers: list[LLMProvider],
    *,
    parser: Callable[[str], object],
    max_parse_retries: int = 2,
) -> Callable[[str], str]:
    """创建带 provider fallback + 解析重试的 call_generator，供 generate_candidates 使用。

    与 ``make_parse_retry_generator`` 契约一致：返回 ``call_generator(prompt) -> str``，
    内部完成"重调 LLM 直到可解析 + provider 间 fallback"，让 generate_candidates
    拿到的 raw text 一定是可解析的。
    """
    def call_generator(prompt: str) -> str:
        return call_llm_with_parse_retry_fallback(
            providers, prompt, parser=parser, max_parse_retries=max_parse_retries,
        )

    return call_generator


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
