# index-monitor/tests/test_fetcher.py
"""fetcher 模块的单元测试：重点验证非 ASCII URL 的百分号编码。"""
from app.services.citation_check.fetcher import _encode_url


class TestEncodeUrl:
    """_encode_url 应对 URL 路径/查询中的非 ASCII 字符做百分号编码。"""

    def test_ascii_url_unchanged(self):
        """纯 ASCII URL 应保持不变。"""
        url = "https://www.runoob.com/python3/python3-string.html"
        assert _encode_url(url) == url

    def test_chinese_path_encoded(self):
        """中文路径应被百分号编码。"""
        url = "https://zh.wikipedia.org/wiki/搜索引擎优化"
        encoded = _encode_url(url)
        # 编码后不应包含原始中文字符
        assert "搜索引擎优化" not in encoded
        # 应包含百分号编码序列（搜索 = %E6%90%9C%E7%B4%A2）
        assert "%E6%90%9C%E7%B4%A2" in encoded
        # scheme 和 host 保持不变
        assert encoded.startswith("https://zh.wikipedia.org/wiki/")

    def test_mixed_ascii_and_chinese(self):
        """混合 ASCII 和中文的路径应只编码非 ASCII 部分。"""
        url = "https://example.com/articles/2026/SEO优化指南"
        encoded = _encode_url(url)
        assert "example.com/articles/2026/SEO" in encoded
        assert "优化指南" not in encoded
        # 优 = %E4%BC%98
        assert "%E4%BC%98" in encoded

    def test_chinese_query_encoded(self):
        """中文查询参数应被百分号编码。"""
        url = "https://example.com/search?q=人工智能&page=1"
        encoded = _encode_url(url)
        assert "人工智能" not in encoded
        assert "page=1" in encoded
        # 人 = %E4%BA%BA
        assert "%E4%BA%BA" in encoded

    def test_preserves_safe_characters(self):
        """安全字符（/, =, &, %, #）应保留。"""
        url = "https://example.com/path/to/page?x=1&y=2#section"
        assert _encode_url(url) == url

    def test_already_encoded_url_not_double_encoded(self):
        """已百分号编码的 URL 不应被二次编码。"""
        url = "https://example.com/wiki/%E6%90%9C%E7%B4%A2"
        encoded = _encode_url(url)
        # 不应出现 %25（% 的编码），说明没有被二次编码
        assert "%25" not in encoded
        assert "%E6%90%9C%E7%B4%A2" in encoded
