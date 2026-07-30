# index-monitor/tests/test_parse_index_response.py
"""parse_index_response 单元测试：验证 AI 收录检测响应判定逻辑。"""
from app.services.ai_index_checker import parse_index_response


class TestParseIndexResponse:
    """AI 回复 → indexed / not_indexed 判定。"""

    def test_short_negative_response(self):
        """短回复含否定短语 → not_indexed。"""
        assert parse_index_response("不了解") == "not_indexed"
        assert parse_index_response("不知道") == "not_indexed"
        assert parse_index_response("无法访问该网页") == "not_indexed"

    def test_starts_with_buliao_jie(self):
        """以'不了解'开头 → not_indexed（即使后面有内容）。"""
        assert parse_index_response("不了解该网页的内容，请提供更多信息") == "not_indexed"

    def test_substantive_description(self):
        """提供了实质描述 → indexed。"""
        response = (
            "该网页介绍了 XXX 公司最新发布的 YYY 产品，"
            "主要面向中小企业用户，核心功能包括自动化数据分析和可视化报表。"
        )
        assert parse_index_response(response) == "indexed"

    def test_long_negative_with_explanation(self):
        """长回复但明确否定 → not_indexed。"""
        response = "我没有关于该网页的相关信息，无法确认其内容。建议您直接访问该链接查看。"
        assert parse_index_response(response) == "not_indexed"

    def test_empty_response(self):
        """空回复 → not_indexed（AI 无内容可提供）。"""
        assert parse_index_response("") == "not_indexed"
        assert parse_index_response("   ") == "not_indexed"

    def test_generic_acknowledgment(self):
        """通用确认但无实质内容 → indexed（AI 声称了解）。"""
        response = "是的，我了解这个网页。它是一个关于产品介绍的页面。"
        assert parse_index_response(response) == "indexed"
