"""providers.py 单元测试：验证 DeepSeek 已从引用检测模型列表移除。

设计规格第 2 节。覆盖目标：
- default_adapters() 不返回 deepseek 适配器
- adapter_catalog() 不列出 deepseek 项
- 其他 6 个适配器（豆包/千问/文心/OpenAI/Gemini/Claude）仍存在
- _PROVIDER_ENV_MAP 仍保留 ai_dashscope_api_key（千问依赖）
"""
import os

import pytest

from app.services.citation_check import providers


def test_adapter_catalog_excludes_deepseek():
    """adapter_catalog 不应再列出 deepseek 项。"""
    catalog = providers.adapter_catalog()
    ids = [item["id"] for item in catalog]
    assert "deepseek" not in ids, (
        "deepseek 应从 adapter_catalog 移除：DeepSeek 官方 API 不支持联网搜索，"
        "做引用检测模型先天不足"
    )


def test_adapter_catalog_keeps_other_six():
    """其他 6 个适配器应保留。"""
    catalog = providers.adapter_catalog()
    ids = {item["id"] for item in catalog}
    expected = {"doubao", "qwen", "ernie", "openai", "gemini", "claude"}
    assert expected.issubset(ids), f"应保留这 6 个适配器，缺失：{expected - ids}"


def test_default_adapters_excludes_deepseek(monkeypatch):
    """default_adapters() 不应构造 deepseek 适配器。"""
    monkeypatch.setenv("DASHSCOPE_API_KEY", "fake-dashscope")
    monkeypatch.setenv("ARK_API_KEY", "fake-ark")

    adapters = providers.default_adapters()
    provider_ids = {a.provider_id for a in adapters}
    assert "deepseek" not in provider_ids, "default_adapters 不应返回 deepseek 适配器"


def test_default_adapters_selected_ids_filters_deepseek(monkeypatch):
    """即使 selected_ids 显式包含 deepseek，也不应返回该适配器。"""
    monkeypatch.setenv("DASHSCOPE_API_KEY", "fake-dashscope")

    # 显式传入含 deepseek 的列表
    adapters = providers.default_adapters(["qwen", "deepseek"])
    provider_ids = {a.provider_id for a in adapters}
    assert "deepseek" not in provider_ids, (
        "selected_ids 含 deepseek 时应被静默忽略（已在 adapters 字典中删除）"
    )
    assert "qwen" in provider_ids, "其他有效 id 应正常返回"


def test_dashscope_env_mapping_preserved():
    """_PROVIDER_ENV_MAP 仍应保留 ai_dashscope_api_key → DASHSCOPE_API_KEY（千问依赖）。"""
    # citation_checker._PROVIDER_ENV_MAP 是从 providers 间接消费的环境变量约定
    # 这里通过设置 DASHSCOPE_API_KEY 验证千问适配器仍能读到 Key
    os.environ["DASHSCOPE_API_KEY"] = "preserved-check"
    try:
        adapters = providers.default_adapters(["qwen"])
        assert len(adapters) == 1
        assert adapters[0].api_key == "preserved-check", (
            "千问适配器应仍通过 DASHSCOPE_API_KEY 读取配置"
        )
    finally:
        del os.environ["DASHSCOPE_API_KEY"]
