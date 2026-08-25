"""
/api/v2/academy — Talaix Academy API.

Registered from ``src/dashboard.api.py::create_app()``.

Endpoints:
    GET  /courses                      List public course catalogue (60/min)
    GET  /courses/<course_id>          Public stripped course content (60/min)
    GET  /glossary                     List all glossary terms (60/min)
    GET  /glossary/<term_id>           One glossary term (60/min)
    POST /progress                     Grade + persist best score (registered+, 30/min)
    GET  /progress?course_id=...       My progress on a course (registered+)
    POST /certificate                  Issue Certificate of Completion (registered+)
    GET  /certificate/pdf?course_id=   Download certificate PDF (registered+)
    GET  /certificates/<id>/verify     Public certificate authenticity check (60/min)
"""

from __future__ import annotations

from typing import Any, Dict

from flask import Blueprint, Response, jsonify, request

academy = Blueprint("academy", __name__, url_prefix="/api/v2/academy")


def _err(message: str, status: int, **extra):
    payload = {"error": message, "status": status}
    payload.update(extra)
    return jsonify(payload), status


def _rate(key: str, max_requests: int, window: float) -> bool:
    from ..dashboard.api import _client_key, _rate_limiter  # lazy: avoid circulars

    return _rate_limiter.allow(f"{key}:{_client_key()}", max_requests, window)


def _registered_gate(func):
    """Require the 'registered' role; lazy import avoids dashboard load."""
    from ..dashboard.auth_api import require_role

    return require_role("registered")(func)


# -----------------------------------------------------------------------------
# Catalogue
# -----------------------------------------------------------------------------


@academy.get("/courses")
def list_courses():
    """GET /api/v2/academy/courses — public course list."""
    if not _rate("v2academy_courses", 60, 60.0):
        return _err("Rate limit exceeded", 429)
    from .academy import list_courses as _list_courses

    return jsonify({"courses": _list_courses()})


@academy.get("/courses/<course_id>")
def get_course(course_id: str):
    """GET /api/v2/academy/courses/<id> — public course content (answers stripped)."""
    if not _rate("v2academy_course", 60, 60.0):
        return _err("Rate limit exceeded", 429)
    from .academy import course_public

    course = course_public(course_id)
    if course is None:
        return _err(f"Unknown course '{course_id}'", 404)
    return jsonify({"course": course})


# -----------------------------------------------------------------------------
# Glossary
# -----------------------------------------------------------------------------


@academy.get("/glossary")
def list_glossary():
    """GET /api/v2/academy/glossary — all terms."""
    if not _rate("v2academy_glossary", 60, 60.0):
        return _err("Rate limit exceeded", 429)
    from .academy import load_glossary

    return jsonify(load_glossary())


@academy.get("/glossary/<term_id>")
def get_term(term_id: str):
    """GET /api/v2/academy/glossary/<id> — one term."""
    if not _rate("v2academy_term", 60, 60.0):
        return _err("Rate limit exceeded", 429)
    from .academy import get_term as _get_term

    term = _get_term(term_id)
    if term is None:
        return _err(f"Unknown term '{term_id}'", 404)
    return jsonify({"term": term})


# -----------------------------------------------------------------------------
# Progress and grading
# -----------------------------------------------------------------------------


@academy.post("/progress")
@_registered_gate
def submit_progress():
    """POST /api/v2/academy/progress — grade a module and persist the best score."""
    if not _rate("v2academy_progress", 30, 60.0):
        return _err("Rate limit exceeded", 429)

    from ..dashboard.auth_api import current_user
    from ..dashboard.verification_store import VerificationStore
    from .academy import grade

    user = current_user()
    data = request.get_json(silent=True) or {}
    course_id = data.get("course_id")
    module_id = data.get("module_id")
    answers = data.get("answers")

    if not course_id or not module_id:
        return _err("course_id and module_id are required", 400)
    if not isinstance(answers, list):
        return _err("answers must be a list of integers", 400)

    try:
        result = grade(course_id, module_id, answers)
    except ValueError as exc:
        return _err(str(exc), 400)
    except Exception as exc:
        return _err(f"Grading failed: {exc}", 502)

    VerificationStore().save_progress(
        user_id=user["id"],
        course_id=course_id,
        module_id=module_id,
        best_correct=result["score_correct"],
        best_total=result["score_total"],
        passed=result["passed"],
    )

    return jsonify(result)


