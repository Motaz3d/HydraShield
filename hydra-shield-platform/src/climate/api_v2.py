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


# ---------------------------------------------------------------------------
# Economic exposure (docs/ECONOMIC_INTELLIGENCE.md)
# ---------------------------------------------------------------------------


def _hazard_context(hazard_id: str, lat: float, lon: float) -> dict:
    """Current level of one hazard as context for the economy endpoint.

    Lazy registry import; hazards that fail (or are unknown) are reported
    honestly in the context block rather than failing the whole request.
    """
    from . import registry

    module = registry.get(hazard_id)
    if module is None:
        return {"hazard": hazard_id, "status": "unavailable",
                "reason": f"Unknown hazard '{hazard_id}'. See /api/v2/hazards."}
    try:
        result = module.analyze(lat, lon)
    except Exception as exc:  # tolerate hazards that fail
        return {"hazard": hazard_id, "status": "unavailable", "reason": str(exc)}
    return {
        "hazard": hazard_id,
        "status": result.status,
        "summary": result.summary,
        "level": result.level.to_dict() if result.level else None,
        "unavailable_reason": result.unavailable_reason,
    }


@v2.get("/economy")
def economy():
    """Economic exposure profile: /api/v2/economy?lat=…&lon=…&radius_km=5

    Structured exposure categories from real mapped data. Monetary
    quantification is always ``not_quantified`` (no documented valuation
    dataset integrated). ``hazard=`` optionally attaches that hazard's
    current level as context.
    """
    if not _rate("v2economy", 20, 60.0):
        return _err("Rate limit exceeded", 429)

    lat, lon, err = _parse_latlon(request.args)
    if err:
        return _err(err, 400)
    try:
        radius_km = float(request.args.get("radius_km", 5.0))
    except (TypeError, ValueError):
        return _err("radius_km must be a number", 400)

    hazard_context = None
    hazard_id = request.args.get("hazard")
    if hazard_id:
        hazard_context = _hazard_context(hazard_id.strip().lower(), lat, lon)

    from .exposure_econ import build_economic_exposure

    return jsonify(build_economic_exposure(
        lat, lon, radius_km=radius_km, hazard_context=hazard_context))


# ---------------------------------------------------------------------------
# Solutions intelligence (docs/SOLUTIONS_INTELLIGENCE.md)
# ---------------------------------------------------------------------------


def _assemble_site(lat: float, lon: float) -> dict:
    """Assemble the solutions engine's site dict from LIGHT cached fetchers
    only (terrain, land cover, OSM exposure counts, recent daily weather).

    Hazard levels are deliberately NOT computed here: the per-hazard
    engines (wildfire in particular) are heavy; call /api/v2/analyze
    per hazard instead. Whatever cannot be fetched is left None — the
    engine reports it in ``insufficient_data``.
    """
    site: dict = {
        "lat": lat,
        "lon": lon,
        "hazards": [],
        "climate_zone": None,
        "moisture_regime": None,
        "elevation_m": None,
        "landcover_classes": None,
        "water_features_count": None,
        "buildings_count": None,
        "historical_events": None,
    }

    try:
        from ..dashboard.real_data import fetch_terrain

        terrain = fetch_terrain(lat, lon)
        if "error" not in terrain:
            site["elevation_m"] = terrain.get("elevation_m")
    except Exception:
        pass

    try:
        from ..gis_mapping.landcover import fetch_landcover

        lc = fetch_landcover(lat, lon)
        if "error" not in lc:
            histogram = lc.get("histogram") or {}
            site["landcover_classes"] = sorted({
                v.get("label") for v in histogram.values() if v.get("label")
            })
    except Exception:
        pass

    try:
        from ..dashboard import exposure as exposure_module

        ctx = exposure_module.fetch_osm_context(lat, lon, 5000)
        if "error" not in ctx:
            counts = ctx.get("counts") or {}
            site["water_features_count"] = (
                counts.get("water_features", 0) + counts.get("waterways", 0))
            site["buildings_count"] = counts.get("buildings", 0)
    except Exception:
        pass

    try:
        from ..dashboard import ecology as ecology_module
        from ..dashboard.real_data import (
            fetch_daily_fire_weather, fetch_weather_current)

        daily = fetch_daily_fire_weather(lat, lon, past_days=21, forecast_days=1)
        if "error" not in daily:
            days = daily.get("days") or []
            tmax = [d["temp_max_c"] for d in days if d.get("temp_max_c") is not None]
            rain = [d["precipitation_mm"] for d in days
                    if d.get("precipitation_mm") is not None]
            climate = {
                "mean_temp_max_c": (sum(tmax) / len(tmax)) if tmax else None,
                "total_precip_mm": sum(rain) if rain else None,
            }
            site["climate_zone"] = ecology_module.classify_climate_zone(
                climate, site["elevation_m"])
            recent_rain = climate["total_precip_mm"]
        else:
            recent_rain = None

        soil_moisture = None
        current = fetch_weather_current(lat, lon)
        if "error" not in current:
            soil_moisture = current.get("soil_moisture_m3m3")
        site["moisture_regime"] = ecology_module.classify_moisture_regime(
            None, soil_moisture, recent_rain)
    except Exception:
        pass

    site["hazards_note"] = (
        "Hazard levels are not computed on this endpoint (light fetchers "
        "only; the per-hazard engines are heavy). Provide hazard context "
        "via /api/v2/analyze?hazard=… — the engine reports the missing "
        "levels in insufficient_data.")
    return site


