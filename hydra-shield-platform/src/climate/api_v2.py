"""
/api/v2 — multi-hazard platform API (Flask blueprint).

Registered from `src/dashboard/api.py::create_app()`. Existing /api/… v1
contracts are untouched; v2 exposes the hazard registry, per-hazard
analysis, historical events, and (in later stages) exposure/economy/
solutions/accounts.

Honesty contract: every unavailable/key-gated layer says so explicitly —
no fabricated data anywhere in v2.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request

v2 = Blueprint("v2", __name__, url_prefix="/api/v2")


def _err(message: str, status: int):
    return jsonify({"error": message, "status": status}), status


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


# ---------------------------------------------------------------------------
# Hazard registry
# ---------------------------------------------------------------------------


@v2.get("/hazards")
def hazards():
    """The registered hazards. A hazard appears here only when wired to at
    least one real, documented data source — no placeholders."""
    from . import registry

    return jsonify({
        "hazards": registry.descriptors(),
        "note": "A hazard is registered only when backed by a real, documented "
                "data source. Temporal coverage is reported per dataset — the "
                "year selector is built from it, never hardcoded.",
    })


@v2.get("/hazards/<hazard_id>")
def hazard_detail(hazard_id: str):
    from . import registry

    module = registry.get(hazard_id)
    if module is None:
        return _err(f"Unknown hazard '{hazard_id}'. See /api/v2/hazards.", 404)
    d = module.descriptor()
    d["map_layers"] = module.map_layers()
    return jsonify(d)


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------


@v2.get("/analyze")
def analyze():
    """Per-hazard analysis: /api/v2/analyze?hazard=flood&lat=…&lon=…

    ``raw=1`` includes the engine-native payload (wildfire compatibility).
    """
    if not _rate("v2analyze", 30, 60.0):
        return _err("Rate limit exceeded", 429)

    from . import registry

    hazard_id = (request.args.get("hazard") or "wildfire").strip().lower()
    module = registry.get(hazard_id)
    if module is None:
        return _err(f"Unknown hazard '{hazard_id}'. See /api/v2/hazards.", 404)

    lat, lon, err = _parse_latlon(request.args)
    if err:
        return _err(err, 400)
    name = request.args.get("name") or None

    available, reason = module.availability()
    if not available:
        return jsonify({
            "hazard": hazard_id,
            "status": "unavailable",
            "unavailable_reason": reason,
        }), 503

    result = module.analyze(lat, lon, name=name)
    include_raw = request.args.get("raw") == "1"
    return jsonify(result.to_dict(include_raw=include_raw))


# ---------------------------------------------------------------------------
# Historical events
# ---------------------------------------------------------------------------


@v2.get("/events")
def events():
    """Historical events: /api/v2/events?hazard=wildfire&lat=…&lon=…&year=2024

    Years are never hardcoded — request any year; the response states the
    dataset coverage honestly when a year is out of range.
    """
    if not _rate("v2events", 10, 60.0):
        return _err("Rate limit exceeded", 429)

    from . import registry

    hazard_id = (request.args.get("hazard") or "wildfire").strip().lower()
    module = registry.get(hazard_id)
    if module is None:
        return _err(f"Unknown hazard '{hazard_id}'. See /api/v2/hazards.", 404)

    lat, lon, err = _parse_latlon(request.args)
    if err:
        return _err(err, 400)
    try:
        radius_km = float(request.args.get("radius_km", 50.0))
    except (TypeError, ValueError):
        return _err("radius_km must be a number", 400)
    year_raw = request.args.get("year")
    year = None
    if year_raw:
        try:
            year = int(year_raw)
        except ValueError:
            return _err("year must be an integer", 400)

    return jsonify(module.events(lat, lon, radius_km=radius_km, year=year))


@v2.get("/events/<event_id>")
def event_detail(event_id: str):
    """One stored event with its full evidence list ("show me the evidence")."""
    from .events import EventStore

    event = EventStore().get_event(event_id)
    if event is None:
        return _err(f"No stored event '{event_id}'. Events are persisted when "
                    "derived via /api/v2/events.", 404)
    return jsonify(event)


# ---------------------------------------------------------------------------
# Sources (v2 mirror of the registry — same audit trail)
# ---------------------------------------------------------------------------


@v2.get("/sources")
def sources():
    import json as _json
    import os as _os

    registry_path = _os.path.join(
        _os.path.dirname(__file__), "..", "..", "config", "source_registry.json"
    )
    try:
        with open(registry_path, "r", encoding="utf-8") as fh:
            registry_doc = _json.load(fh)
    except (OSError, _json.JSONDecodeError) as exc:
        return _err(f"Source registry unavailable: {exc}", 503)
    return jsonify(registry_doc)
