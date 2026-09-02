"""
/api/v2/licensing — Environmental Licensing Advisory API.

Registered from ``src/dashboard/api.py::create_app()``. Exposes the
licensing dossier engine (``src.climate.licensing``): the evidence
vocabulary endpoint (sides / typologies / permit types / frameworks) and
the dossier builder. The same engine is also registered as the TX-2
product ``licensing`` (``tx_core.adapters.products``).

Honesty contract: invalid requests fail with a clear 400; layer failures
inside a dossier are declared UNKNOWN gaps, never fabricated.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from flask import Blueprint, jsonify, request

licensing = Blueprint("licensing", __name__, url_prefix="/api/v2/licensing")


def _err(message: str, status: int, **extra):
    payload = {"error": message, "status": status}
    payload.update(extra)
    return jsonify(payload), status


def _rate(key: str, max_requests: int, window: float) -> bool:
    from ..dashboard.api import _client_key, _rate_limiter  # lazy: avoid circulars

    return _rate_limiter.allow(f"{key}:{_client_key()}", max_requests, window)


# -----------------------------------------------------------------------------
# Evidence vocabulary
# -----------------------------------------------------------------------------


@licensing.get("/frameworks")
def frameworks():
    """GET /api/v2/licensing/frameworks — the dossier vocabulary.

    Applicant sides, project typologies, permit types and the referenced
    international frameworks. Public and data-free (static vocabulary).
    """
    from . import licensing as licensing_module

    return jsonify({
        "applicant_sides": [
            {"id": side_id, "label": cfg["label"], "framing": cfg["framing"]}
            for side_id, cfg in licensing_module.APPLICANT_SIDES.items()
        ],
        "typologies": [
            {"id": typ_id, "label": cfg["label"], "note": cfg["note"]}
            for typ_id, cfg in licensing_module.PROJECT_TYPOLOGIES.items()
        ],
        "permit_types": [
            {"id": permit_id, "label": cfg["label"], "note": cfg["note"]}
            for permit_id, cfg in licensing_module.PERMIT_TYPES.items()
        ],
        "hazards": [
            {"id": hazard_id, "permit_label": cfg["permit_label"]}
            for hazard_id, cfg in licensing_module.LICENSING_HAZARDS.items()
        ],
        "frameworks": licensing_module.LICENSING_FRAMEWORKS,
        "disclaimer": licensing_module.DISCLAIMER,
        "honesty_contract": licensing_module.HONESTY_CONTRACT,
    })


# -----------------------------------------------------------------------------
# Dossier builder
# -----------------------------------------------------------------------------


def _dossier_request_body() -> "tuple[Optional[Dict[str, Any]], Optional[Any]]":
    """Validate the POST /dossier JSON body.

    Returns ``(params, None)`` on success or ``(None, error_response)``.
    """
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return None, _err(
            "JSON body required: {site: {lat, lon} | {address}, [radius_km], "
            "[side], [typology], [permit_type], [project_title], "
            "[description], [jurisdiction], [hazards]}",
            400,
        )

    site = body.get("site")
    if not isinstance(site, dict):
        return None, _err("site is required: {lat, lon} or {address}", 400)
    has_coords = site.get("lat") is not None and site.get("lon") is not None
    has_address = bool((site.get("address") or "").strip())
    if not has_coords and not has_address:
        return None, _err("site must include lat/lon or an address", 400)

    radius_raw = body.get("radius_km", 25.0)
    try:
        radius_km = float(radius_raw)
    except (TypeError, ValueError):
        return None, _err("radius_km must be a number", 400)
    if not (1.0 <= radius_km <= 200.0):
        return None, _err("radius_km must be between 1 and 200", 400)

    hazards_raw = body.get("hazards")
    hazards: Optional[List[str]] = None
    if isinstance(hazards_raw, str):
        hazards = [h.strip() for h in hazards_raw.split(",") if h.strip()]
    elif isinstance(hazards_raw, list):
        hazards = [str(h) for h in hazards_raw if str(h).strip()]
    elif hazards_raw is not None:
        return None, _err(
            "hazards must be a list of hazard ids or a comma-separated string",
            400,
        )

    return (
        {
            "site": {
                "lat": site.get("lat"),
                "lon": site.get("lon"),
                "name": site.get("name"),
                "address": site.get("address"),
            },
            "radius_km": radius_km,
            "side": body.get("side"),
            "typology": body.get("typology"),
            "permit_type": body.get("permit_type"),
            "project_title": body.get("project_title"),
            "description": body.get("description"),
            "jurisdiction": body.get("jurisdiction"),
            "hazards": hazards,
        },
        None,
    )


@licensing.post("/dossier")
def build_dossier():
    """POST /api/v2/licensing/dossier — build the pre-draft evidence dossier.

    Public, rate-limited screening endpoint (the same evidence the advisory
    workflow reviews into the delivered branded dossier).
    """
    if not _rate("v2licensing_dossier", 10, 60.0):
        return _err("Rate limit exceeded", 429)

    params, error = _dossier_request_body()
    if error is not None:
        return error
    assert params is not None

    from .licensing import build_licensing_dossier

    dossier = build_licensing_dossier(**params)
    if "error" in dossier:
        return _err(dossier["error"], 400)
    return jsonify(dossier)
