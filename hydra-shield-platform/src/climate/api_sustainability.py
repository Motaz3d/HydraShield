"""
/api/v2/sustainability — Sustainability Evidence Reporting API.

Registered from ``src/dashboard/api.py::create_app()``. Provides a CSRD/ESRS-
oriented evidence pack for a company profile plus site locations, reusing the
Green Finance Verification engine.
"""

from __future__ import annotations

from typing import Any, Dict, List

from flask import Blueprint, Response, jsonify, request

sustainability = Blueprint("sustainability", __name__, url_prefix="/api/v2/sustainability")


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
# Public frameworks reference
# -----------------------------------------------------------------------------


@sustainability.get("/frameworks")
def frameworks():
    """GET /api/v2/sustainability/frameworks — public frameworks reference."""
    if not _rate("v2sustainability_frameworks", 60, 60.0):
        return _err("Rate limit exceeded", 429)

    from .sustainability import (
        DISCLAIMER as disclaimer,
        ESRS_COVERAGE,
        EVIDENCE_STANDARD,
        SUSTAINABILITY_FRAMEWORKS,
    )

    return jsonify({
        "frameworks": SUSTAINABILITY_FRAMEWORKS,
        "coverage_map": ESRS_COVERAGE,
        "evidence_standard": EVIDENCE_STANDARD,
        "disclaimer": disclaimer,
    })


# -----------------------------------------------------------------------------
# Report generation
# -----------------------------------------------------------------------------


def _validate_report_body(data: Dict[str, Any]) -> tuple:
    """Validate the POST body and return (company, assets) or (None, error_response)."""
    company = data.get("company")
    if not isinstance(company, dict):
        return None, _err("company must be an object", 400)
    if not (company.get("name") or "").strip():
        return None, _err("company.name is required", 400)

    assets = data.get("assets")
    if not isinstance(assets, list):
        return None, _err("assets must be a list", 400)
    if not assets:
        return None, _err("assets list is empty", 400)

    return company, None


def _normalise_assets(assets: List[Any]) -> List[Dict[str, Any]]:
    """Normalise assets to dicts with name/lat/lon, preserving invalid values."""
    normalised: List[Dict[str, Any]] = []
    for asset in assets:
        if not isinstance(asset, dict):
            return None  # signal malformed
        normalised.append({
            "name": (asset.get("name") or "").strip() or None,
            "lat": asset.get("lat"),
            "lon": asset.get("lon"),
        })
    return normalised


def _build_and_persist(user: Dict[str, Any], company: Dict[str, Any], assets: List[Dict[str, Any]]) -> tuple:
    """Build the evidence payload and persist it. Returns (payload, error_response)."""
    from ..dashboard.verification_store import VerificationStore
    from .sustainability import build_sustainability_evidence

    try:
        payload = build_sustainability_evidence(company, assets)
    except ValueError as exc:
        return None, _err(str(exc), 400)
    except Exception as exc:
        return None, _err(f"Report generation failed: {exc}", 502)

    VerificationStore().save_report(
        user_id=user["id"],
        company=company,
        payload=payload,
    )
    return payload, None


@sustainability.post("/report")
@_registered_gate
def report():
    """POST /api/v2/sustainability/report — JSON evidence report."""
    if not _rate("v2sustainability_report", 6, 60.0):
        return _err("Rate limit exceeded", 429)

    from ..dashboard.accounts import ROLE_RANK
    from ..dashboard.auth_api import current_user

    user = current_user()
    data = request.get_json(silent=True) or {}

    company, err = _validate_report_body(data)
    if err:
        return err

    max_assets = 100 if ROLE_RANK.get(user["role"], 0) >= ROLE_RANK["subscriber"] else 25
    assets_raw = data.get("assets", [])
    if len(assets_raw) > max_assets:
        return _err(
            f"Report cannot cover more than {max_assets} sites for your tier",
            413,
            upgrade=None if ROLE_RANK.get(user["role"], 0) >= ROLE_RANK["subscriber"] else {
                "required_role": "subscriber",
                "your_role": user["role"],
                "unlocks": "Upgrading to 'subscriber' allows reports covering up to 100 sites.",
            },
        )

    assets = _normalise_assets(assets_raw)
    if assets is None:
        return _err("assets must be a list of objects", 400)

    payload, err = _build_and_persist(user, company, assets)
    if err:
        return err
    return jsonify(payload)


@sustainability.post("/report/pdf")
@_registered_gate
def report_pdf():
    """POST /api/v2/sustainability/report/pdf — PDF evidence report."""
    if not _rate("v2sustainability_report_pdf", 6, 60.0):
        return _err("Rate limit exceeded", 429)

    from ..dashboard.accounts import ROLE_RANK
    from ..dashboard.auth_api import current_user
    from ..dashboard.sustainability_report import build_sustainability_pdf

    user = current_user()
    data = request.get_json(silent=True) or {}

    company, err = _validate_report_body(data)
    if err:
        return err

    max_assets = 100 if ROLE_RANK.get(user["role"], 0) >= ROLE_RANK["subscriber"] else 25
    assets_raw = data.get("assets", [])
    if len(assets_raw) > max_assets:
        return _err(
            f"Report cannot cover more than {max_assets} sites for your tier",
            413,
            upgrade=None if ROLE_RANK.get(user["role"], 0) >= ROLE_RANK["subscriber"] else {
                "required_role": "subscriber",
                "your_role": user["role"],
                "unlocks": "Upgrading to 'subscriber' allows reports covering up to 100 sites.",
            },
        )

    assets = _normalise_assets(assets_raw)
    if assets is None:
        return _err("assets must be a list of objects", 400)

    payload, err = _build_and_persist(user, company, assets)
    if err:
        return err

    try:
        pdf = build_sustainability_pdf(payload)
    except RuntimeError as exc:
        return _err(f"Report generation unavailable: {exc}", 503)
    except Exception as exc:
        return _err(f"Report generation failed: {exc}", 502)

    safe = "".join(c if c.isalnum() else "_" for c in (company.get("name") or "report"))[:40]
    return Response(
        pdf,
        mimetype="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="talaix_sustainability_{safe}.pdf"',
            "Cache-Control": "no-store",
        },
    )


@sustainability.get("/report/<report_id>")
def get_report(report_id: str):
    """GET /api/v2/sustainability/report/<id> — owner or admin only."""
    from ..dashboard.accounts import ROLE_RANK
    from ..dashboard.auth_api import current_user
    from ..dashboard.verification_store import VerificationStore

    user = current_user()
    if user is None:
        from ..dashboard.auth_api import _unauthorized

        return _unauthorized()

    record = VerificationStore().get_report(report_id)
    if record is None:
        return _err(f"Unknown report '{report_id}'", 404)
    if record["user_id"] != user["id"] and ROLE_RANK.get(user["role"], 0) < ROLE_RANK["admin"]:
        return _err("You do not have access to this report", 403)
    return jsonify(record)
