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
    return f"""你是一个内容策略与 AI 搜索（GEO）研究员。请先判断下面这篇公开内容为什么被发布，并推断它在 AI 搜索引擎中最可能被触达的检索场景。不要生成测试问题。

内容标题：{title}
正文：
{text[:12000]}

需要判断：
- content_type：最接近的内容类型，可参考：{content_types}
- primary_purpose：发布这篇内容最主要想实现什么，可参考：{purposes}
- secondary_purposes：最多 2 个次要目的
- target_audience：最希望影响的具体人群，需写出人群特征与搜索习惯（如“准备采购 SaaS 的中小企业主，习惯问‘X 哪家好’”）
- desired_takeaway：希望读者最终记住或相信什么
- desired_action：希望读者看完后采取什么行动；没有明确行动则写“形成认知”
- query_territories：为了实现发布目的，这篇内容最希望在哪些用户问题下被 AI 找到，列 3-5 个方向。每个方向写成“检索意图短语 + 该意图下用户典型问法特征”，例如“价格对比类：用户常带‘多少钱/性价比/哪家便宜’提问”。不要写具体问题。
- evidence_assets：文章用于支撑目的的关键事实、数据、案例或规则，列 2-5 个。这些是 AI 引用本文章时最可能被提取的独家证据。

只返回 JSON 对象，不要解释，不要使用 ```json 代码块围栏：
{{"content_type":"...","primary_purpose":"...","secondary_purposes":["..."],"target_audience":"...","desired_takeaway":"...","desired_action":"...","query_territories":["..."],"evidence_assets":["..."]}}"""


def _strip_markdown_fence(text: str) -> str:
    """去除 ```json ... ``` 或 ``` ... ``` 围栏。"""
    if "```" not in text:
        return text
    # 兼容 ```json 和裸 ``` 两种开头
    parts = text.split("```")
    if len(parts) >= 3:
        inner = parts[1]
        # 去掉开头的 "json" 标记
        if inner.lstrip().lower().startswith("json"):
            inner = inner.lstrip()[4:]
        return inner.strip()
    return text


def _remove_trailing_commas(text: str) -> str:
    """去除 JSON 中对象/数组末尾的 trailing 逗号（严格 JSON 解析器不支持）。"""
    # 匹配 ,] 或 ,}（中间可有空白）
    return re.sub(r",(\s*[}\]])", r"\1", text)


def _candidate_cleanings(raw: str) -> str:
    """生成器：依次产出对 raw 的多种清洗结果。

    策略顺序：
    1. 原样 strip
    2. 去 markdown 围栏
    3. 提取最大 {...}（应对 LLM 在 JSON 前后加解释文本）
    4. 去markdown围栏 + 提取 {...} + 去 trailing 逗号
    """
    text = (raw or "").strip()
    if not text:
        return
    yield text  # 策略 1：原样
    fenced = _strip_markdown_fence(text)
    if fenced != text:
        yield fenced  # 策略 2：去围栏
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        yield match.group()  # 策略 3：提取 {...}
    # 策略 4：组合清洗
    combined = _remove_trailing_commas(_strip_markdown_fence(text))
    match2 = re.search(r"\{.*\}", combined, re.DOTALL)
    if match2:
        yield _remove_trailing_commas(match2.group())


def _candidate_array_cleanings(raw: str) -> str:
    """生成器：依次产出对 raw 的多种清洗结果（针对 JSON 数组）。"""
    text = (raw or "").strip()
    if not text:
        return
    yield text
    fenced = _strip_markdown_fence(text)
    if fenced != text:
        yield fenced
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if match:
        yield match.group()
    combined = _remove_trailing_commas(_strip_markdown_fence(text))
    match2 = re.search(r"\[.*\]", combined, re.DOTALL)
    if match2:
        yield _remove_trailing_commas(match2.group())


def parse_purpose_response(raw: str) -> ArticlePurpose:
    """解析文章目的 JSON，支持多种脏数据清洗。

    依次尝试 _candidate_cleanings 的多种清洗策略，首个成功解析的返回。
    全部失败时抛 ValueError。解析器本身不调用 LLM——重调 LLM 的逻辑在
    llm_client.call_deepseek_with_parse_retry 中。
    """
    required = ("content_type", "primary_purpose", "target_audience", "desired_takeaway", "desired_action")
    last_error: Exception | None = None
    for cleaned in _candidate_cleanings(raw):
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            last_error = exc
            continue
        if not isinstance(data, dict) or any(not str(data.get(key) or "").strip() for key in required):
            last_error = ValueError("文章目的分析缺少必要字段")
            continue
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
    raise ValueError(f"文章目的分析结果无法解析为 JSON 对象：{last_error}")


