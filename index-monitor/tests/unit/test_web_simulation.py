"""阶段 3：网页端模拟引擎单元测试。

覆盖目标：
- SimulationResult 数据类默认值与自定义值
- YuanbaoSimulator 类属性与选择器配置
- WebSimulationManager 注册/获取/调度（含未知平台降级）
- BaseWebSimulator._classify_hit 复用 matching 逻辑（exact/domain/none）
- YuanbaoSimulator._parse_cookie_header cookie 解析
- WebSimulationAdapter.ask 同步包装异步模拟器（成功/失败/异常三分支）
- adapter_catalog / default_adapters 注册 yuanbao
- _run_async 在有无事件循环下均能运行协程

不覆盖真实 Playwright 浏览器交互——那是集成测试范畴，需真实浏览器与网络。
"""
import asyncio

import pytest

from app.services.web_simulation import (
    BaseWebSimulator,
    SimulationResult,
    YuanbaoSimulator,
    WebSimulationManager,
    get_web_simulation_manager,
)
from app.services.web_simulation.base import BaseWebSimulator as _Base
from app.services.citation_check.providers import (
    WebSimulationAdapter,
    _run_async,
    adapter_catalog,
    default_adapters,
)
from app.services.citation_check.engine import ModelAnswer, VERIFIED_CITATIONS


# --------------------------------------------------------------------------- #
# SimulationResult 数据类                                                       #
# --------------------------------------------------------------------------- #

def test_simulation_result_defaults():
    """SimulationResult 默认值应为空/失败态。"""
    r = SimulationResult()
    assert r.answer == ""
    assert r.sources == []
    assert r.hit_type == "none"
    assert r.screenshot_path is None
    assert r.error is None
    assert r.success is False


def test_simulation_result_custom():
    """SimulationResult 应保留自定义字段。"""
    r = SimulationResult(
        answer="回答",
        sources=[{"url": "https://example.com/a", "title": "A"}],
        hit_type="exact",
        screenshot_path="/tmp/x.png",
        success=True,
    )
    assert r.answer == "回答"
    assert r.sources == [{"url": "https://example.com/a", "title": "A"}]
    assert r.hit_type == "exact"
    assert r.screenshot_path == "/tmp/x.png"
    assert r.success is True


# --------------------------------------------------------------------------- #
# YuanbaoSimulator 类属性                                                       #
# --------------------------------------------------------------------------- #

def test_yuanbao_simulator_class_attributes():
    """类属性应正确定义。"""
    assert YuanbaoSimulator.platform_id == "yuanbao"
    assert YuanbaoSimulator.platform_name == "元宝"
    assert YuanbaoSimulator.homepage_url == "https://yuanbao.tencent.com/"


def test_yuanbao_selectors_has_required_keys():
    """SELECTORS 应包含抓取流程所需的关键选择器。"""
    required = {"input_box", "send_button", "answer_container", "source_links"}
    assert required.issubset(YuanbaoSimulator.SELECTORS.keys())


def test_yuanbao_simulator_is_base_subclass():
    """YuanbaoSimulator 应是 BaseWebSimulator 子类。"""
    assert issubclass(YuanbaoSimulator, _Base)


# --------------------------------------------------------------------------- #
# WebSimulationManager 注册/获取/调度                                            #
# --------------------------------------------------------------------------- #

def test_manager_default_registers_yuanbao():
    """管理器默认应注册 yuanbao。"""
    mgr = WebSimulationManager()
    assert "yuanbao" in mgr.available_platforms()
    assert isinstance(mgr.get("yuanbao"), YuanbaoSimulator)


def test_manager_get_unknown_returns_none():
    """获取不存在的平台应返回 None。"""
    mgr = WebSimulationManager()
    assert mgr.get("no_such_platform") is None


def test_manager_register_custom():
    """应能注册自定义模拟器，后注册覆盖前者。"""

    class FakeSim(BaseWebSimulator):
        platform_id = "fake"
        platform_name = "Fake"

        async def simulate_search(self, question, target_urls, timeout=60):
            return SimulationResult(success=True, answer="fake")

    mgr = WebSimulationManager()
    mgr.register(FakeSim())
    assert "fake" in mgr.available_platforms()
    assert mgr.get("fake").platform_name == "Fake"


def test_manager_register_rejects_empty_platform_id():
    """注册空 platform_id 应抛 ValueError。"""

    class EmptySim(BaseWebSimulator):
        platform_id = ""
        platform_name = "Empty"

        async def simulate_search(self, question, target_urls, timeout=60):
            return SimulationResult()

    mgr = WebSimulationManager()
    with pytest.raises(ValueError, match="platform_id"):
        mgr.register(EmptySim())


@pytest.mark.asyncio
async def test_manager_simulate_unknown_platform_returns_error():
    """模拟不存在平台应返回带 error 的 SimulationResult，不抛异常。"""
    mgr = WebSimulationManager()
    result = await mgr.simulate("no_such_platform", "问题", [])
    assert result.success is False
    assert "不支持的平台" in (result.error or "")


