# index-monitor/tests/unit/test_llm_client_fallback.py
"""llm_client provider fallback 测试（阶段 2 - ⑥b）。

验证目标：
1. build_question_providers：按 DeepSeek→千问→豆包 顺序构建，跳过无 Key 的
2. call_llm_with_parse_retry_fallback：首个 provider 调用失败 → 换下一个 → 成功
3. call_llm_with_parse_retry_fallback：全部失败 → 抛最后一个异常
4. call_llm_with_parse_retry_fallback：解析失败重试耗尽 → 换下一个 provider
5. make_fallback_parse_retry_generator：返回首个可用 provider 的可解析文本

这解决痛点 6：Stage 2/3 强依赖 DeepSeek，DeepSeek 失效则全盘失败。
"""
from unittest.mock import patch, MagicMock

import httpx
import pytest

from app.services.llm_client import (
    LLMProvider,
    build_question_providers,
    _call_llm_sync,
    call_llm_with_parse_retry_fallback,
    make_fallback_parse_retry_generator,
)


# --------------------------------------------------------------------------- #
# build_question_providers                                                     #
# --------------------------------------------------------------------------- #

def test_build_providers_skips_missing_keys():
    """无 API Key 的 provider 应被跳过。"""
    config = {
        "ai_deepseek_api_key": "ds-key",
        # ai_dashscope_api_key 缺失 → 千问被跳过
        "ai_ark_api_key": "ark-key",
        "ai_question_model": "deepseek-chat",
    }
    providers = build_question_providers(config)
    ids = [p.provider_id for p in providers]
    assert ids == ["deepseek", "doubao"], f"应跳过无 Key 的千问，实际 {ids}"


def test_build_providers_order_deepseek_qwen_doubao():
    """fallback 顺序应为 DeepSeek→千问→豆包。"""
    config = {
        "ai_deepseek_api_key": "ds-key",
        "ai_dashscope_api_key": "ds2-key",
        "ai_ark_api_key": "ark-key",
        "ai_question_model": "deepseek-chat",
    }
    providers = build_question_providers(config)
    ids = [p.provider_id for p in providers]
    assert ids == ["deepseek", "qwen", "doubao"]


def test_build_providers_deepseek_uses_question_model_config():
    """DeepSeek 的 model 应取 ai_question_model 配置（向后兼容）。"""
    config = {
        "ai_deepseek_api_key": "ds-key",
        "ai_question_model": "my-custom-deepseek-model",
    }
    providers = build_question_providers(config)
    deepseek = next(p for p in providers if p.provider_id == "deepseek")
    assert deepseek.model == "my-custom-deepseek-model"


def test_build_providers_empty_when_no_keys():
    """无任何 Key 时返回空列表。"""
    providers = build_question_providers({})
    assert providers == []


# --------------------------------------------------------------------------- #
# 辅助：构造 mock httpx 响应                                                   #
# --------------------------------------------------------------------------- #

def _mock_response(status_code: int, content: str = "") -> httpx.Response:
    """构造一个 httpx.Response mock。"""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = {
        "choices": [{"message": {"content": content}}]
    }
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=resp,
        )
    else:
        resp.raise_for_status.return_value = None
    return resp


def _patch_client_post(responses_by_url: dict):
    """patch httpx.Client，按 base_url 返回不同响应。

    responses_by_url: {base_url: response_or_list_of_responses}
    单个 response：每次调用返回同一个；
    list：按顺序返回（用于重试场景）。
    """
    call_log = []

    class FakeClient:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, **kw):
            call_log.append(url)
            # 匹配 base_url 前缀
            for base_url, resp in responses_by_url.items():
                if url.startswith(base_url):
                    if isinstance(resp, list):
                        return resp.pop(0)
                    return resp
            raise AssertionError(f"未 mock 的 URL: {url}")

    return patch("app.services.llm_client.httpx.Client", FakeClient), call_log


# --------------------------------------------------------------------------- #
# _call_llm_sync                                                              #
# --------------------------------------------------------------------------- #

def test_call_llm_sync_returns_content():
    """_call_llm_sync 应返回 OpenAI 兼容 chat 响应的 content。"""
    provider = LLMProvider(
        provider_id="deepseek", api_key="ds-key",
        model="deepseek-chat", base_url="https://api.deepseek.com/v1",
    )
    patcher, _ = _patch_client_post({
        "https://api.deepseek.com/v1": _mock_response(200, "hello world"),
    })
    with patcher:
        text = _call_llm_sync(provider, "test prompt")
    assert text == "hello world"


