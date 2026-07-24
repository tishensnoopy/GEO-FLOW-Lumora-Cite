"""Core utilities for Lumora Cite.

This package is intentionally independent from Lumora users, billing, tasks,
and reports so it can later be extracted into the open-source Agent.
"""

from .limits import beijing_day
from .engine import ModelAnswer, run_citation_check
from .matching import classify_citation_hit, normalize_url
from .question_generation import build_candidate_prompt, generate_candidates
from .questions import QuestionCandidate, select_best_questions
from .suitability import SuitabilityResult, evaluate_content_suitability

__all__ = [
    "QuestionCandidate",
    "SuitabilityResult",
    "ModelAnswer",
    "beijing_day",
    "build_candidate_prompt",
    "classify_citation_hit",
    "evaluate_content_suitability",
    "generate_candidates",
    "normalize_url",
    "run_citation_check",
    "select_best_questions",
]
