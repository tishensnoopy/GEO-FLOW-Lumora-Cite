"""llm_client.py 单元测试：模型名修正 + 步骤级重试 + JSON 解析重试。

设计规格第 1 节。覆盖目标：
- DEFAULT_QUESTION_MODEL 为 deepseek-chat（不是不存在的 deepseek-v4-flash）
- 429 限流时重试，指数退避
- 5xx 错误时重试
- 4xx（非 429）立即抛出不重试
- 调用成功但 JSON 解析失败时，追加提示重新调用
- make_parse_retry_generator 包装原 make_call_generator + 解析重试
"""
import json
from unittest.mock import MagicMock, patch, call

import httpx
import pytest

from app.services import llm_client
from app.services.llm_client import (
    DEFAULT_QUESTION_MODEL,
    DEFAULT_TIMEOUT,
    call_deepseek_sync,
    call_deepseek_with_parse_retry,
    make_call_generator,
    make_parse_retry_generator,
    _call_with_retry,
)


# --------------------------------------------------------------------------- #
# 模型名修正                                                                   #
# --------------------------------------------------------------------------- #

def test_default_question_model_is_deepseek_chat():
    """DEFAULT_QUESTION_MODEL 应为 deepseek-chat（DeepSeek 官方实际支持的模型名）。

    deepseek-v4-flash / deepseek-v4-pro 等模型名在 DeepSeek 官方 API 和
    阿里云 DashScope 上都不存在，会导致 API 调用 400 失败。
    """
    assert DEFAULT_QUESTION_MODEL == "deepseek-chat", (
        "DeepSeek 官方 API 实际支持 deepseek-chat（V3）和 deepseek-reasoner（R1），"
        "deepseek-v4-flash 等模型名不存在"
    )


# --------------------------------------------------------------------------- #
# _call_with_retry 重试逻辑                                                    #
# --------------------------------------------------------------------------- #

@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    """禁止真实 sleep，加速测试。"""
    monkeypatch.setattr("time.sleep", lambda _: None)


def _make_http_status_error(code):
    """构造 httpx.HTTPStatusError。"""
    request = httpx.Request("POST", "https://api.deepseek.com/v1/chat/completions")
    response = httpx.Response(code, request=request)
    return httpx.HTTPStatusError(f"HTTP {code}", request=request, response=response)


def test_retry_on_429():
    """429 限流应触发重试。"""
    mock_call = MagicMock(side_effect=_make_http_status_error(429))
    with pytest.raises(httpx.HTTPStatusError):
        _call_with_retry(mock_call, max_retries=2)
    assert mock_call.call_count == 3, "1 次首调 + 2 次重试 = 3 次"


def test_retry_on_5xx():
    """5xx 服务器错误应触发重试。"""
    mock_call = MagicMock(side_effect=_make_http_status_error(503))
    with pytest.raises(httpx.HTTPStatusError):
        _call_with_retry(mock_call, max_retries=2)
    assert mock_call.call_count == 3


def test_no_retry_on_4xx_non_429():
    """4xx（非 429）应立即抛出不重试（重试无意义）。"""
    mock_call = MagicMock(side_effect=_make_http_status_error(400))
    with pytest.raises(httpx.HTTPStatusError):
        _call_with_retry(mock_call, max_retries=2)
    assert mock_call.call_count == 1, "400 应立即抛出不重试"


def test_no_retry_on_401():
    """401 认证失败应立即抛出不重试。"""
    mock_call = MagicMock(side_effect=_make_http_status_error(401))
    with pytest.raises(httpx.HTTPStatusError):
        _call_with_retry(mock_call, max_retries=2)
    assert mock_call.call_count == 1


def test_no_retry_on_success():
    """成功调用不重试。"""
    mock_call = MagicMock(return_value="ok")
    result = _call_with_retry(mock_call, max_retries=2)
    assert result == "ok"
    assert mock_call.call_count == 1


def test_retry_then_success():
    """前几次失败后成功，应停止重试。"""
    mock_call = MagicMock(side_effect=[
        _make_http_status_error(429),
        _make_http_status_error(503),
        "finally ok",
    ])
    result = _call_with_retry(mock_call, max_retries=3)
    assert result == "finally ok"
    assert mock_call.call_count == 3


def test_timeout_exception_retries():
    """超时异常应触发重试。"""
    mock_call = MagicMock(side_effect=httpx.TimeoutException("timeout"))
    with pytest.raises(httpx.TimeoutException):
        _call_with_retry(mock_call, max_retries=1)
    assert mock_call.call_count == 2


# --------------------------------------------------------------------------- #
# call_deepseek_sync 集成 _call_with_retry                                     #
# --------------------------------------------------------------------------- #

def test_call_deepseek_sync_uses_retry(monkeypatch):
    """call_deepseek_sync 应通过 _call_with_retry 调用，429 时重试。"""
    call_count = [0]

    def transport_handler(request):
        call_count[0] += 1
        if call_count[0] < 3:
            return httpx.Response(429, text="rate limited")
        return httpx.Response(200, json={"choices": [{"message": {"content": "hello"}}]})

    transport = httpx.MockTransport(transport_handler)
    original_client = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: original_client(transport=transport, **kw))

    result = call_deepseek_sync("fake-key", "deepseek-chat", "test prompt")
    assert result == "hello"
    assert call_count[0] == 3, "前 2 次 429 + 第 3 次成功"


