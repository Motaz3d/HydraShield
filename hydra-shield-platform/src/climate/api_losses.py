"""
/api/v2 losses blueprint — Loss Data Registry (additive; does not change
any existing endpoint).

Exposes:

- ``GET /api/v2/losses``         — the full loss summary (observed / estimated /
  modelled / projected strictly separated; observed now carries real documented
  figures from integrated free sources when available)
- ``GET /api/v2/losses/summary`` — flat headline loss figures (public,
  read-only): ``{"status":"ok","items":[{"label","value","unit","source",
  "reference_period"}...],"disclaimer"}``
- ``GET /api/v2/losses/sources`` — the registry source records (integrated,
  planned and candidate) with access and licence conditions
- ``GET /api/v2/losses/estimate?lat&lon(&radius_km=)`` — the Talaix loss
  screening ESTIMATE for a point: computed exposed-value range from the real
  mapped building count (exposure engine) and declared benchmarks; strictly
  separated from documented figures (ESTIMATED, never merged)

The blueprint is deliberately NOT registered here — the lead registers it
in ``src/dashboard/api.py``.

Honesty contract: every served figure is documented with source,
reference_period, geographic scope and licence note; no figure is invented.
"""

from __future__ import annotations

from flask import Blueprint, jsonify

from .api_v2 import _err, _rate

losses_bp = Blueprint("losses", __name__, url_prefix="/api/v2")

_RATE_MAX = 20
_RATE_WINDOW = 60.0


@losses_bp.get("/losses")
def losses():
    """Loss summary: /api/v2/losses

    Observed losses now include real documented figures from integrated free
    sources when available; estimated / modelled / projected each remain
    not_available. The registry metadata and the strict-separation note are
    included.
    """
    if not _rate("v2losses", _RATE_MAX, _RATE_WINDOW):
        return _err("Rate limit exceeded", 429)

    from .losses import loss_summary

    payload = loss_summary()
    if "error" in payload:
        return _err(payload["error"], 500)
    return jsonify(payload)


@losses_bp.get("/losses/summary")
def losses_summary():
    """Flat headline loss figures: /api/v2/losses/summary

    Returns the homepage contract:
        {"status":"ok","items":[{"label":str,"value":str,"unit":str,
         "source":str,"reference_period":str}...],"disclaimer":str}
    or {"status":"unavailable","items":[],"disclaimer":str} when no
    documented figures are available.
    """
    if not _rate("v2lossessummary", _RATE_MAX, _RATE_WINDOW):
        return _err("Rate limit exceeded", 429)

    from .losses import loss_summary_items

    payload = loss_summary_items()
    return jsonify(payload)


@losses_bp.get("/losses/estimate")
def losses_estimate():
    """Talaix loss screening estimate: /api/v2/losses/estimate?lat&lon

    Computes the ESTIMATED exposed-value range for a point from the real
    mapped building count (economic exposure engine, OSM/ohsome) and the
    declared benchmarks in config/loss_estimate_benchmarks.json. The
    expected-loss slot is honestly not_available (no validated damage-ratio
    model integrated). ESTIMATED — never merged with documented figures.
    """
    if not _rate("v2lossesestimate", _RATE_MAX, _RATE_WINDOW):
        return _err("Rate limit exceeded", 429)

    from flask import request

    from .exposure_econ import build_economic_exposure
    from .loss_estimate import enriched_estimate

    try:
        lat = float(request.args.get("lat", ""))
        lon = float(request.args.get("lon", ""))
    except ValueError:
        return _err("Provide ?lat=...&lon=...", 400)
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return _err("Coordinates out of range", 400)
    try:
        radius_km = float(request.args.get("radius_km", "5"))
    except ValueError:
        radius_km = 5.0
    depth_raw = request.args.get("depth_m")
    depth_m = None
    if depth_raw is not None:
        try:
            depth_m = float(depth_raw)
        except ValueError:
            return _err("depth_m must be a number", 400)

    exposure = build_economic_exposure(lat, lon, radius_km=radius_km)
    if "error" in exposure:
        return jsonify({
            "status": "unavailable",
            "reason": f"exposure engine: {exposure['error']}",
            "claim_status": "ESTIMATED",
        })
    buildings = ((exposure.get("exposure") or {}).get("buildings") or {}).get("count")
    src = ((exposure.get("exposure") or {}).get("buildings") or {}).get("source")
    payload = enriched_estimate(
        lat, lon, buildings,
        buildings_source=src or "economic exposure engine (OSM/ohsome)",
        radius_m=(exposure.get("radius_km") or 0) * 1000 or None,
        depth_m=depth_m)
    payload["location"] = {"lat": lat, "lon": lon}
    return jsonify(payload)


@losses_bp.get("/losses/sources")
def losses_sources():
    """Loss-data source registry: /api/v2/losses/sources

    The registry's source records (integrated, planned and candidate) with
    provider, official URL, access mode, licence note, coverage and status.
    """
    if not _rate("v2lossessources", _RATE_MAX, _RATE_WINDOW):
        return _err("Rate limit exceeded", 429)

    from .losses import load_loss_registry

    registry = load_loss_registry()
    sources = registry.get("sources") or []
    statuses = {"integrated": [], "planned": [], "candidate": []}
    for src in sources:
        statuses.get(src.get("status"), []).append(src.get("id"))
    return jsonify({
        "sources": sources,
        "source_count": len(sources),
        "registry": {
            "registry_id": registry.get("registry_id"),
            "version": registry.get("version"),
            "config": "config/loss_registry.json",
        },
        "integrated": statuses["integrated"],
        "planned": statuses["planned"],
        "candidate": statuses["candidate"],
        "note": "Sources are integrated only when wired into a real pipeline; "
                "planned sources await commercial licences; candidates are "
                "reviewed entry points. Access and licence conditions are "
                "stated per source; no invented figures are served.",
    })
