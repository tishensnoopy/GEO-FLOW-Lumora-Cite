# index-monitor/tests/unit/test_domain_normalizer.py
"""domain 标准化测试：小写 + 去 www 前缀。设计文档第 7.1 节。"""
import pytest

from app.utils.validators import normalize_domain


def test_normalize_strips_www():
    assert normalize_domain("www.example.com") == "example.com"


def test_normalize_lowercase():
    assert normalize_domain("Example.COM") == "example.com"


def test_normalize_from_url():
    """从完整 URL 提取 domain。"""
    assert normalize_domain("https://www.example.com/path/page") == "example.com"
    assert normalize_domain("http://blog.example.com/post/1") == "blog.example.com"


def test_normalize_empty_url():
    assert normalize_domain("") == ""
    assert normalize_domain(None) == ""


def test_normalize_already_normalized():
    assert normalize_domain("example.com") == "example.com"
