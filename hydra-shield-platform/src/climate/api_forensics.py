"""
/api/v2/forensics — Environmental Security & Forensic Verification API.

Registered from ``src/dashboard/api.py::create_app()``.

Endpoints:
    GET  /frameworks           Public framework / typology / claim-type list (60/min)
    POST /cases                Evaluate a forensic case (registered+, 6/min)
    POST /cases/pdf            PDF evidence pack for a case (registered+, 6/min)
    GET  /cases/<case_id>      Retrieve stored case (owner/admin)
"""

from __future__ import annotations

from typing import Any, Dict

from flask import Blueprint, Response, jsonify, request

forensics = Blueprint("forensics", __name__, url_prefix="/api/v2/forensics")


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
# Frameworks
# -----------------------------------------------------------------------------


@forensics.get("/frameworks")
def frameworks():
    """GET /api/v2/forensics/frameworks — public framework and vocabulary list."""
    if not _rate("v2forensics_frameworks", 60, 60.0):
        return _err("Rate limit exceeded", 429)

    from .forensics import (
        CASE_TYPOLOGIES,
        CLAIM_TYPES,
        FORENSIC_FRAMEWORKS,
        FORENSICS_DISCLAIMER,
        LEGAL_NOTE,
    )

    return jsonify({
        "typologies": CASE_TYPOLOGIES,
        "claim_types": CLAIM_TYPES,
        "frameworks": FORENSIC_FRAMEWORKS,
        "legal_note": LEGAL_NOTE,
        "disclaimer": FORENSICS_DISCLAIMER,
    })


# -----------------------------------------------------------------------------
# Case evaluation
# -----------------------------------------------------------------------------


def _normalise_case(data: Dict[str, Any]) -> Dict[str, Any]:
    """Return a case dict suitable for the engine; raises ValueError on bad input."""
    typology = data.get("typology")
    if not typology:
        raise ValueError("typology is required")

    subject_claim = data.get("subject_claim")
    if not isinstance(subject_claim, dict):
        raise ValueError("subject_claim must be an object")
    if not subject_claim.get("type"):
        raise ValueError("subject_claim.type is required")

    site = data.get("site")
    if not isinstance(site, dict):
        raise ValueError("site must be an object")

    radius_km = data.get("radius_km", 25.0)
    try:
        radius_km = float(radius_km)
    except (TypeError, ValueError):
        raise ValueError("radius_km must be a number")

    reference_documents = data.get("reference_documents")
    if reference_documents is not None and not isinstance(reference_documents, list):
        raise ValueError("reference_documents must be a list")

    return {
        "title": data.get("title"),
        "typology": typology,
        "site": site,
        "subject_claim": subject_claim,
        "reference_documents": reference_documents,
        "radius_km": radius_km,
    }


@forensics.post("/cases")
@_registered_gate
def evaluate_case():
    """POST /api/v2/forensics/cases — evaluate a forensic case."""
    if not _rate("v2forensics_cases", 6, 60.0):
        return _err("Rate limit exceeded", 429)

    from ..dashboard.auth_api import current_user
    from ..dashboard.verification_store import VerificationStore
    from .forensics import assess_case

    user = current_user()
    data = request.get_json(silent=True) or {}

    try:
        case = _normalise_case(data)
    except ValueError as exc:
        return _err(str(exc), 400)

    try:
        payload = assess_case(case)
    except ValueError as exc:
        return _err(str(exc), 400)
    except Exception as exc:
        return _err(f"Case assessment failed: {exc}", 502)

    VerificationStore().save_case(user_id=user["id"], case=case, payload=payload)

    return jsonify({
        "case_id": payload["case_id"],
        "case_verdict": payload["case_verdict"],
        "checks": payload["checks"],
        "declared_gaps_count": len(payload["declared_gaps"]),
        "payload": payload,
    })


@forensics.post("/cases/pdf")
@_registered_gate
def case_pdf():
    """POST /api/v2/forensics/cases/pdf — PDF evidence pack for a case."""
    if not _rate("v2forensics_cases_pdf", 6, 60.0):
        return _err("Rate limit exceeded", 429)

    from ..dashboard.forensics_report import build_forensics_pdf
    from .forensics import assess_case

    data = request.get_json(silent=True) or {}

    try:
        case = _normalise_case(data)
    except ValueError as exc:
        return _err(str(exc), 400)

    try:
        payload = assess_case(case)
    except ValueError as exc:
        return _err(str(exc), 400)
    except Exception as exc:
        return _err(f"Case assessment failed: {exc}", 502)

    try:
        pdf = build_forensics_pdf(payload)
    except RuntimeError as exc:
        return _err(f"Report generation unavailable: {exc}", 503)
    except Exception as exc:
        return _err(f"Report generation failed: {exc}", 502)

    title = payload.get("title") or payload.get("typology", {}).get("id") or "case"
    safe = "".join(c if c.isalnum() else "_" for c in str(title))[:40]
    return Response(
        pdf,
        mimetype="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="talaix_forensics_{safe}.pdf"',
            "Cache-Control": "no-store",
        },
    )


@forensics.get("/cases/<case_id>")
def get_case(case_id: str):
    """GET /api/v2/forensics/cases/<id> — owner or admin only."""
    from ..dashboard.accounts import ROLE_RANK
    from ..dashboard.auth_api import current_user
    from ..dashboard.verification_store import VerificationStore

    user = current_user()
    if user is None:
        from ..dashboard.auth_api import _unauthorized

        return _unauthorized()

    record = VerificationStore().get_case(case_id)
    if record is None:
        return _err(f"Unknown case '{case_id}'", 404)
    if record["user_id"] != user["id"] and ROLE_RANK.get(user["role"], 0) < ROLE_RANK["admin"]:
        return _err("You do not have access to this case", 403)
    return jsonify(record)