# --------------------------------------------------------------------------- #
# call_llm_with_parse_retry_fallback                                          #
# --------------------------------------------------------------------------- #

def _always_parse_ok(text):
    """解析器：始终通过。"""
    return {"parsed": text}


def test_fallback_first_provider_fails_second_succeeds():
    """首个 provider HTTP 失败 → 换第二个 → 成功返回其文本。

    场景：DeepSeek 401 → 千问 200。
    """
    deepseek = LLMProvider("deepseek", "ds-key", "deepseek-chat", "https://api.deepseek.com/v1")
    qwen = LLMProvider("qwen", "ds2-key", "qwen-plus", "https://dashscope.aliyuncs.com/compatible-mode/v1")

    patcher, call_log = _patch_client_post({
        "https://api.deepseek.com/v1": _mock_response(401),
        "https://dashscope.aliyuncs.com/compatible-mode/v1": _mock_response(200, "qwen answer"),
    })
    # 401 不重试（_is_retryable_http_error 只重试 429/5xx），直接 fallback
    with patcher:
        text = call_llm_with_parse_retry_fallback(
            [deepseek, qwen], "prompt", parser=_always_parse_ok,
        )
    assert text == "qwen answer"
    # 应该调用了 deepseek 和 qwen 两个 endpoint
    assert any("api.deepseek.com" in u for u in call_log)
    assert any("dashscope.aliyuncs.com" in u for u in call_log)


def test_fallback_all_providers_fail_raises_last():
    """所有 provider 都失败 → 抛最后一个异常。"""
    deepseek = LLMProvider("deepseek", "ds-key", "deepseek-chat", "https://api.deepseek.com/v1")
    qwen = LLMProvider("qwen", "ds2-key", "qwen-plus", "https://dashscope.aliyuncs.com/compatible-mode/v1")

    patcher, _ = _patch_client_post({
        "https://api.deepseek.com/v1": _mock_response(401),
        "https://dashscope.aliyuncs.com/compatible-mode/v1": _mock_response(403),
    })
    with patcher:
        with pytest.raises(httpx.HTTPStatusError):
            call_llm_with_parse_retry_fallback(
                [deepseek, qwen], "prompt", parser=_always_parse_ok,
            )


def test_fallback_parse_failure_triggers_next_provider():
    """首个 provider 调用成功但解析失败（重试耗尽）→ 换下一个 provider。

    场景：DeepSeek 返回非 JSON 文本（解析失败 2 次后放弃）→ 千问返回可解析文本。
    """
    deepseek = LLMProvider("deepseek", "ds-key", "deepseek-chat", "https://api.deepseek.com/v1")
    qwen = LLMProvider("qwen", "ds2-key", "qwen-plus", "https://dashscope.aliyuncs.com/compatible-mode/v1")

    def strict_parser(text):
        # 只接受含 "VALID:" 前缀的文本
        if not text.startswith("VALID:"):
            raise ValueError("无法解析")
        return text

    # DeepSeek 每次返回不可解析文本；千问返回可解析
    patcher, _ = _patch_client_post({
        "https://api.deepseek.com/v1": _mock_response(200, "garbage not json"),
        "https://dashscope.aliyuncs.com/compatible-mode/v1": _mock_response(200, "VALID:good"),
    })
    with patcher:
        text = call_llm_with_parse_retry_fallback(
            [deepseek, qwen], "prompt", parser=strict_parser, max_parse_retries=1,
        )
    assert text == "VALID:good"


def test_fallback_empty_providers_raises():
    """providers 为空时抛 RuntimeError。"""
    with pytest.raises(RuntimeError, match="无可用"):
        call_llm_with_parse_retry_fallback([], "prompt", parser=_always_parse_ok)


# --------------------------------------------------------------------------- #
# make_fallback_parse_retry_generator                                         #
# --------------------------------------------------------------------------- #

def test_make_fallback_generator_returns_parseable_text():
    """make_fallback_parse_retry_generator 返回的 call_generator 应返回可解析文本。"""
    deepseek = LLMProvider("deepseek", "ds-key", "deepseek-chat", "https://api.deepseek.com/v1")

    patcher, _ = _patch_client_post({
        "https://api.deepseek.com/v1": _mock_response(200, "answer"),
    })
    gen = make_fallback_parse_retry_generator([deepseek], parser=_always_parse_ok)
    with patcher:
        text = gen("prompt")
    assert text == "answer"