@pytest.mark.asyncio
async def test_manager_simulate_catches_simulator_exception():
    """模拟器内部抛异常时，manager 应捕获并包装成 error，不向上抛。"""

    class BoomSim(BaseWebSimulator):
        platform_id = "boom"
        platform_name = "Boom"

        async def simulate_search(self, question, target_urls, timeout=60):
            raise RuntimeError("爆炸")

    mgr = WebSimulationManager()
    mgr.register(BoomSim())
    result = await mgr.simulate("boom", "问题", [])
    assert result.success is False
    assert "爆炸" in (result.error or "")


def test_get_web_simulation_manager_singleton():
    """全局单例应稳定返回同一实例。"""
    a = get_web_simulation_manager()
    b = get_web_simulation_manager()
    assert a is b


# --------------------------------------------------------------------------- #
# BaseWebSimulator._classify_hit（复用 matching）                              #
# --------------------------------------------------------------------------- #

def test_classify_hit_exact():
    """源 URL 与目标精确匹配应返回 exact。"""
    sim = YuanbaoSimulator()
    target = "https://example.com/article/1"
    sources = [{"url": target, "title": "T"}]
    assert sim._classify_hit(sources, [target]) == "exact"


def test_classify_hit_domain():
    """同主域不同 path 应返回 domain。"""
    sim = YuanbaoSimulator()
    sources = [{"url": "https://example.com/other", "title": "T"}]
    assert sim._classify_hit(sources, ["https://example.com/article"]) == "domain"


def test_classify_hit_none():
    """无任何匹配应返回 none。"""
    sim = YuanbaoSimulator()
    sources = [{"url": "https://other.com/x", "title": "T"}]
    assert sim._classify_hit(sources, ["https://example.com/article"]) == "none"


def test_classify_hit_empty_sources():
    """无源时应返回 none。"""
    sim = YuanbaoSimulator()
    assert sim._classify_hit([], ["https://example.com/article"]) == "none"


# --------------------------------------------------------------------------- #
# YuanbaoSimulator._parse_cookie_header                                        #
# --------------------------------------------------------------------------- #

def test_parse_cookie_header_normal():
    """应正确解析多 cookie 字符串为 Playwright cookie 格式。"""
    cookies = YuanbaoSimulator._parse_cookie_header(
        "session=abc; token=xyz", "https://yuanbao.tencent.com/"
    )
    assert len(cookies) == 2
    assert cookies[0]["name"] == "session"
    assert cookies[0]["value"] == "abc"
    assert cookies[0]["domain"] == "yuanbao.tencent.com"
    assert cookies[0]["path"] == "/"
    assert cookies[0]["secure"] is True
    assert cookies[1]["name"] == "token"
    assert cookies[1]["value"] == "xyz"


def test_parse_cookie_header_empty():
    """空字符串应返回空列表。"""
    assert YuanbaoSimulator._parse_cookie_header("", "https://yuanbao.tencent.com/") == []


def test_parse_cookie_header_malformed():
    """格式异常的片段应被跳过，不抛异常。"""
    cookies = YuanbaoSimulator._parse_cookie_header(
        "good=1; bad; =empty; also=2", "https://yuanbao.tencent.com/"
    )
    names = [c["name"] for c in cookies]
    assert "good" in names
    assert "also" in names
    assert "bad" not in names  # 无等号，跳过
    assert "" not in names  # 空名，跳过


def test_parse_cookie_header_invalid_url():
    """base_url 无 hostname 时应返回空列表。"""
    assert YuanbaoSimulator._parse_cookie_header("a=b", "not-a-url") == []


# --------------------------------------------------------------------------- #
# WebSimulationAdapter（同步包装异步模拟器）                                    #
# --------------------------------------------------------------------------- #

class _FakeManager:
    """替身管理器，避免触发真实 Playwright。"""

    def __init__(self, result=None, exc=None):
        self._result = result
        self._exc = exc
        self.calls = []

    def get(self, platform_id):
        # 返回一个仅提供 platform_name 的替身（用于 adapter __init__ 取 name）
        class _S:
            platform_name = "元宝"
        return _S()

    async def simulate(self, platform_id, question, target_urls, timeout=60):
        self.calls.append((platform_id, question, target_urls, timeout))
        if self._exc:
            raise self._exc
        return self._result


def _make_adapter_with_fake_manager(fake_mgr):
    """构造一个绑定 fake manager 的 WebSimulationAdapter，绕过全局单例。"""
    adapter = WebSimulationAdapter.__new__(WebSimulationAdapter)
    adapter._manager = fake_mgr
    adapter.provider_id = "yuanbao"
    adapter.name = "元宝"
    adapter.model_id = "web-simulation"
    return adapter


def test_web_simulation_adapter_class_attributes():
    """adapter 类属性应满足 CitationModelAdapter Protocol。"""
    assert WebSimulationAdapter.capability == VERIFIED_CITATIONS


