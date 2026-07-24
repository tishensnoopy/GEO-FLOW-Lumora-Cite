"""Markdown report generation for local citation checks."""

from datetime import datetime
from zoneinfo import ZoneInfo


def markdown_filename(now: datetime | None = None) -> str:
    current = now or datetime.now(ZoneInfo("Asia/Shanghai"))
    return f"lumora-cite-report-{current.strftime('%Y%m%d-%H%M')}.md"


def _pct(value) -> str:
    return "-" if value is None else f"{value * 100:.1f}%"


def _cell(value) -> str:
    return str(value or "-").replace("|", "\\|").replace("\n", " ")


def render_markdown_report(data: dict) -> str:
    target = data.get("target") or {}
    summary = data.get("summary") or {}
    capabilities = data.get("provider_capabilities") or []
    lines = [
        "# Lumora Cite 检测报告",
        "",
        f"- 生成时间（北京时间）：{datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 内容标题：{target.get('title') or '未识别'}",
        f"- 目标 URL：{target.get('resolved_url') or target.get('requested_url') or '-'}",
        f"- 问题生成模型：{data.get('question_generator') or '当前运行 Skill 的 Agent 模型'}",
        "",
        "## 模型能力检测",
        "",
        "| 模型 | 模型 ID | 联网搜索 | 返回来源 URL | 结论 |",
        "|---|---|---:|---:|---|",
    ]
    for item in capabilities:
        lines.append(
            f"| {_cell(item.get('model'))} | {_cell(item.get('model_id'))} | "
            f"{'是' if item.get('web_search') else '否'} | "
            f"{'是' if item.get('sources_returned') else '否'} | {_cell(item.get('status'))} |"
        )
    lines.extend([
        "",
        "## 汇总结论",
        "",
        f"- 检测问题：{summary.get('questions', 0)} 个",
        f"- 通过能力检测的模型：{summary.get('configured_models', 0)} 个",
        f"- 精确引用：{summary.get('exact', 0)} / {summary.get('valid_answers', 0)} 个有效回答",
        f"- 精确引用率：{_pct(summary.get('exact_citation_rate'))}",
        f"- 问题覆盖率：{_pct(summary.get('question_coverage_rate'))}",
        f"- 不可验证回答：{summary.get('unverifiable', 0)} 个",
        "",
        "## 逐题证据",
        "",
    ])
    for index, question in enumerate(data.get("questions") or []):
        lines.extend([
            f"### {index + 1}. {question.get('question')}",
            "",
            f"选择原因：{question.get('selection_reason') or '-'}",
            "",
        ])
        for item in [result for result in data.get("results") or [] if result.get("question_index") == index]:
            hit = (item.get("hit") or {}).get("layer", "unverifiable")
            lines.append(f"#### {item.get('model')}：{hit}")
            if item.get("error"):
                lines.append(f"- 错误：{item['error']}")
            sources = item.get("sources") or []
            lines.append("- 来源：" if sources else "- 来源：未返回来源 URL")
            lines.extend(f"  - {source}" for source in sources)
            lines.append("")
    lines.extend([
        "## 结果边界",
        "",
        "本结果只表示目标链接是否在本次指定问题和模型回答中作为来源出现。未发现引用，不代表内容从未被 AI 使用，也不能证明内容是否进入模型训练数据。",
        "",
    ])
    return "\n".join(lines)
