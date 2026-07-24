"""Cross-industry candidate question generation protocol."""

import json
import re
from dataclasses import asdict, dataclass
from typing import Callable

from .questions import QuestionCandidate


CONTENT_TYPES = (
    "产品选购/测评",
    "技术教程/方法指南",
    "行业研究/数据报告",
    "新闻/公告",
    "政策/规则解读",
    "案例复盘",
    "知识解释",
    "其他信息型内容",
)

PUBLISHING_PURPOSES = (
    "建立品牌或产品认知",
    "影响用户比较与购买决策",
    "发布新闻、版本或重要变更",
    "解释服务规则、政策或合规信息",
    "教育市场并建立方法认知",
    "用数据、案例或研究建立专业权威",
    "回应风险、误解或负面认知",
    "获取咨询、注册或销售线索",
    "提供操作指南或问题解决方案",
)


@dataclass(frozen=True)
class ArticlePurpose:
    content_type: str
    primary_purpose: str
    secondary_purposes: list[str]
    target_audience: str
    desired_takeaway: str
    desired_action: str
    query_territories: list[str]
    evidence_assets: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


def build_purpose_prompt(title: str, text: str) -> str:
    """Ask the generator to infer why the content was published."""
    content_types = "、".join(CONTENT_TYPES)
    purposes = "、".join(PUBLISHING_PURPOSES)
    return f"""你是一个内容策略研究员。请先判断下面这篇公开内容为什么被发布。不要生成测试问题。

内容标题：{title}
正文：
{text[:12000]}

需要判断：
- content_type：最接近的内容类型，可参考：{content_types}
- primary_purpose：发布这篇内容最主要想实现什么，可参考：{purposes}
- secondary_purposes：最多 2 个次要目的
- target_audience：最希望影响的具体人群
- desired_takeaway：希望读者最终记住或相信什么
- desired_action：希望读者看完后采取什么行动；没有明确行动则写“形成认知”
- query_territories：为了实现发布目的，这篇内容最希望在哪些用户问题下被 AI 找到，列 3-5 个方向，不要写具体问题
- evidence_assets：文章用于支撑目的的关键事实、数据、案例或规则，列 2-5 个

只返回 JSON 对象，不要解释：
{{"content_type":"...","primary_purpose":"...","secondary_purposes":["..."],"target_audience":"...","desired_takeaway":"...","desired_action":"...","query_territories":["..."],"evidence_assets":["..."]}}"""


def parse_purpose_response(raw: str) -> ArticlePurpose:
    cleaned = (raw or "").strip()
    if "```" in cleaned:
        cleaned = cleaned.split("```json")[-1].split("```")[0].strip()
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        raise ValueError("文章目的分析结果不包含 JSON 对象")
    data = json.loads(match.group())
    required = ("content_type", "primary_purpose", "target_audience", "desired_takeaway", "desired_action")
    if not isinstance(data, dict) or any(not str(data.get(key) or "").strip() for key in required):
        raise ValueError("文章目的分析缺少必要字段")
    return ArticlePurpose(
        content_type=str(data["content_type"]).strip(),
        primary_purpose=str(data["primary_purpose"]).strip(),
        secondary_purposes=[str(item).strip() for item in data.get("secondary_purposes", []) if str(item).strip()][:2],
        target_audience=str(data["target_audience"]).strip(),
        desired_takeaway=str(data["desired_takeaway"]).strip(),
        desired_action=str(data["desired_action"]).strip(),
        query_territories=[str(item).strip() for item in data.get("query_territories", []) if str(item).strip()][:5],
        evidence_assets=[str(item).strip() for item in data.get("evidence_assets", []) if str(item).strip()][:5],
    )


