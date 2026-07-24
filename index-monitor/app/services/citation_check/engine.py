"""Provider-independent Citation Check execution engine."""

from dataclasses import asdict, dataclass
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Protocol

from .matching import classify_citation_hit
from .questions import QuestionCandidate, select_best_questions


VERIFIED_CITATIONS = "verified_citations"
SEARCH_WITHOUT_CITATIONS = "search_without_citations"
ANSWER_ONLY = "answer_only"
DEFAULT_QUESTION_COUNT = 10
CAPABILITY_PROBE_QUESTION = "请联网搜索 Python 官方网站，并在回答中保留至少一个来源链接。"


@dataclass(frozen=True)
class ModelAnswer:
    model: str
    model_id: str
    answer: str
    sources: list[str]
    search_used: bool | None
    error: str | None = None


class CitationModelAdapter(Protocol):
    provider_id: str
    name: str
    model_id: str
    capability: str

    def ask(self, question: str) -> ModelAnswer:
        """Ask one independent question and return structured source evidence."""


def ask_with_retry(adapter: CitationModelAdapter, question: str, retries: int = 1) -> ModelAnswer:
    result: ModelAnswer | None = None
    for _ in range(retries + 1):
        try:
            result = adapter.ask(question)
        except Exception as exc:
            result = ModelAnswer(adapter.name, adapter.model_id, "", [], None, str(exc))
        if not result.error:
            return result
    return result or ModelAnswer(adapter.name, adapter.model_id, "", [], None, "模型未返回结果")


def _is_verifiable(adapter: CitationModelAdapter, answer: ModelAnswer) -> bool:
    if adapter.capability != VERIFIED_CITATIONS or answer.error:
        return False
    return answer.search_used is True or bool(answer.sources)


def probe_adapter_capability(adapter: CitationModelAdapter) -> dict:
    """Verify that the configured model actually searches and returns source URLs."""
    answer = ask_with_retry(adapter, CAPABILITY_PROBE_QUESTION, 0)
    web_search = answer.search_used is True
    sources_returned = bool(answer.sources)
    if answer.error:
        status = "error"
    elif web_search and sources_returned:
        status = "verified"
    elif web_search:
        status = "search_without_sources"
    else:
        status = "no_search"
    return {
        "provider_id": getattr(adapter, "provider_id", adapter.name),
        "model": adapter.name,
        "model_id": adapter.model_id,
        "status": status,
        "web_search": web_search,
        "sources_returned": sources_returned,
        "sample_sources": answer.sources[:3],
        "error": answer.error,
    }


def probe_adapter_capabilities(adapters: list[CitationModelAdapter]) -> list[dict]:
    if not adapters:
        return []
    with ThreadPoolExecutor(max_workers=min(6, len(adapters))) as executor:
        results = list(executor.map(probe_adapter_capability, adapters))
    return sorted(results, key=lambda item: item["model"])


def run_citation_check(
    *,
    target_urls: list[str],
    candidates: list[QuestionCandidate],
    adapters: list[CitationModelAdapter],
    question_count: int = DEFAULT_QUESTION_COUNT,
    forbidden_terms: list[str] | None = None,
) -> dict:
    """Run selected questions against configured adapters and aggregate evidence."""
    selected = select_best_questions(
        candidates,
        count=question_count,
        forbidden_terms=forbidden_terms,
    )
    if len(selected) < question_count:
        raise ValueError(f"合格问题不足：需要 {question_count} 个，实际 {len(selected)} 个")
    if not adapters:
        raise ValueError("至少需要配置一个模型适配器")

    results = []
    exact_questions = set()
    exact_models = set()
    counts = {"exact": 0, "domain": 0, "none": 0, "unverifiable": 0}

    jobs = [
        (question_index, candidate, adapter)
        for question_index, candidate in enumerate(selected)
        for adapter in adapters
    ]
    with ThreadPoolExecutor(max_workers=min(12, len(jobs))) as executor:
        futures = {
            executor.submit(ask_with_retry, adapter, candidate.question, 1): (question_index, candidate, adapter)
            for question_index, candidate, adapter in jobs
        }
        for future in as_completed(futures):
            question_index, candidate, adapter = futures[future]
            answer = future.result()
            hit = classify_citation_hit(
                target_urls,
                answer.sources,
                verifiable=_is_verifiable(adapter, answer),
            )
            counts[hit.layer] += 1
            if hit.layer == "exact":
                exact_questions.add(question_index)
                exact_models.add(adapter.name)
            results.append({
                "question_index": question_index,
                "question": candidate.question,
                "selection_reason": candidate.selection_reason,
                "question_score": round(candidate.score, 4),
                "model": answer.model,
                "model_id": answer.model_id,
                "capability": adapter.capability,
                "answer": answer.answer,
                "sources": answer.sources,
                "search_used": answer.search_used,
                "error": answer.error,
                "hit": asdict(hit),
            })
    results.sort(key=lambda item: (item["question_index"], item["model"]))

    valid_answers = counts["exact"] + counts["domain"] + counts["none"]
    valid_models = {
        item["model"]
        for item in results
        if item["hit"]["layer"] != "unverifiable"
    }
    summary = {
        "questions": len(selected),
        "configured_models": len(adapters),
        "valid_answers": valid_answers,
        **counts,
        "exact_citation_rate": counts["exact"] / valid_answers if valid_answers else None,
        "domain_appearance_rate": counts["domain"] / valid_answers if valid_answers else None,
        "question_coverage_rate": len(exact_questions) / len(selected) if selected else None,
        "model_coverage_rate": len(exact_models) / len(valid_models) if valid_models else None,
    }
    return {
        "questions": [
            {
                "question": item.question,
                "selection_reason": item.selection_reason,
                "score": round(item.score, 4),
            }
            for item in selected
        ],
        "summary": summary,
        "results": results,
    }
