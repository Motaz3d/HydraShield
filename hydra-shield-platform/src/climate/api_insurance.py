"""
/api/v2/insurance — Insurance Environmental Risk API.

Registered from ``src/dashboard/api.py::create_app()``. Provides per-asset
risk profiles and portfolio checks that combine current hazard levels with
long-term event records.
"""

from __future__ import annotations

from typing import Any, Dict, List

from flask import Blueprint, Response, jsonify, request

insurance = Blueprint("insurance", __name__, url_prefix="/api/v2/insurance")


def _err(message: str, status: int, **extra):
    payload = {"error": message, "status": status}
    payload.update(extra)
    return jsonify(payload), status


def _parse_latlon(args):
    try:
        lat = float(args.get("lat"))
        lon = float(args.get("lon"))
    except (TypeError, ValueError):
        return None, None, "lat and lon must be numbers"
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return None, None, "lat/lon out of range"
    return lat, lon, None


def _rate(key: str, max_requests: int, window: float) -> bool:
    from ..dashboard.api import _client_key, _rate_limiter  # lazy: avoid circulars

    return _rate_limiter.allow(f"{key}:{_client_key()}", max_requests, window)


def _registered_gate(func):
    """Require the 'registered' role; lazy import avoids dashboard load."""
    from ..dashboard.auth_api import require_role

    return require_role("registered")(func)


# -----------------------------------------------------------------------------
# Single-asset profile
# -----------------------------------------------------------------------------


@insurance.get("/profile")
def profile():
    """GET /api/v2/insurance/profile?lat=&lon=&name=&radius_km= """
    if not _rate("v2insurance_profile", 20, 60.0):
        return _err("Rate limit exceeded", 429)

    lat, lon, err = _parse_latlon(request.args)
    if err:
        return _err(err, 400)
    name = request.args.get("name") or None

    radius_raw = request.args.get("radius_km", "50")
    try:
        radius_km = float(radius_raw)
    except (TypeError, ValueError):
        return _err("radius_km must be a number", 400)
    if not (1.0 <= radius_km <= 500.0):
        return _err("radius_km must be between 1 and 500", 400)

    from .insurance import build_risk_profile

    return jsonify(build_risk_profile(lat, lon, name=name, radius_km=radius_km))


@insurance.get("/profile/report")
def profile_report():
    """GET /api/v2/insurance/profile/report?lat=&lon=&name=&radius_km= — PDF."""
    if not _rate("v2insurance_profile_report", 10, 60.0):
        return _err("Rate limit exceeded", 429)

    lat, lon, err = _parse_latlon(request.args)
    if err:
        return _err(err, 400)
    name = request.args.get("name") or None

    radius_raw = request.args.get("radius_km", "50")
    try:
        radius_km = float(radius_raw)
    except (TypeError, ValueError):
        return _err("radius_km must be a number", 400)
    if not (1.0 <= radius_km <= 500.0):
        return _err("radius_km must be between 1 and 500", 400)

    from ..dashboard.insurance_report import build_insurance_pdf
    from .insurance import build_risk_profile

    profile = build_risk_profile(lat, lon, name=name, radius_km=radius_km)

    # Talaix loss screening estimate (ESTIMATED): computed from the real
    # mapped building count (economic exposure engine) and declared
    # benchmarks. Best-effort — the profile and its loss-not-quantified
    # rule are unchanged when this is unavailable.
    loss_estimate_result = None
    try:
        from .exposure_econ import build_economic_exposure
        from .loss_estimate import enriched_estimate

        exposure = build_economic_exposure(lat, lon)
        if "error" not in exposure:
            buildings = ((exposure.get("exposure") or {})
                         .get("buildings") or {}).get("count")
            bsrc = ((exposure.get("exposure") or {})
                    .get("buildings") or {}).get("source")
            loss_estimate_result = enriched_estimate(
                lat, lon, buildings,
                buildings_source=bsrc or "economic exposure engine (OSM/ohsome)",
                radius_m=(exposure.get("radius_km") or 0) * 1000 or None)
    except Exception:
        loss_estimate_result = None

    try:
        pdf = build_insurance_pdf(profile, loss_estimate=loss_estimate_result)
    except RuntimeError as exc:
        return _err(f"Report generation unavailable: {exc}", 503)
    except Exception as exc:
        return _err(f"Report generation failed: {exc}", 502)

    safe = "".join(c if c.isalnum() else "_" for c in (name or f"{lat}_{lon}"))[:40]
    return Response(
        pdf,
        mimetype="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="talaix_insurance_{safe}.pdf"',
            "Cache-Control": "no-store",
        },
    )