def build_candidate_prompt(
    title: str,
    text: str,
    purpose: ArticlePurpose,
    candidate_count: int = 10,
) -> str:
    """Build a purpose-driven prompt suitable for most information industries."""
    purpose_json = json.dumps(purpose.to_dict(), ensure_ascii=False)
    return f"""你是一个真实用户问题研究员。请根据文章内容和已经识别的发布目的，生成 {candidate_count} 个用户可能自然向联网 AI 提出的问题，供“该内容是否会被 AI 自然引用”的检测使用。

内容标题：{title}
正文：
{text[:12000]}

文章发布目的分析：
{purpose_json}

生成问题的核心目标：
- 检测这篇内容是否能在与其发布目的相关的真实用户问题中被 AI 找到和引用。
- 优先覆盖 primary_purpose、desired_takeaway 和 query_territories，而不是只挑文章能回答的零散细节。
- 大约 60% 候选问题服务于主要发布目的，20% 服务于次要目的，20% 检测文章最有区分度的证据资产。

严格要求：
1. 问题不能提到文章、链接、网站、平台、作者，也不能复制完整标题。
2. 问题必须是用户在不知道这篇内容存在时也可能自然提出的。
3. 文章必须能够充分回答问题；不要生成只与正文勉强相关的问题。
4. 优先生成 AI 回答时可能需要联网查证、引用来源的问题。
5. 覆盖文章最重要的不同意图，避免同义改写。
6. 不要为了提高引用命中率，刻意复制正文中的生僻表达。
7. 问题应当能帮助判断发布目的是否实现；与发布目的无关的细枝末节，即使文章能回答也不要生成。

为每个候选问题按 0-1 评分：
- content_support：文章是否能够充分直接回答
- natural_intent：真实用户是否可能自然提问
- citation_need：AI 回答时是否需要联网并引用来源
- distinctiveness：文章是否提供独有数据、案例、方法或具体事实
- freshness：时效信息是否影响答案
- purpose_alignment：问题是否直接服务于文章主要或次要发布目的

只返回 JSON 数组，不要解释：
[{{"question":"...","selection_reason":"说明问题如何对应发布目的","purpose_alignment":0.9,"content_support":0.9,"natural_intent":0.8,"citation_need":0.8,"distinctiveness":0.7,"freshness":0.5}}]"""


def _extract_json_array(raw: str) -> list:
    cleaned = (raw or "").strip()
    if "```" in cleaned:
        cleaned = cleaned.split("```json")[-1].split("```")[0].strip()
    match = re.search(r"\[.*\]", cleaned, re.DOTALL)
    if not match:
        raise ValueError("问题生成结果不包含 JSON 数组")
    data = json.loads(match.group())
    if not isinstance(data, list):
        raise ValueError("问题生成结果必须是 JSON 数组")
    return data


def parse_candidate_response(raw: str) -> list[QuestionCandidate]:
    """Parse valid candidates and discard malformed score objects."""
    candidates = []
    for item in _extract_json_array(raw):
        if not isinstance(item, dict) or not str(item.get("question") or "").strip():
            continue
        try:
            scores = {
                key: float(item[key])
                for key in (
                    "content_support",
                    "natural_intent",
                    "citation_need",
                    "distinctiveness",
                    "freshness",
                )
            }
        except (KeyError, TypeError, ValueError):
            continue
        if any(score < 0 or score > 1 for score in scores.values()):
            continue
        candidates.append(QuestionCandidate(
            question=str(item["question"]).strip(),
            selection_reason=str(item.get("selection_reason") or "").strip(),
            metadata={
                "raw": item,
                "purpose_alignment": float(item.get("purpose_alignment", 0)),
            },
            **scores,
        ))
    return candidates


def generate_candidates(
    *,
    title: str,
    text: str,
    purpose: ArticlePurpose,
    call_generator: Callable[[str], str],
    candidate_count: int = 10,
) -> list[QuestionCandidate]:
    """Generate candidates through an injected provider callable."""
    raw = call_generator(build_candidate_prompt(title, text, purpose, candidate_count))
    return parse_candidate_response(raw)
