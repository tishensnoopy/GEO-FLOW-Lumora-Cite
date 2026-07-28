"""engine.py 单元测试：探测结果 TTL 缓存。

设计规格第 3 节。覆盖目标：
- 首次探测调用底层 uncached 函数
- TTL 内第二次命中缓存，不再调底层
- force_refresh=True 跳过缓存
- invalidate_probe_cache() 清空全部
- invalidate_probe_cache(provider_id) 只清指定模型
- probe_adapter_capabilities 批量入口也走缓存
"""
import time
from unittest.mock import MagicMock, patch

import pytest

from app.services.citation_check import engine
from app.services.citation_check.engine import (
    ModelAnswer,
    probe_adapter_capability,
    probe_adapter_capabilities,
    invalidate_probe_cache,
    _PROBE_CACHE,
    _PROBE_CACHE_TTL,
    _cache_key,
)


class FakeAdapter:
    """模拟适配器，记录 ask 调用次数。"""
    capability = engine.VERIFIED_CITATIONS

    def __init__(self, provider_id, name="Fake", model_id="fake-1"):
        self.provider_id = provider_id
        self.name = name
        self.model_id = model_id
        self.ask_call_count = 0

    def ask(self, question):
        self.ask_call_count += 1
        return ModelAnswer(
            model=self.name,
            model_id=self.model_id,
            answer="Python 官网 https://www.python.org",
            sources=["https://www.python.org"],
            search_used=True,
            error=None,
        )


@pytest.fixture(autouse=True)
def reset_cache():
    """每个测试前后清空缓存，避免测试间污染。"""
    _PROBE_CACHE.clear()
    yield
    _PROBE_CACHE.clear()


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    """禁止重试时的真实 sleep，加速测试。"""
    monkeypatch.setattr("time.sleep", lambda _: None)


def test_cache_key_format():
    """缓存 key 应为 provider_id:model_id 格式。"""
    adapter = FakeAdapter("qwen", model_id="qwen3.6-plus")
    assert _cache_key(adapter) == "qwen:qwen3.6-plus"


def _make_probe_result(provider_id, status="verified"):
    """构造完整的探测结果 dict（与 _probe_adapter_capability_uncached 输出一致）。"""
    return {
        "provider_id": provider_id,
        "model": provider_id.title(),
        "model_id": "fake-1",
        "status": status,
        "web_search": status == "verified",
        "sources_returned": status == "verified",
        "sample_sources": [],
        "error": None,
    }


def test_first_probe_calls_underlying():
    """首次探测应调用底层 uncached 函数。"""
    adapter = FakeAdapter("qwen")
    with patch("app.services.citation_check.engine._probe_adapter_capability_uncached") as mock_uncached:
        mock_uncached.return_value = _make_probe_result("qwen")
        result = probe_adapter_capability(adapter)
        assert mock_uncached.call_count == 1
        assert result["status"] == "verified"


def test_second_probe_hits_cache():
    """TTL 内第二次探测应命中缓存，不再调底层。"""
    adapter = FakeAdapter("qwen")
    with patch("app.services.citation_check.engine._probe_adapter_capability_uncached") as mock_uncached:
        mock_uncached.return_value = _make_probe_result("qwen")
        probe_adapter_capability(adapter)
        probe_adapter_capability(adapter)
        probe_adapter_capability(adapter)
        assert mock_uncached.call_count == 1, "第二次/第三次应命中缓存，不调底层"


def test_force_refresh_skips_cache():
    """force_refresh=True 应跳过缓存重新探测。"""
    adapter = FakeAdapter("qwen")
    with patch("app.services.citation_check.engine._probe_adapter_capability_uncached") as mock_uncached:
        mock_uncached.return_value = _make_probe_result("qwen")
        probe_adapter_capability(adapter)
        probe_adapter_capability(adapter, force_refresh=True)
        assert mock_uncached.call_count == 2, "force_refresh 应重新调底层"


def test_invalidate_all():
    """invalidate_probe_cache() 无参清空全部。"""
    adapter1 = FakeAdapter("qwen")
    adapter2 = FakeAdapter("gemini")
    with patch("app.services.citation_check.engine._probe_adapter_capability_uncached") as mock_uncached:
        mock_uncached.side_effect = lambda a: _make_probe_result(a.provider_id)
        probe_adapter_capability(adapter1)
        probe_adapter_capability(adapter2)
        assert len(_PROBE_CACHE) == 2
        invalidate_probe_cache()
        assert len(_PROBE_CACHE) == 0
        # 清空后再次探测应重新调底层
        probe_adapter_capability(adapter1)
        assert mock_uncached.call_count == 3


def test_invalidate_by_provider_id():
    """invalidate_probe_cache(provider_id) 只清指定模型。"""
    adapter1 = FakeAdapter("qwen")
    adapter2 = FakeAdapter("gemini")
    with patch("app.services.citation_check.engine._probe_adapter_capability_uncached") as mock_uncached:
        mock_uncached.side_effect = lambda a: _make_probe_result(a.provider_id)
        probe_adapter_capability(adapter1)
        probe_adapter_capability(adapter2)
        invalidate_probe_cache("qwen")
        # qwen 缓存已清，gemini 仍在
        assert "qwen:fake-1" not in _PROBE_CACHE
        assert "gemini:fake-1" in _PROBE_CACHE
        # 再次探测 qwen 应调底层，gemini 应命中缓存
        probe_adapter_capability(adapter1)
        probe_adapter_capability(adapter2)
        assert mock_uncached.call_count == 3, "qwen 重新调底层（第3次），gemini 命中缓存"


def test_expired_cache_reprobes(monkeypatch):
    """缓存过期后应重新探测。"""
    adapter = FakeAdapter("qwen")
    base_time = [1000.0]
    monkeypatch.setattr("time.time", lambda: base_time[0])

    with patch("app.services.citation_check.engine._probe_adapter_capability_uncached") as mock_uncached:
        mock_uncached.return_value = _make_probe_result("qwen")
        probe_adapter_capability(adapter)
        # 时间推进超过 TTL
        base_time[0] += _PROBE_CACHE_TTL + 1
        probe_adapter_capability(adapter)
        assert mock_uncached.call_count == 2, "过期后应重新调底层"


def test_probe_adapter_capabilities_uses_cache():
    """批量入口 probe_adapter_capabilities 也应走缓存。"""
    adapters = [FakeAdapter("qwen"), FakeAdapter("gemini")]
    with patch("app.services.citation_check.engine._probe_adapter_capability_uncached") as mock_uncached:
        mock_uncached.side_effect = lambda a: _make_probe_result(a.provider_id)
        # 第一批：2 次底层调用
        probe_adapter_capabilities(adapters)
        assert mock_uncached.call_count == 2
        # 第二批相同适配器：应全部命中缓存
        probe_adapter_capabilities(adapters)
        assert mock_uncached.call_count == 2, "第二批应全部命中缓存"
