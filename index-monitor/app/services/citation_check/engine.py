"""Provider-independent Citation Check execution engine."""

import logging
import time
from dataclasses import asdict, dataclass
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Protocol

from .matching import classify_citation_hit
from .questions import QuestionCandidate, select_best_questions


logger = logging.getLogger(__name__)

VERIFIED_CITATIONS = "verified_citations"
SEARCH_WITHOUT_CITATIONS = "search_without_citations"
ANSWER_ONLY = "answer_only"
DEFAULT_QUESTION_COUNT = 10
CAPABILITY_PROBE_QUESTION = "请联网搜索 Python 官方网站，并在回答中保留至少一个来源链接。"

# 探测结果缓存：模型是否支持联网搜索是准静态数据，不会几分钟内变化。
# 进程内 dict + TTL，避免每次 check_url 都重新探测 N 个模型（省配额、降延迟）。
# 多 worker 间不共享，每个 worker 启动后第一次探测会重复——可接受。
_PROBE_CACHE: dict[str, tuple[float, dict]] = {}
_PROBE_CACHE_TTL = 3600  # 秒（1 小时）


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


def _cache_key(adapter: CitationModelAdapter) -> str:
    """构造缓存 key：provider_id:model_id。"""
    return f"{getattr(adapter, 'provider_id', adapter.name)}:{adapter.model_id}"


def _get_cached(key: str) -> dict | None:
    """读取缓存，过期返回 None。"""
    entry = _PROBE_CACHE.get(key)
    if entry is None:
        return None
    timestamp, value = entry
    if time.time() - timestamp > _PROBE_CACHE_TTL:
        return None
    logger.debug("probe cache hit: %s", key)
    return value


def _set_cached(key: str, value: dict) -> None:
    """写入缓存。"""
    _PROBE_CACHE[key] = (time.time(), value)


def invalidate_probe_cache(provider_id: str | None = None) -> None:
    """清空探测缓存。

    - provider_id=None：清空全部（供配置批量变更时调用）
    - provider_id="qwen"：只清该模型的缓存（供单模型 Key 更新时调用）
    """
    if provider_id is None:
        _PROBE_CACHE.clear()
        logger.info("probe cache cleared (all)")
        return
    keys_to_remove = [k for k in _PROBE_CACHE if k.startswith(f"{provider_id}:")]
    for k in keys_to_remove:
        del _PROBE_CACHE[k]
    logger.info("probe cache invalidated for %s (%d entries)", provider_id, len(keys_to_remove))


def _probe_adapter_capability_uncached(adapter: CitationModelAdapter) -> dict:
    """Verify that the configured model actually searches and returns source URLs.

    P0 修复（保留）：
    1. 探测重试从 0 次改为 2 次（应对偶发超时/限流）
    2. verified 标准从 AND 放宽为 OR（web_search 或 sources_returned 任一即可）
       原标准过严导致大量实际支持联网的模型被淘汰，采信检测"几乎每次触发失败"。
    """
    answer = ask_with_retry(adapter, CAPABILITY_PROBE_QUESTION, 2)
    web_search = answer.search_used is True
    sources_returned = bool(answer.sources)
    if answer.error:
        status = "error"
    elif web_search or sources_returned:
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


def probe_adapter_capability(adapter: CitationModelAdapter, *, force_refresh: bool = False) -> dict:
    """探测适配器联网能力（带 TTL 缓存）。

    - force_refresh=True：跳过缓存重新探测（供配置变更后强制刷新）
    - 默认走缓存，TTL=_PROBE_CACHE_TTL（1 小时）
    """
    key = _cache_key(adapter)
    if not force_refresh:
        cached = _get_cached(key)
        if cached is not None:
            return cached
    result = _probe_adapter_capability_uncached(adapter)
    _set_cached(key, result)
    return result


def probe_adapter_capabilities(adapters: list[CitationModelAdapter]) -> list[dict]:
    if not adapters:
        return []
    # 先检查缓存，只对未命中的适配器并发探测
    cached_results: list[tuple[int, dict]] = []
    adapters_to_probe: list[tuple[int, CitationModelAdapter]] = []
    for idx, adapter in enumerate(adapters):
        cached = _get_cached(_cache_key(adapter))
        if cached is not None:
            cached_results.append((idx, cached))
        else:
            adapters_to_probe.append((idx, adapter))

    # 并发探测未命中的适配器
    fresh_results: list[tuple[int, dict]] = []
    if adapters_to_probe:
        with ThreadPoolExecutor(max_workers=min(6, len(adapters_to_probe))) as executor:
            futures = {
                executor.submit(probe_adapter_capability, adapter): (idx, adapter)
                for idx, adapter in adapters_to_probe
            }
            for future in as_completed(futures):
                idx, adapter = futures[future]
                fresh_results.append((idx, future.result()))

    # 按原顺序合并，再按 model 名排序（保持与原实现一致的行为）
    all_results = cached_results + fresh_results
    all_results.sort(key=lambda item: item[0])
    results = [result for _, result in all_results]
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