@academy.get("/progress")
@_registered_gate
def get_progress():
    """GET /api/v2/academy/progress?course_id=... — my progress rows."""
    from ..dashboard.auth_api import current_user
    from ..dashboard.verification_store import VerificationStore

    user = current_user()
    course_id = request.args.get("course_id")
    if not course_id:
        return _err("course_id is required", 400)

    rows = VerificationStore().get_progress(user["id"], course_id)
    return jsonify({"course_id": course_id, "progress": rows})


# -----------------------------------------------------------------------------
# Certificates
# -----------------------------------------------------------------------------


def _course_title(course_id: str) -> str:
    from .academy import get_course as _get_course

    course = _get_course(course_id)
    return course.get("title", course_id) if course else course_id


@academy.post("/certificate")
@_registered_gate
def issue_certificate():
    """POST /api/v2/academy/certificate — issue a Certificate of Completion."""
    from ..dashboard.auth_api import current_user
    from ..dashboard.verification_store import VerificationStore
    from .academy import certificate_eligible, get_course

    user = current_user()
    data = request.get_json(silent=True) or {}
    course_id = data.get("course_id")
    if not course_id:
        return _err("course_id is required", 400)

    course = get_course(course_id)
    if course is None:
        return _err(f"Unknown course '{course_id}'", 404)

    store = VerificationStore()
    progress = store.get_progress(user["id"], course_id)
    eligible, missing = certificate_eligible(progress, course)
    if not eligible:
        return _err(
            "Not yet eligible for a certificate",
            409,
            missing_modules=missing,
            note="All modules, including the final assessment, must be passed.",
        )

    score_correct = sum(r["best_correct"] for r in progress)
    score_total = sum(r["best_total"] for r in progress)
    display_name = user.get("display_name") or user.get("email") or "Student"
    cert_id = store.save_certificate(
        user_id=user["id"],
        course_id=course_id,
        display_name=display_name,
        score_correct=score_correct,
        score_total=score_total,
    )
    cert = store.get_certificate(cert_id)
    return jsonify({"certificate": cert})


@academy.get("/certificate/pdf")
@_registered_gate
def certificate_pdf():
    """GET /api/v2/academy/certificate/pdf?course_id=... — certificate PDF."""
    from ..dashboard.academy_certificate import build_certificate_pdf
    from ..dashboard.auth_api import current_user
    from ..dashboard.verification_store import VerificationStore

    user = current_user()
    course_id = request.args.get("course_id")
    if not course_id:
        return _err("course_id is required", 400)

    cert = VerificationStore().get_certificate_for(user["id"], course_id)
    if cert is None:
        return _err("No certificate found for this course", 404)

    try:
        pdf = build_certificate_pdf(cert, _course_title(course_id))
    except RuntimeError as exc:
        return _err(f"PDF generation unavailable: {exc}", 503)
    except Exception as exc:
        return _err(f"PDF generation failed: {exc}", 502)

    safe = "".join(c if c.isalnum() else "_" for c in str(course_id))[:40]
    return Response(
        pdf,
        mimetype="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="talaix_academy_{safe}_certificate.pdf"',
            "Cache-Control": "no-store",
        },
    )


@academy.get("/certificates/<certificate_id>/verify")
def verify_certificate(certificate_id: str):
    """GET /api/v2/academy/certificates/<id>/verify — public authenticity check."""
    if not _rate("v2academy_verify", 60, 60.0):
        return _err("Rate limit exceeded", 429)

    from ..dashboard.verification_store import VerificationStore

    cert = VerificationStore().get_certificate(certificate_id)
    if cert is None:
        return jsonify({"valid": False}), 404

    return jsonify({
        "valid": True,
        "display_name": cert.get("display_name"),
        "course_id": cert.get("course_id"),
        "course_title": _course_title(cert.get("course_id", "")),
        "score_correct": cert.get("score_correct"),
        "score_total": cert.get("score_total"),
        "issued_at": cert.get("issued_at"),
        "note": "Talaix Academy Certificate of Completion — not an accredited academic qualification or professional certification.",
    })