@v2.get("/solutions")
def solutions():
    """Site-fitted solutions: /api/v2/solutions?lat=…&lon=…

    Assembles the site dict from light cached fetchers and matches the
    curated solutions knowledge base. Hazard levels are not computed on
    this endpoint — callers may declare hazards of interest explicitly via
    ``&hazards=wildfire,drought`` (validated against the registry; basis
    is declared as caller-selected), or use /api/v2/analyze per hazard for
    levelled context. Without hazards the response is the honest
    insufficient-data path.
    """
    if not _rate("v2solutions", 20, 60.0):
        return _err("Rate limit exceeded", 429)

    lat, lon, err = _parse_latlon(request.args)
    if err:
        return _err(err, 400)

    from . import registry, solutions as solutions_module

    site = _assemble_site(lat, lon)

    hazards_param = (request.args.get("hazards") or "").strip()
    if hazards_param:
        selected, unknown = [], []
        for hid in {h.strip().lower() for h in hazards_param.split(",") if h.strip()}:
            if registry.get(hid) is not None:
                selected.append({
                    "id": hid,
                    "level": None,
                    "basis": "caller-selected hazard of interest "
                             "(no level computed on this endpoint)",
                })
            else:
                unknown.append(hid)
        site["hazards"] = selected
        if unknown:
            site["unknown_hazards_requested"] = sorted(unknown)

    return jsonify(solutions_module.recommend_solutions(site))


# ---------------------------------------------------------------------------
# Data Observatory (config/data_registry.json — catalog records)
# ---------------------------------------------------------------------------

_OBSERVATORY_NOTE = (
    "Entries are catalog records — status integrated/candidate/rejected; "
    "nothing here implies the data is wired into analysis unless "
    "status=integrated.")


@v2.get("/registry")
def data_observatory():
    """The Data Observatory: /api/v2/registry?status=…&hazard=…&provider_class=…

    Catalog records of datasets. Filters are exact-match on status and
    provider_class, and membership-match on hazard_relevance for hazard.
    """
    if not _rate("v2registry", 60, 60.0):
        return _err("Rate limit exceeded", 429)

    from . import data_registry

    try:
        entries = data_registry.all()
    except data_registry.RegistryError as exc:
        return _err(f"Data registry unavailable: {exc}", 503)

    status = (request.args.get("status") or "").strip().lower()
    hazard = (request.args.get("hazard") or "").strip().lower()
    provider_class = (request.args.get("provider_class") or "").strip().lower()
    if status:
        if status not in data_registry.VALID_STATUSES:
            return _err(f"Unknown status '{status}'.", 400)
        entries = [e for e in entries if e["status"] == status]
    if hazard:
        entries = [e for e in entries if hazard in e["hazard_relevance"]]
    if provider_class:
        if provider_class not in data_registry.VALID_PROVIDER_CLASSES:
            return _err(f"Unknown provider_class '{provider_class}'.", 400)
        entries = [e for e in entries if e["provider_class"] == provider_class]

    return jsonify({
        "datasets": entries,
        "count": len(entries),
        "filters": {
            "status": status or None,
            "hazard": hazard or None,
            "provider_class": provider_class or None,
        },
        "observatory_note": _OBSERVATORY_NOTE,
    })


