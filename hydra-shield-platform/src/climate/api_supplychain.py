"""
/api/v2/supplychain — Supply Chain Origin & EUDR Evidence API.

Registered from ``src/dashboard/api.py::create_app()``.

Endpoints:
    GET  /frameworks                Public framework list (60/min)
    POST /claims                    Evaluate a claim (registered+, 6/min)
    POST /claims/pdf                PDF report for a claim (registered+, 6/min)
    GET  /claims/<claim_id>         Retrieve stored claim (owner/admin)
"""

from __future__ import annotations

from typing import Any, Dict, List

from flask import Blueprint, Response, jsonify, request

supplychain = Blueprint("supplychain", __name__, url_prefix="/api/v2/supplychain")


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


def _normalise_plots(plots: Any) -> List[Dict[str, Any]]:
    """Validate and normalise the plot list supplied by the caller."""
    normalised: List[Dict[str, Any]] = []
    if not isinstance(plots, list):
        return None  # type: ignore[return-value]
    for idx, raw in enumerate(plots):
        if not isinstance(raw, dict):
            return None  # type: ignore[return-value]
        name = (raw.get("name") or "").strip() or f"plot_{idx + 1}"
        lat = raw.get("lat")
        lon = raw.get("lon")
        try:
            lat_f = float(lat)
            lon_f = float(lon)
        except (TypeError, ValueError):
            return None  # type: ignore[return-value]
        if not (-90.0 <= lat_f <= 90.0 and -180.0 <= lon_f <= 180.0):
            return None  # type: ignore[return-value]
        normalised.append({
            "name": name,
            "lat": lat_f,
            "lon": lon_f,
            "address": (raw.get("address") or "").strip() or None,
        })
    return normalised


# -----------------------------------------------------------------------------
# Frameworks
# -----------------------------------------------------------------------------


@supplychain.get("/frameworks")
def frameworks():
    """GET /api/v2/supplychain/frameworks — public framework list."""
    if not _rate("v2supplychain_frameworks", 60, 60.0):
        return _err("Rate limit exceeded", 429)

    from .supplychain import (
        DISCLAIMER, EUDR_COMMODITIES, EUDR_CUTOFF_DATE, SUPPLY_CHAIN_FRAMEWORKS,
    )

    return jsonify({
        "frameworks": SUPPLY_CHAIN_FRAMEWORKS,
        "eudr_commodities": EUDR_COMMODITIES,
        "eudr_cutoff_date": EUDR_CUTOFF_DATE,
        "disclaimer": DISCLAIMER,
    })


# -----------------------------------------------------------------------------
# Claim evaluation
# -----------------------------------------------------------------------------


@supplychain.post("/claims")
@_registered_gate
def evaluate_claim_endpoint():
    """POST /api/v2/supplychain/claims — evaluate an origin/green claim."""
    if not _rate("v2supplychain_claims", 6, 60.0):
        return _err("Rate limit exceeded", 429)

    from ..dashboard.accounts import ROLE_RANK
    from ..dashboard.auth_api import current_user
    from ..dashboard.verification_store import VerificationStore
    from .supplychain import evaluate_claim

    user = current_user()
    data = request.get_json(silent=True) or {}

    plots = data.get("plots")
    if not isinstance(plots, list) or not plots:
        return _err("plots must be a non-empty list", 400)

    max_plots = 100 if ROLE_RANK.get(user["role"], 0) >= ROLE_RANK["subscriber"] else 25
    if len(plots) > max_plots:
        return _err(
            f"Claims cannot exceed {max_plots} plots for your tier",
            413,
            upgrade=None if ROLE_RANK.get(user["role"], 0) >= ROLE_RANK["subscriber"] else {
                "required_role": "subscriber",
                "your_role": user["role"],
                "unlocks": "Upgrading to 'subscriber' allows claims up to 100 plots.",
            },
        )

    normalised_plots = _normalise_plots(plots)
    if normalised_plots is None:
        return _err("each plot must be an object with valid lat/lon", 400)

    claim = evaluate_claim({
        "supplier": data.get("supplier"),
        "commodity": data.get("commodity"),
        "country": data.get("country"),
        "plots": normalised_plots,
    })

    VerificationStore().save_claim(user_id=user["id"], claim=claim)

    return jsonify({
        "claim_id": claim["claim_id"],
        "claim_verdict": claim["claim_verdict"],
        "deforestation_assessment": claim["deforestation_assessment"],
        "plot_count": claim["plot_count"],
        "partial_evidence_count": claim["partial_evidence_count"],
        "no_evidence_count": claim["no_evidence_count"],
        "declared_gaps_count": len(claim["declared_gaps"]),
        "claim": claim,
    })


@supplychain.post("/claims/pdf")
@_registered_gate
def claim_pdf():
    """POST /api/v2/supplychain/claims/pdf — PDF evidence report for a claim."""
    if not _rate("v2supplychain_claims_pdf", 6, 60.0):
        return _err("Rate limit exceeded", 429)

    from .supplychain import evaluate_claim
    from ..dashboard.supplychain_report import build_supplychain_pdf

    data = request.get_json(silent=True) or {}

    plots = data.get("plots")
    if not isinstance(plots, list) or not plots:
        return _err("plots must be a non-empty list", 400)

    normalised_plots = _normalise_plots(plots)
    if normalised_plots is None:
        return _err("each plot must be an object with valid lat/lon", 400)

    claim = evaluate_claim({
        "supplier": data.get("supplier"),
        "commodity": data.get("commodity"),
        "country": data.get("country"),
        "plots": normalised_plots,
    })

    try:
        pdf = build_supplychain_pdf(claim)
    except RuntimeError as exc:
        return _err(f"Report generation unavailable: {exc}", 503)
    except Exception as exc:
        return _err(f"Report generation failed: {exc}", 502)

    safe = "".join(c if c.isalnum() else "_" for c in str(claim.get("commodity") or claim.get("supplier") or "claim"))[:40]
    return Response(
        pdf,
        mimetype="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="talaix_supplychain_{safe}.pdf"',
            "Cache-Control": "no-store",
        },
    )


@supplychain.get("/claims/<claim_id>")
def get_claim(claim_id: str):
    """GET /api/v2/supplychain/claims/<id> — owner or admin only."""
    from ..dashboard.accounts import ROLE_RANK
    from ..dashboard.auth_api import current_user
    from ..dashboard.verification_store import VerificationStore

    user = current_user()
    if user is None:
        from ..dashboard.auth_api import _unauthorized

        return _unauthorized()

    record = VerificationStore().get_claim(claim_id)
    if record is None:
        return _err(f"Unknown claim '{claim_id}'", 404)
    if record["user_id"] != user["id"] and ROLE_RANK.get(user["role"], 0) < ROLE_RANK["admin"]:
        return _err("You do not have access to this claim", 403)
    return jsonify(record)
