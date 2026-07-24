"""Question candidate validation, scoring, and selection."""

from dataclasses import dataclass, field
import re


@dataclass(frozen=True)
class QuestionCandidate:
    question: str
    content_support: float
    natural_intent: float
    citation_need: float
    distinctiveness: float
    freshness: float
    selection_reason: str = ""
    metadata: dict = field(default_factory=dict)

    @property
    def score(self) -> float:
        base = (
            self.content_support * 0.30
            + self.natural_intent * 0.25
            + self.citation_need * 0.25
            + self.distinctiveness * 0.15
            + self.freshness * 0.05
        )
        purpose_alignment = float(self.metadata.get("purpose_alignment", 0))
        return base * 0.75 + purpose_alignment * 0.25


def _tokens(text: str) -> set[str]:
    lowered = (text or "").lower()
    ascii_words = re.findall(r"[a-z0-9]+", lowered)
    chinese_chars = re.findall(r"[\u4e00-\u9fff]", lowered)
    return set(ascii_words + chinese_chars)


def _similarity(left: str, right: str) -> float:
    a, b = _tokens(left), _tokens(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _contains_leak(question: str, forbidden_terms: list[str]) -> bool:
    lowered = question.lower()
    return any(term.strip().lower() in lowered for term in forbidden_terms if term and term.strip())


def select_best_questions(
    candidates: list[QuestionCandidate],
    *,
    count: int = 3,
    forbidden_terms: list[str] | None = None,
    max_similarity: float = 0.72,
) -> list[QuestionCandidate]:
    """Select high-scoring, non-leaking, sufficiently diverse questions."""
    forbidden_terms = forbidden_terms or []
    valid = [
        candidate
        for candidate in candidates
        if candidate.question.strip()
        and not _contains_leak(candidate.question, forbidden_terms)
        and min(
            candidate.content_support,
            candidate.natural_intent,
            candidate.citation_need,
            candidate.distinctiveness,
            candidate.freshness,
        ) >= 0
        and max(
            candidate.content_support,
            candidate.natural_intent,
            candidate.citation_need,
            candidate.distinctiveness,
            candidate.freshness,
        ) <= 1
    ]
    selected: list[QuestionCandidate] = []
    for candidate in sorted(valid, key=lambda item: item.score, reverse=True):
        if all(_similarity(candidate.question, chosen.question) <= max_similarity for chosen in selected):
            selected.append(candidate)
        if len(selected) == count:
            break
    return selected
