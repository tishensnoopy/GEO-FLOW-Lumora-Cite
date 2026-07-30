# index-monitor/app/services/ai_index_checker.py
"""AI 收录检测服务：检测 AI 大模型是否收录了目标 URL。

收录检测在问题监测之前执行（双阶段管道 Phase 1）：
1. 对每个 URL × 模型组合，直接询问 AI 是否了解该 URL
2. 解析响应判定 indexed / not_indexed
3. 存入 ai_index_results 表

仅对 index_status='indexed' 的组合执行问题监测（Phase 2 改造）。
"""
# AI 回复中的否定短语——命中即判定 not_indexed
NEGATIVE_PHRASES = (
    "不了解", "不知道", "无法访问", "没有相关信息",
    "未收录", "不清楚", "不熟悉", "无法获取",
    "我没有关于", "我无法确认", "无法确认其内容",
)


def parse_index_response(response: str) -> str:
    """判定 AI 收录检测响应 → 'indexed' 或 'not_indexed'。

    判定规则：
    1. 空回复 → not_indexed
    2. 以"不了解"开头 → not_indexed
    3. 短回复（<50字）含否定短语 → not_indexed
    4. 长回复含"我没有关于"/"我无法确认" → not_indexed
    5. 其他（AI 提供了实质描述）→ indexed
    """
    text = (response or "").strip()
    if not text:
        return "not_indexed"
    if text.startswith("不了解"):
        return "not_indexed"
    # 短回复含否定短语
    if len(text) < 50 and any(p in text for p in NEGATIVE_PHRASES):
        return "not_indexed"
    # 长回复中的强否定短语
    strong_negatives = ("我没有关于", "我无法确认", "无法确认其内容")
    if any(p in text for p in strong_negatives):
        return "not_indexed"
    return "indexed"


def build_index_prompt(url: str) -> str:
    """构建 AI 收录检测 prompt。"""
    return (
        f"你是否了解这个网页的内容？请直接回答。\n\n"
        f"URL: {url}\n\n"
        f"如果你了解该网页的内容，请用 100 字以内简要描述其主要内容。\n"
        f"如果你不了解，请只回答\"不了解\"。"
    )