def build_candidate_prompt(
    title: str,
    text: str,
    purpose: ArticlePurpose,
    candidate_count: int = 10,
) -> str:
    """Build a purpose-driven prompt suitable for most information industries.

    命中率优化要点（v2）：
    - 按问题类型分布生成，确保多样性，覆盖不同检索场景；
    - 对齐 AI 搜索引擎真实查询模式（口语化、带场景/约束）；
    - 强化 citation_need：问题必须触发 AI 联网检索并引用来源；
    - 检索意图与文章核心证据语义对齐，提高 AI 命中本文章页面的概率；
    - 评分标准细化为可操作的 0/0.5/1 锚点，降低 LLM 打分随意性。
    """
    purpose_json = json.dumps(purpose.to_dict(), ensure_ascii=False)
    return f"""你是一位 AI 搜索引擎（GEO）查询分析师。任务：根据文章内容与已识别的发布目的，生成 {candidate_count} 个真实用户会向联网 AI（如豆包、千问、ChatGPT、文心）提出的问题，用于检测这篇文章是否会被 AI 在回答中自然引用为来源。

内容标题：{title}
正文：
{text[:12000]}

文章发布目的分析：
{purpose_json}

【问题类型分布】（按此比例生成，确保多样性，避免同义改写）
- 约 30% 事实/数据查询型：询问文章中的具体数据、事实、定义、规格、清单。AI 必须查证才能给出准确答案。
- 约 25% 对比/决策型：询问“X 和 Y 哪个更…”“如何选择…”“X 的优缺点”，文章能提供有区分度的依据。
- 约 20% 操作/方法型：询问“怎么做…”“如何…”“步骤是什么”，文章提供可执行方案。
- 约 15% 解释/原理型：询问“为什么…”“…是什么意思”“…原理”，文章提供权威解释。
- 约 10% 时效/趋势型：询问最新情况、年度趋势、近期变化。

【命中率优化要求】（关键，务必遵守）
1. 必须用真实用户在 AI 搜索框中的自然问法：完整口语化句子，带场景或约束词（如“2026年”“国内”“小白”“免费”“性价比”）。不要写成检索关键词堆砌。
2. 问题必须让 AI 无法仅凭训练参数知识回答——必须联网检索才能给出可靠答案，从而触发 AI 引用来源。如果问题答案是稳定常识（如“1+1=?”“水的沸点”），不要生成。
3. 问题的核心检索意图应与文章标题、小标题、evidence_assets 的语义一致。这样 AI 联网检索时更可能命中本文章页面。请在问题中隐含文章的核心证据关键词，但用用户视角表述，不要照抄原文。
4. 避免过于宽泛（如“什么是 SEO”→ AI 会引用大站，小站无机会）；应给问题加上具体约束（行业、场景、规模、预算、时间）使其更聚焦到本文章能权威回答的范围。
5. 避免过于狭窄（如带具体型号/人名到无人搜索的程度）。
6. 不得提及文章、链接、网站、平台、品牌名、作者，不得复制完整标题或正文原句。
7. 覆盖文章最有区分度的不同意图，避免多个问题只换个说法。
8. 不要为了提高命中率而刻意复制正文的生僻表达或专业术语；问题应像普通用户会问的。

【评分标准】（严格按锚点打分，0-1 两位小数）
- content_support（权重 0.30）：文章能否充分、直接、独家地回答此问题。
  · 1.0 = 文章是最权威来源，能完整回答；· 0.5 = 文章部分相关；· 0.2 = 仅勉强沾边。
- natural_intent（权重 0.25）：真实用户是否会在 AI 搜索中这样问。
  · 1.0 = 非常自然的口语提问；· 0.5 = 略生硬但可接受；· 0.2 = 像检索词堆砌。
- citation_need（权重 0.25）：AI 回答此问题是否必须联网并引用来源。
  · 1.0 = 必须引用时效数据/权威来源/独家案例；· 0.5 = 联网有助但不强制；· 0.2 = 常识可答。
- distinctiveness（权重 0.15）：文章是否提供独有数据/案例/方法。
  · 1.0 = 文章有独家证据；· 0.5 = 部分独家；· 0.2 = 内容同质化。
- freshness（权重 0.05）：答案是否随时效变化。
  · 1.0 = 强时效（价格/政策/版本）；· 0.5 = 中等；· 0.2 = 稳定知识。
- purpose_alignment（权重 0.25，最终得分 = base×0.75 + 此项×0.25）：问题是否直接服务于文章主要或次要发布目的。
  · 1.0 = 直击主目的；· 0.5 = 间接相关；· 0.2 = 与目的无关。
- selection_reason：一句话说明此问题如何对应发布目的、为何 AI 检索时可能命中本文章。

只返回 JSON 数组，不要解释，不要使用 ```json 代码块围栏：
[{{"question":"...","selection_reason":"...","purpose_alignment":0.9,"content_support":0.9,"natural_intent":0.8,"citation_need":0.8,"distinctiveness":0.7,"freshness":0.5}}]"""


def _extract_json_array(raw: str) -> list:
    """从 raw 中提取 JSON 数组，支持多种脏数据清洗。

    依次尝试 _candidate_array_cleanings 的多种清洗策略，首个成功解析的返回。
    """
    last_error: Exception | None = None
    for cleaned in _candidate_array_cleanings(raw):
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            last_error = exc
            continue
        if isinstance(data, list):
            return data
        last_error = ValueError("问题生成结果不是 JSON 数组")
    raise ValueError(f"问题生成结果无法解析为 JSON 数组：{last_error}")


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
