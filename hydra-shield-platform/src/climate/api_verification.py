"""
/api/v2/verification — Green Finance Verification API.

Registered from ``src/dashboard/api.py::create_app()``. Provides per-asset
physical climate-risk verification, evidence PDF reports and portfolio batch
checks, all backed by the hazard registry and the evidence ontology.
"""

from __future__ import annotations

from typing import Any, Dict, List

from flask import Blueprint, Response, jsonify, request

verification = Blueprint("verification", __name__, url_prefix="/api/v2/verification")


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
# Asset verification
# -----------------------------------------------------------------------------


@verification.get("/asset")
def asset_verification():
    """GET /api/v2/verification/asset?lat=&lon=&name="""
    if not _rate("v2verification_asset", 20, 60.0):
        return _err("Rate limit exceeded", 429)

    lat, lon, err = _parse_latlon(request.args)
    if err:
        return _err(err, 400)
    name = request.args.get("name") or None

    from .verification import verify_asset

    return jsonify(verify_asset(lat, lon, name=name))


# -----------------------------------------------------------------------------
# Evidence PDF report
# -----------------------------------------------------------------------------


@verification.get("/report")
def verification_report():
    """GET /api/v2/verification/report?lat=&lon=&name= — PDF evidence report."""
    if not _rate("v2verification_report", 10, 60.0):
        return _err("Rate limit exceeded", 429)

    lat, lon, err = _parse_latlon(request.args)
    if err:
        return _err(err, 400)
    name = request.args.get("name") or None

    from .verification import verify_asset
    from ..dashboard.verification_report import build_verification_pdf

    verification_result = verify_asset(lat, lon, name=name)
    try:
        pdf = build_verification_pdf(verification_result)
    except RuntimeError as exc:
        return _err(f"Report generation unavailable: {exc}", 503)
    except Exception as exc:
        return _err(f"Report generation failed: {exc}", 502)

    safe = "".join(c if c.isalnum() else "_" for c in (name or f"{lat}_{lon}"))[:40]
    return Response(
        pdf,
        mimetype="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="talaix_verification_{safe}.pdf"',
            "Cache-Control": "no-store",
        },
    )


# -----------------------------------------------------------------------------
# Portfolio batch check
# -----------------------------------------------------------------------------


def _trim_result(result: Dict[str, Any]) -> Dict[str, Any]:
    """Light response shape for portfolio results: no full evidence lists."""
    verification = result.get("verification") if result.get("ok") else None
    labels: Dict[str, str] = {}
    if verification:
        for c in verification.get("hazard_checks", []):
            lvl = c.get("level") or {}
            if lvl.get("label"):
                labels[c.get("hazard", "unknown")] = lvl["label"]
    return {
        "asset": result.get("asset"),
        "ok": result.get("ok"),
        "error": result.get("error") if not result.get("ok") else None,
        "verification_id": verification.get("verification_id") if verification else None,
        "summary": verification.get("summary") if verification else None,
        "hazard_levels": labels,
    }


@verification.post("/portfolio")
@_registered_gate
def portfolio_verification():
    """POST /api/v2/verification/portfolio — batch check (registered+)."""
    if not _rate("v2verification_portfolio", 6, 60.0):
        return _err("Rate limit exceeded", 429)

    from ..dashboard.auth_api import current_user
    from ..dashboard.accounts import ROLE_RANK
    from ..dashboard.verification_store import VerificationStore
    from .verification import verify_portfolio

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

    validated_assets: List[Dict[str, Any]] = []
    for idx, asset in enumerate(assets):
        if not isinstance(asset, dict):
            return _err(f"asset at index {idx} must be an object", 400)
        validated_assets.append({
            "name": (asset.get("name") or "").strip() or None,
            "lat": asset.get("lat"),
            "lon": asset.get("lon"),
        })

    results = verify_portfolio(validated_assets)
    portfolio_id = VerificationStore().save_portfolio(
        user_id=user["id"],
        name=name,
        assets=validated_assets,
        results=results,
    )

    ok_count = sum(1 for r in results if r.get("ok"))
    return jsonify({
        "portfolio_id": portfolio_id,
        "count": len(results),
        "ok_count": ok_count,
        "results": [_trim_result(r) for r in results],
    })


@verification.get("/portfolio/<portfolio_id>")
def get_portfolio(portfolio_id: str):
    """GET /api/v2/verification/portfolio/<id> — owner or admin only."""
    from ..dashboard.auth_api import current_user
    from ..dashboard.accounts import ROLE_RANK
    from ..dashboard.verification_store import VerificationStore

    user = current_user()
    if user is None:
        from ..dashboard.auth_api import _unauthorized

        return _unauthorized()

    record = VerificationStore().get_portfolio(portfolio_id)
    if record is None:
        return _err(f"Unknown portfolio '{portfolio_id}'", 404)
    if record["user_id"] != user["id"] and ROLE_RANK.get(user["role"], 0) < ROLE_RANK["admin"]:
        return _err("You do not have access to this portfolio", 403)
    return jsonify(record)
