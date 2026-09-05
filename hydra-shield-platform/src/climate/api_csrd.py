"""
/api/v2/csrd — CsrdTX regulatory intelligence API.

Registered from ``src/dashboard/api.py::create_app()``. Exposes the
version-aware regulatory knowledge base, the CSRD applicability engine
and the full CsrdTX assessment (applicability + double materiality +
coverage + readiness + gaps).
"""

from __future__ import annotations

from typing import Any, Dict, List

from flask import Blueprint, jsonify, request

csrd = Blueprint("csrd", __name__, url_prefix="/api/v2/csrd")


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
# Public regulatory reference
# -----------------------------------------------------------------------------


@csrd.get("/regulations")
def regulations():
    """GET /api/v2/csrd/regulations — regulatory versions + watch changelog."""
    if not _rate("v2csrd_regulations", 60, 60.0):
        return _err("Rate limit exceeded", 429)

    from .csrd.regulations import (
        esrs_versions,
        load_changelog,
        load_kb,
        wave_calendar,
    )

    kb = load_kb()
    return jsonify({
        "as_of": kb["changelog"].get("as_of"),
        "esrs_versions": esrs_versions(),
        "wave_calendar": wave_calendar(),
        "rule_sets": [
            {
                "id": rs.get("id"),
                "name": rs.get("name"),
                "status": rs.get("status"),
                "applies_to_reporting_years": rs.get("applies_to_reporting_years"),
                "source": rs.get("source"),
            }
            for rs in kb["applicability_rules"]["rule_sets"]
        ],
        "changelog": load_changelog().get("events", []),
        "status_vocabulary": kb["applicability_rules"].get("status_vocabulary"),
        "honesty_note": (
            "Entries whose status is not 'in_force' are reported for forward "
            "planning and are never silently applied to determinations."
        ),
    })


# -----------------------------------------------------------------------------
# Applicability screening
# -----------------------------------------------------------------------------


@csrd.post("/applicability")
@_registered_gate
def applicability():
    """POST /api/v2/csrd/applicability — CSRD scope screening for a company."""
    if not _rate("v2csrd_applicability", 20, 60.0):
        return _err("Rate limit exceeded", 429)

    from .csrd.applicability import assess_applicability

    data = request.get_json(silent=True) or {}
    company = data.get("company", data)  # accept bare profile or {"company": …}
    if not isinstance(company, dict):
        return _err("company must be an object", 400)
    if not (company.get("name") or "").strip():
        return _err("company.name is required", 400)

    try:
        return jsonify(assess_applicability(company))
    except ValueError as exc:
        return _err(str(exc), 400)


# -----------------------------------------------------------------------------
# Full assessment
# -----------------------------------------------------------------------------


def _normalise_assets(assets: List[Any]):
    normalised: List[Dict[str, Any]] = []
    for asset in assets:
        if not isinstance(asset, dict):
            return None
        normalised.append({
            "name": (asset.get("name") or "").strip() or None,
            "lat": asset.get("lat"),
            "lon": asset.get("lon"),
        })
    return normalised


@csrd.post("/assessment")
@_registered_gate
def assessment():
    """POST /api/v2/csrd/assessment — full CsrdTX assessment (JSON)."""
    if not _rate("v2csrd_assessment", 6, 60.0):
        return _err("Rate limit exceeded", 429)

    from ..dashboard.accounts import ROLE_RANK
    from ..dashboard.auth_api import current_user
    from .csrd.engine import build_csrd_assessment

    user = current_user()
    data = request.get_json(silent=True) or {}

    company = data.get("company")
    if not isinstance(company, dict):
        return _err("company must be an object", 400)
    if not (company.get("name") or "").strip():
        return _err("company.name is required", 400)

    assets_raw = data.get("assets") or []
    if not isinstance(assets_raw, list):
        return _err("assets must be a list", 400)
    max_assets = 100 if ROLE_RANK.get(user["role"], 0) >= ROLE_RANK["subscriber"] else 25
    if len(assets_raw) > max_assets:
        return _err(
            f"Assessment cannot cover more than {max_assets} sites for your tier",
            413,
            upgrade=None if ROLE_RANK.get(user["role"], 0) >= ROLE_RANK["subscriber"] else {
                "required_role": "subscriber",
                "your_role": user["role"],
                "unlocks": "Upgrading to 'subscriber' allows assessments covering up to 100 sites.",
            },
        )
    assets = _normalise_assets(assets_raw)
    if assets is None:
        return _err("assets must be a list of objects", 400)

    materiality_inputs = data.get("materiality_inputs")
    if materiality_inputs is not None and not isinstance(materiality_inputs, dict):
        return _err("materiality_inputs must be an object keyed by topic id", 400)

    esrs_version_id = data.get("esrs_version")

    try:
        payload = build_csrd_assessment(
            company,
            assets or None,
            materiality_inputs=materiality_inputs,
            esrs_version_id=esrs_version_id,
        )
    except ValueError as exc:
        return _err(str(exc), 400)
    except Exception as exc:
        return _err(f"Assessment failed: {exc}", 502)

    return jsonify(payload)
