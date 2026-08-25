"""
Talaix Academy loader and logic.

Course and glossary content lives as config JSON registries
(``config/academy_course.json`` and ``config/academy_glossary.json``), loaded
in the same honest, fail-loud style as the other data registries.

No Flask imports. Quiz grading happens server-side; public course payloads have
correct answers and explanations stripped.
"""

from __future__ import annotations

import copy
import json
import math
import os
from typing import Any, Dict, List, Optional, Tuple

_DEFAULT_COURSE_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "config", "academy_course.json"
)
_DEFAULT_GLOSSARY_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "config", "academy_glossary.json"
)


class AcademyConfigError(RuntimeError):
    """Raised when course or glossary config cannot be loaded or is invalid."""


# -----------------------------------------------------------------------------
# Loading
# -----------------------------------------------------------------------------


def _load_json(path: str, label: str) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError as exc:
        raise AcademyConfigError(f"{label} not found at {path}") from exc
    except json.JSONDecodeError as exc:
        raise AcademyConfigError(f"{label} is not valid JSON: {exc}") from exc
    except OSError as exc:
        raise AcademyConfigError(f"{label} unreadable: {exc}") from exc


def load_course(path: Optional[str] = None) -> Dict[str, Any]:
    """Load the full academy course registry."""
    path = path or os.environ.get("HYDRASHIELD_ACADEMY_COURSE") or _DEFAULT_COURSE_PATH
    data = _load_json(path, "Academy course config")
    if not isinstance(data, dict) or "courses" not in data:
        raise AcademyConfigError("Academy course config must be an object with a 'courses' list")
    return data


def load_glossary(path: Optional[str] = None) -> Dict[str, Any]:
    """Load the full academy glossary registry."""
    path = path or os.environ.get("HYDRASHIELD_ACADEMY_GLOSSARY") or _DEFAULT_GLOSSARY_PATH
    data = _load_json(path, "Academy glossary config")
    if not isinstance(data, dict) or "terms" not in data:
        raise AcademyConfigError("Academy glossary config must be an object with a 'terms' list")
    return data


def get_course(course_id: str, course_config: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """Return one course dict from the registry, or None if not found."""
    config = course_config if course_config is not None else load_course()
    for course in config.get("courses", []):
        if course.get("id") == course_id:
            return course
    return None


def get_term(term_id: str, glossary_config: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """Return one glossary term dict, or None if not found."""
    config = glossary_config if glossary_config is not None else load_glossary()
    for term in config.get("terms", []):
        if term.get("id") == term_id:
            return term
    return None


# -----------------------------------------------------------------------------
# Public-safe course payload
# -----------------------------------------------------------------------------


def course_public(course_id: str, course_config: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """Return a course payload with quizzes stripped of answers and explanations."""
    course = get_course(course_id, course_config=course_config)
    if course is None:
        return None

    public = copy.deepcopy(course)
    for module in public.get("modules", []):
        for quiz in module.get("quiz", []):
            quiz.pop("correct_index", None)
            quiz.pop("explanation", None)
    return public


def list_courses(course_config: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Return a light list of courses (id, title, audience, description, module count, minutes)."""
    config = course_config if course_config is not None else load_course()
    result: List[Dict[str, Any]] = []
    for course in config.get("courses", []):
        modules = course.get("modules", [])
        result.append({
            "id": course.get("id"),
            "title": course.get("title"),
            "audience": course.get("audience"),
            "description": course.get("description"),
            "certificate_note": course.get("certificate_note"),
            "module_count": len(modules),
            "total_minutes": sum(int(m.get("minutes", 0)) for m in modules),
        })
    return result


# -----------------------------------------------------------------------------
# Grading
# -----------------------------------------------------------------------------


def _pass_threshold(num_questions: int) -> int:
    """Minimum correct answers to pass a module at 70%."""
    return math.ceil(0.7 * num_questions)


def grade(
    course_id: str,
    module_id: str,
    answers: List[int],
    course_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Grade a module quiz server-side.

    Returns a dict with score_correct, score_total, passed, and per-question
    results including the correct answer and explanation.
    """
    course = get_course(course_id, course_config=course_config)
    if course is None:
        raise AcademyConfigError(f"Unknown course '{course_id}'")

    module = None
    for m in course.get("modules", []):
        if m.get("id") == module_id:
            module = m
            break
    if module is None:
        raise AcademyConfigError(f"Unknown module '{module_id}' in course '{course_id}'")

    quiz = module.get("quiz") or []
    if len(answers) != len(quiz):
        raise ValueError(f"Expected {len(quiz)} answers, got {len(answers)}")

    correct_count = 0
    results: List[Dict[str, Any]] = []
    for idx, question in enumerate(quiz):
        correct_index = question.get("correct_index")
        user_answer = answers[idx]
        is_correct = correct_index is not None and user_answer == correct_index
        if is_correct:
            correct_count += 1
        results.append({
            "question": question.get("question"),
            "your_answer": user_answer,
            "correct_index": correct_index,
            "correct": is_correct,
            "explanation": question.get("explanation"),
        })

    total = len(quiz)
    threshold = _pass_threshold(total)
    passed = correct_count >= threshold

    return {
        "course_id": course_id,
        "module_id": module_id,
        "module_title": module.get("title"),
        "score_correct": correct_count,
        "score_total": total,
        "pass_threshold": threshold,
        "passed": passed,
        "results": results,
    }


# -----------------------------------------------------------------------------
# Certificate eligibility
# -----------------------------------------------------------------------------


def certificate_eligible(
    progress_rows: List[Dict[str, Any]],
    course: Dict[str, Any],
) -> Tuple[bool, List[str]]:
    """
    Determine whether a user has passed all modules in a course.

    progress_rows are dicts with at least 'module_id' and 'passed' keys.
    Returns (eligible, missing_module_ids).
    """
    passed_modules = {r["module_id"] for r in progress_rows if r.get("passed")}
    required = [m["id"] for m in course.get("modules", [])]
    missing = [m for m in required if m not in passed_modules]
    return not missing, missing
