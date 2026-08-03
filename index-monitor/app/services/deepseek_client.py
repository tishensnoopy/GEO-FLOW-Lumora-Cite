"""DeepSeek API 客户端（OpenAI 兼容接口）。

用于文章→关键词推断等非引用检测的 LLM 调用。
引用检测仍走 citation_check/providers.py 的 adapter 体系。
"""
import logging
import httpx

logger = logging.getLogger(__name__)

DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
DEEPSEEK_MODEL = "deepseek-v4-flash"
DEEPSEEK_TIMEOUT = 30.0


class DeepSeekError(Exception):
    """DeepSeek API 调用异常。"""


async def ask_deepseek(
    api_key: str,
    prompt: str,
    system_prompt: str = "你是 AI 助手",
    model: str = DEEPSEEK_MODEL,
    temperature: float = 0.3,
) -> str:
    """调用 DeepSeek chat completions，返回回答文本。

    Args:
        api_key: DeepSeek API Key（sk- 开头）
        prompt: 用户提示词
        system_prompt: 系统提示词
        model: 模型名，默认 deepseek-v4-flash
        temperature: 温度参数，推断场景用低温度（0.3）保证稳定性

    Returns:
        AI 回答文本

    Raises:
        DeepSeekError: API 调用失败时抛出
    """
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        "temperature": temperature,
    }

    try:
        async with httpx.AsyncClient(timeout=DEEPSEEK_TIMEOUT) as client:
            response = await client.post(
                DEEPSEEK_API_URL, headers=headers, json=payload
            )
            if response.status_code != 200:
                raise DeepSeekError(
                    f"DeepSeek API 错误 {response.status_code}: {response.text[:200]}"
                )
            data = response.json()
            return data["choices"][0]["message"]["content"]
    except httpx.RequestError as exc:
        raise DeepSeekError(f"DeepSeek 网络请求失败: {exc}") from exc
    except (KeyError, IndexError) as exc:
        raise DeepSeekError(f"DeepSeek 返回格式异常: {exc}") from exc
