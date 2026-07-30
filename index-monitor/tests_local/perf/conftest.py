# index-monitor/tests/perf/conftest.py
"""性能测试共用配置。"""
import pytest


def pytest_configure(config):
    """注册自定义标记，消除 PytestUnknownMarkWarning。"""
    config.addinivalue_line(
        "markers",
        "perf: 性能测试——测量耗时/吞吐/并发度，用 mock 隔离外部依赖。",
    )