def test_call_deepseek_sync_temperature_is_03(monkeypatch):
    """temperature 应为 0.3（结构化 JSON 输出更稳定）。"""
    captured_payload = {}

    def transport_handler(request):
        captured_payload.update(json.loads(request.content.decode("utf-8")))
        return httpx.Response(200, json={"choices": [{"message": {"content": "x"}}]})

    transport = httpx.MockTransport(transport_handler)
    original_client = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: original_client(transport=transport, **kw))

    call_deepseek_sync("fake-key", "deepseek-chat", "prompt")
    assert captured_payload.get("temperature") == 0.3, (
        "结构化 JSON 输出应用低 temperature，原 0.7 偏高易产出解析失败的脏数据"
    )


def test_call_deepseek_sync_max_tokens_is_8192(monkeypatch):
    """max_tokens 应为 8192（目的推断 + 10 个候选问题 JSON 容易超 4K）。"""
    captured_payload = {}

    def transport_handler(request):
        captured_payload.update(json.loads(request.content.decode("utf-8")))
        return httpx.Response(200, json={"choices": [{"message": {"content": "x"}}]})

    transport = httpx.MockTransport(transport_handler)
    original_client = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: original_client(transport=transport, **kw))

    call_deepseek_sync("fake-key", "deepseek-chat", "prompt")
    assert captured_payload.get("max_tokens") == 8192


# --------------------------------------------------------------------------- #
# call_deepseek_with_parse_retry 解析重试                                       #
# --------------------------------------------------------------------------- #

def test_parse_retry_on_value_error(monkeypatch):
    """调用成功但 parser 抛 ValueError 时，应追加提示重新调用。"""
    call_count = [0]
    captured_prompts = []

    def mock_sync(api_key, model, prompt, timeout=None):
        call_count[0] += 1
        captured_prompts.append(prompt)
        if call_count[0] == 1:
            return "这不是 JSON"  # parser 会抛 ValueError
        return '{"content_type":"x","primary_purpose":"y","target_audience":"z","desired_takeaway":"a","desired_action":"b"}'

    monkeypatch.setattr(llm_client, "call_deepseek_sync", mock_sync)

    def parser(text):
        from app.services.citation_check.question_generation import parse_purpose_response
        return parse_purpose_response(text)

    result = call_deepseek_with_parse_retry("fake-key", "deepseek-chat", "原 prompt", parser=parser)
    assert call_count[0] == 2, "首次解析失败应触发 1 次重试"
    assert "请严格只返回 JSON" in captured_prompts[1], "重试 prompt 应追加 JSON 提示"


def test_parse_retry_max_attempts(monkeypatch):
    """解析重试应最多 2 次（共 3 次调用）。"""
    call_count = [0]

    def mock_sync(api_key, model, prompt, timeout=None):
        call_count[0] += 1
        return "始终不是 JSON"

    monkeypatch.setattr(llm_client, "call_deepseek_sync", mock_sync)

    def parser(text):
        raise ValueError("解析失败")

    with pytest.raises(ValueError):
        call_deepseek_with_parse_retry("fake-key", "deepseek-chat", "prompt", parser=parser, max_parse_retries=2)
    assert call_count[0] == 3, "1 次首调 + 2 次解析重试 = 3 次"


def test_parse_no_retry_on_success(monkeypatch):
    """解析成功不重试。"""
    call_count = [0]

    def mock_sync(api_key, model, prompt, timeout=None):
        call_count[0] += 1
        return '{"valid":"json"}'

    monkeypatch.setattr(llm_client, "call_deepseek_sync", mock_sync)

    def parser(text):
        return {"parsed": True}

    result = call_deepseek_with_parse_retry("fake-key", "deepseek-chat", "prompt", parser=parser)
    assert result == {"parsed": True}
    assert call_count[0] == 1


# --------------------------------------------------------------------------- #
# make_parse_retry_generator                                                    #
# --------------------------------------------------------------------------- #

def test_make_parse_retry_generator_wraps_call_generator(monkeypatch):
    """make_parse_retry_generator 应包装 make_call_generator 并加解析重试。

    契约：返回 raw text（str）供 generate_candidates 二次解析，但内部保证
    返回的 text 一定是 parser 能成功解析的——失败时会重调 LLM。
    """
    call_count = [0]
    valid_json = '[{"question":"Q1","selection_reason":"r","content_support":0.9,"natural_intent":0.8,"citation_need":0.7,"distinctiveness":0.6,"freshness":0.5}]'

    def mock_sync(api_key, model, prompt, timeout=None):
        call_count[0] += 1
        if call_count[0] == 1:
            return "脏数据"  # 首次返回无法解析的脏数据
        return valid_json  # 重试返回可解析的 JSON

    monkeypatch.setattr(llm_client, "call_deepseek_sync", mock_sync)

    from app.services.citation_check.question_generation import parse_candidate_response
    gen = make_parse_retry_generator("fake-key", "deepseek-chat", parser=parse_candidate_response)
    raw_text = gen("原 prompt")
    # 返回的应是可解析的 raw text（str），不是解析后的对象
    assert isinstance(raw_text, str)
    assert call_count[0] == 2, "首次解析失败应触发重试"
    # 验证返回的 raw text 确实可被 parser 解析
    candidates = parse_candidate_response(raw_text)
    assert len(candidates) == 1
    assert candidates[0].question == "Q1"