# -----------------------------------------------------------------------------
# Portfolio check
# -----------------------------------------------------------------------------


def _normalise_assets(assets: List[Any]) -> List[Dict[str, Any]]:
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


@insurance.post("/portfolio")
@_registered_gate
def portfolio_profile():
    """POST /api/v2/insurance/portfolio — batch profile check."""
    if not _rate("v2insurance_portfolio", 6, 60.0):
        return _err("Rate limit exceeded", 429)

    from ..dashboard.accounts import ROLE_RANK
    from ..dashboard.auth_api import current_user
    from ..dashboard.verification_store import VerificationStore
    from .insurance import build_portfolio_profile

    user = current_user()
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip() or None
    assets = data.get("assets")
    if not isinstance(assets, list):
        return _err("assets must be a list", 400)
    if not assets:
        return _err("assets list is empty", 400)

    max_assets = 100 if ROLE_RANK.get(user["role"], 0) >= ROLE_RANK["subscriber"] else 25
    if len(assets) > max_assets:
        return _err(
            f"Portfolio cannot exceed {max_assets} assets for your tier",
            413,
            upgrade=None if ROLE_RANK.get(user["role"], 0) >= ROLE_RANK["subscriber"] else {
                "required_role": "subscriber",
                "your_role": user["role"],
                "unlocks": "Upgrading to 'subscriber' allows portfolios up to 100 assets.",
            },
        )

    radius_raw = data.get("radius_km", 50.0)
    try:
        radius_km = float(radius_raw)
    except (TypeError, ValueError):
        return _err("radius_km must be a number", 400)
    if not (1.0 <= radius_km <= 500.0):
        return _err("radius_km must be between 1 and 500", 400)

    validated_assets = _normalise_assets(assets)
    if validated_assets is None:
        return _err("assets must be a list of objects", 400)

    results = build_portfolio_profile(validated_assets, radius_km=radius_km)
    portfolio_id = VerificationStore().save_insurance_portfolio(
        user_id=user["id"],
        name=name,
        assets=validated_assets,
        results=results,
    )

    return jsonify({
        "portfolio_id": portfolio_id,
        "count": results["portfolio_summary"]["site_count"],
        "ok_count": results["portfolio_summary"]["ok_count"],
        "portfolio_summary": results["portfolio_summary"],
        "results": results["results"],
    })


@insurance.get("/portfolio/<portfolio_id>")
def get_portfolio(portfolio_id: str):
    """GET /api/v2/insurance/portfolio/<id> — owner or admin only."""
    from ..dashboard.accounts import ROLE_RANK
    from ..dashboard.auth_api import current_user
    from ..dashboard.verification_store import VerificationStore

    user = current_user()
    if user is None:
        from ..dashboard.auth_api import _unauthorized

        return _unauthorized()

    record = VerificationStore().get_insurance_portfolio(portfolio_id)
    if record is None:
        return _err(f"Unknown portfolio '{portfolio_id}'", 404)
    if record["user_id"] != user["id"] and ROLE_RANK.get(user["role"], 0) < ROLE_RANK["admin"]:
        return _err("You do not have access to this portfolio", 403)
    return jsonify(record)