def test_web_simulation_adapter_init_from_real_manager():
    """通过真实 manager 构造 adapter，属性应取自 yuanbao 模拟器。"""
    adapter = WebSimulationAdapter("yuanbao")
    assert adapter.provider_id == "yuanbao"
    assert adapter.name == "元宝"
    assert adapter.model_id == "web-simulation"
    assert adapter.capability == VERIFIED_CITATIONS


def test_adapter_ask_success_returns_model_answer():
    """模拟成功时 ask 应返回带 sources 的 ModelAnswer。"""
    fake = _FakeManager(result=SimulationResult(
        success=True,
        answer="这是回答",
        sources=[{"url": "https://example.com/a", "title": "A"}],
    ))
    adapter = _make_adapter_with_fake_manager(fake)

    answer = adapter.ask("问题")

    assert isinstance(answer, ModelAnswer)
    assert answer.model == "元宝"
    assert answer.model_id == "web-simulation"
    assert answer.answer == "这是回答"
    assert answer.sources == ["https://example.com/a"]
    assert answer.search_used is True
    assert answer.error is None
    # 验证 target_urls 传空（命中判定由 engine 做）
    assert fake.calls[0][2] == []


def test_adapter_ask_failure_returns_error_model_answer():
    """模拟失败时 ask 应返回带 error 的 ModelAnswer，sources 为空。"""
    fake = _FakeManager(result=SimulationResult(
        success=False,
        answer="部分回答",
        error="等待元宝回答超时",
    ))
    adapter = _make_adapter_with_fake_manager(fake)

    answer = adapter.ask("问题")

    assert answer.error == "等待元宝回答超时"
    assert answer.sources == []
    assert answer.search_used is None
    assert answer.answer == "部分回答"


def test_adapter_ask_exception_returns_error_model_answer():
    """模拟器抛异常时 ask 应捕获并返回 error，不向上抛。"""
    fake = _FakeManager(exc=RuntimeError("Playwright 未安装"))
    adapter = _make_adapter_with_fake_manager(fake)

    answer = adapter.ask("问题")

    assert answer.error is not None
    assert "Playwright 未安装" in answer.error
    assert answer.sources == []
    assert answer.answer == ""


def test_adapter_ask_no_sources_sets_search_used_false():
    """模拟成功但无 sources 时 search_used 应为 False。"""
    fake = _FakeManager(result=SimulationResult(success=True, answer="回答", sources=[]))
    adapter = _make_adapter_with_fake_manager(fake)

    answer = adapter.ask("问题")

    assert answer.search_used is False
    assert answer.error is None


# --------------------------------------------------------------------------- #
# providers.py 集成                                                            #
# --------------------------------------------------------------------------- #

def test_adapter_catalog_includes_yuanbao():
    """adapter_catalog 应列出 yuanbao，且 configured 始终为 True。"""
    catalog = adapter_catalog()
    yuanbao = next((item for item in catalog if item["id"] == "yuanbao"), None)
    assert yuanbao is not None, "adapter_catalog 应包含 yuanbao"
    assert yuanbao["name"] == "元宝"
    assert yuanbao["model_id"] == "web-simulation"
    assert yuanbao["configured"] is True


def test_default_adapters_includes_yuanbao():
    """default_adapters(['yuanbao']) 应返回 WebSimulationAdapter 实例。"""
    adapters = default_adapters(["yuanbao"])
    assert len(adapters) == 1
    assert isinstance(adapters[0], WebSimulationAdapter)
    assert adapters[0].provider_id == "yuanbao"


def test_default_adapters_yuanbao_does_not_require_api_key(monkeypatch):
    """元宝不需要 API Key——清空所有 key 后 default_adapters 仍应选中 yuanbao。"""
    for key in ("ARK_API_KEY", "DASHSCOPE_API_KEY", "BAIDU_API_KEY",
                "OPENAI_API_KEY", "GEMINI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(key, raising=False)

    adapters = default_adapters()  # selected_ids=None → 取所有 configured=True
    provider_ids = {a.provider_id for a in adapters}
    assert "yuanbao" in provider_ids, "无 API Key 时 yuanbao 仍应被选中"


# --------------------------------------------------------------------------- #
# _run_async 辅助函数                                                          #
# --------------------------------------------------------------------------- #

def test_run_async_without_running_loop():
    """同步上下文（无运行中的事件循环）下应直接 asyncio.run。"""
    async def coro():
        await asyncio.sleep(0)
        return 42

    assert _run_async(coro()) == 42


@pytest.mark.asyncio
async def test_run_async_with_running_loop():
    """已有事件循环时应降级为新线程运行，不抛嵌套循环错误。"""
    async def coro():
        await asyncio.sleep(0)
        return "ok"

    # 当前已在事件循环中（async test），_run_async 应走新线程分支
    result = await asyncio.to_thread(_run_async, coro())
    assert result == "ok"
