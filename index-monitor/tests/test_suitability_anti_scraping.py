# index-monitor/tests/test_suitability_anti_scraping.py
"""反爬虫内容识别测试。

回归场景：lieju.com 等网站对爬虫返回 JS 反爬挑战页（var arg1='...' 加密内容），
而非真实文章 HTML。fetcher._extract_article 会把这段 JS 当正文提取，
evaluate_content_suitability 误判 suitable=True，导致反爬 JS 被传给问题生成器，
生成"网页上出现 var arg1 乱码是什么意思"等与文章完全无关的问题。

修复：evaluate_content_suitability 应识别反爬内容并返回 suitable=False，
阻止反爬内容进入问题生成流程。
"""
from app.services.citation_check.suitability import evaluate_content_suitability


class TestAntiScrapingDetection:
    """evaluate_content_suitability 应识别反爬虫 JS 加密内容并拒绝。"""

    def test_var_arg1_pattern_rejected(self):
        """含 `var arg1='...'` 反爬特征的文本应被拒绝。

        真实样例（lieju.com 反爬挑战页）：文本以 JSON 包裹的 var arg1 开头，
        后跟大量 base64/hex 编码字符串。
        """
        text = (
            '{"l1":"var arg1=\'5d4790f20ce89b9604a2633ced6b50e3b677500aba9d7cccad\';"} '
            "oHhbljdwUXHjoCxImhBkYzc4pn89Ean7KdwWYpzd78OK0urk/N0WRYH1ju+l3Oru6HkBWNWh6fjsv2Y3cg"
        )
        result = evaluate_content_suitability(title="", text=text)
        assert result.suitable is False
        assert result.rejection_code == "anti_scraping"

    def test_document_cookie_pattern_rejected(self):
        """含 document.cookie 反爬特征的文本应被拒绝。"""
        text = (
            "document.cookie = 'anti_spider=1; path=/'; "
            "window.location.reload(); "
            "eval(function(p,a,c,k,e,d){...}))"
        )
        result = evaluate_content_suitability(title="", text=text)
        assert result.suitable is False
        assert result.rejection_code == "anti_scraping"

    def test_low_readable_ratio_rejected(self):
        """可读文本比例极低（大量编码字符串）应被拒绝。

        无明显 JS 关键词，但前 300 字符几乎全是 base64/hex 编码，
        可读中文/英文比例低于 30%，视为反爬加密内容。
        """
        # 纯 base64 编码字符串，无可读中文/英文句子
        text = (
            "eHhbljdwUXHjoCxImhBkYzc4pn89Ean7KdwWYpzd78OK0urk/N0WRYH1ju+l3Oru6HkBWNWh6fjsv2Y3cg"
            "cDeFexewECfFK87/uM4Y/+clRU9bvw+ylfuHgBVi9W6tpC3QxV7mJkLpOqRsTuVwXyZ0aBcDfGhIjKlMn"
            "OpQrStUvWxYz0123456789+/abcDEF=="
        )
        result = evaluate_content_suitability(title="", text=text)
        assert result.suitable is False
        assert result.rejection_code == "anti_scraping"

    def test_normal_article_not_affected(self):
        """正常文章内容不应被误判为反爬内容。"""
        title = "2026 年国内主流 AI 搜索引擎对比测评"
        text = (
            "随着生成式 AI 的普及，AI 搜索引擎成为获取信息的重要入口。"
            "本文对比了 2026 年国内主流的 AI 搜索引擎，包括豆包、千问、文心一言等。"
            "我们从回答质量、引用来源、响应速度三个维度进行了测试。"
            "测试数据显示，豆包在引用准确率上达到 92%，千问在响应速度上领先。"
            "对于普通用户，选择 AI 搜索引擎时应考虑自身需求。"
            "如果重视答案可信度，建议选择引用来源清晰的引擎。"
        )
        result = evaluate_content_suitability(title=title, text=text)
        assert result.suitable is True

    def test_normal_short_article_not_affected(self):
        """正常短文章（含标题和少量正文）不应被误判。"""
        title = "Python 列表推导式入门"
        text = (
            "列表推导式是 Python 中创建列表的简洁语法。"
            "例如 [x*2 for x in range(10)] 可以快速生成 0 到 18 的偶数列表。"
            "它比传统的 for 循环更简洁，执行效率也更高。"
        )
        result = evaluate_content_suitability(title=title, text=text)
        # 正常短文应通过（或仅 warning），不应被标记为 anti_scraping
        assert result.rejection_code != "anti_scraping"