@v2.get("/registry/<dataset_id>")
def data_observatory_entry(dataset_id: str):
    """One catalog record by id; honest 404 when unknown."""
    if not _rate("v2registry", 60, 60.0):
        return _err("Rate limit exceeded", 429)

    from . import data_registry

    try:
        entry = data_registry.get(dataset_id)
    except data_registry.RegistryError as exc:
        return _err(f"Data registry unavailable: {exc}", 503)
    if entry is None:
        return _err(f"Unknown dataset '{dataset_id}'. See /api/v2/registry.", 404)
    return jsonify({"dataset": entry, "observatory_note": _OBSERVATORY_NOTE})


# ---------------------------------------------------------------------------
# Model registry (config/model_registry.json)
# ---------------------------------------------------------------------------


@v2.get("/models")
def models():
    """The model registry: immutable records of platform indicators/methods."""
    if not _rate("v2models", 60, 60.0):
        return _err("Rate limit exceeded", 429)

    from . import data_registry

    try:
        entries = data_registry.models_all()
    except data_registry.RegistryError as exc:
        return _err(f"Model registry unavailable: {exc}", 503)
    return jsonify({
        "models": entries,
        "count": len(entries),
        "note": ("Model versions are never edited in place — a new version "
                 "id is added. Validation status is stated per model; "
                 "screening indicators are not validated predictors unless "
                 "their record says so."),
    })


@v2.get("/models/<model_id>")
def model_detail(model_id: str):
    """One model record by id; honest 404 when unknown."""
    if not _rate("v2models", 60, 60.0):
        return _err("Rate limit exceeded", 429)

    from . import data_registry

    try:
        entry = data_registry.models_get(model_id)
    except data_registry.RegistryError as exc:
        return _err(f"Model registry unavailable: {exc}", 503)
    if entry is None:
        return _err(f"Unknown model '{model_id}'. See /api/v2/models.", 404)
    return jsonify(entry)


# ---------------------------------------------------------------------------
# Research registry (config/research_registry.json)
# ---------------------------------------------------------------------------


@v2.get("/research")
def research():
    """The research registry: /api/v2/research?topic=…&pipeline_stage=…"""
    if not _rate("v2research", 60, 60.0):
        return _err("Rate limit exceeded", 429)

    from . import data_registry

    try:
        entries = data_registry.research_all()
    except data_registry.RegistryError as exc:
        return _err(f"Research registry unavailable: {exc}", 503)

    topic = (request.args.get("topic") or "").strip().lower()
    stage = (request.args.get("pipeline_stage") or "").strip().lower()
    if topic:
        entries = [r for r in entries
                   if topic in [str(t).lower() for t in r.get("topics", [])]]
    if stage:
        entries = [r for r in entries if r.get("pipeline_stage") == stage]

    return jsonify({
        "references": entries,
        "count": len(entries),
        "filters": {"topic": topic or None, "pipeline_stage": stage or None},
        "note": ("A paper never becomes production logic directly: it moves "
                 "through paper → method → prototype → benchmark → "
                 "validation → production (pipeline_stage per entry)."),
    })


@v2.get("/research/<ref_id>")
def research_detail(ref_id: str):
    """One research reference by id; honest 404 when unknown."""
    if not _rate("v2research", 60, 60.0):
        return _err("Rate limit exceeded", 429)

    from . import data_registry

    try:
        entry = data_registry.research_get(ref_id)
    except data_registry.RegistryError as exc:
        return _err(f"Research registry unavailable: {exc}", 503)
    if entry is None:
        return _err(f"Unknown reference '{ref_id}'. See /api/v2/research.", 404)
    return jsonify(entry)


# ---------------------------------------------------------------------------
# Ingestion provider chains (declared scope, single-provider gaps)
# ---------------------------------------------------------------------------


@v2.get("/ingestion/chains")
def ingestion_chains():
    """Declared provider chains per platform variable.

    Chains reference config/data_registry.json ids. Single-provider chains
    are declared gaps, not hidden ones.
    """
    if not _rate("v2ingestion", 60, 60.0):
        return _err("Rate limit exceeded", 429)

    from . import ingestion

    return jsonify(ingestion.chains_payload())
