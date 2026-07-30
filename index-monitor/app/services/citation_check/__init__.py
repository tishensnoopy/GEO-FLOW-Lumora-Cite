"""Core utilities for Lumora Cite.

This package is intentionally independent from Lumora users, billing, tasks,
and reports so it can later be extracted into the open-source Agent.
"""

from .limits import beijing_day
from .engine import ModelAnswer, run_citation_check
from .matching import classify_citation_hit, normalize_url
from .questions import QuestionCandidate, select_best_questions
from .suitability import SuitabilityResult, evaluate_content_suitability

__all__ = [
    "QuestionCandidate",
    "SuitabilityResult",
    "ModelAnswer",
    "beijing_day",
    "classify_citation_hit",
    "evaluate_content_suitability",
    "normalize_url",
    "run_citation_check",
    "select_best_questions",
]
