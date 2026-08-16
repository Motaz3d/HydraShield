"""
Ignition / exposure / vulnerability / access intelligence (real OSM data).

Uses the OpenStreetMap Overpass API (free, no key) to answer, transparently
and without merging anything into the risk score:

    - Is anything exposed here?        (buildings within radius)
    - Are vulnerable assets nearby?    (hospitals, schools, fire stations,
                                        power facilities)
    - Is the area accessible?          (road network, major roads)
    - Is this a potential WUI?         (buildings + burnable land cover)
    - Are there water resources?       (surface water features)

Honesty rules:
    - OSM completeness varies by region — counts are "mapped features",
      declared as a limitation, never ground truth.
    - The block is reported separately from the risk score (hazard) — it is
      NOT folded into the 0-100 composite.
    - When Overpass is unreachable the whole block is reported unavailable.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Dict, Optional

from .cache import cached
from .real_data import _UA

TTL_EXPOSURE = 7 * 24 * 3600.0  # mapped features change slowly
_OHSOME_URL = "https://api.ohsome.org/v1/elements/count"
_OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]

# Category -> (ohsome filter, Overpass selector) — same order for parsing.
_CATEGORIES = [
    ("hospitals", "amenity=hospital", 'node["amenity"="hospital"]'),
    ("schools", "amenity=school", 'node["amenity"="school"]'),
    ("fire_stations", "amenity=fire_station", 'node["amenity"="fire_station"]'),
    ("power_facilities", "power in (substation,plant)",
     'node["power"~"substation|plant"]'),
    ("buildings", "building=*", 'way["building"]'),
    ("roads_all", "highway=*", 'way["highway"]'),
    ("roads_major", "highway in (motorway,trunk,primary,secondary)",
     'way["highway"~"^(motorway|trunk|primary|secondary)$"]'),
    ("water_features", "natural=water", 'way["natural"="water"]'),
    ("waterways", "waterway=*", 'way["waterway"]'),
]


def _post_overpass(query: str, timeout: float = 20.0) -> Dict:
    """POST to the Overpass API (several public instances, in order)."""
    body = urllib.parse.urlencode({"data": query}).encode("utf-8")
    last_exc: Optional[Exception] = None
    for url in _OVERPASS_URLS:
        try:
            req = urllib.request.Request(url, data=body, headers={"User-Agent": _UA})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            last_exc = exc
    raise RuntimeError(f"Overpass unavailable on all instances: {last_exc}")


def _fetch_counts_ohsome(lat: float, lon: float, radius_m: int,
                         timeout: float = 15.0) -> Dict:
    """
    Count OSM features via the ohsome API (designed for aggregations; the
    OSM extract lags a few weeks — the count date is reported honestly).
    Raises on failure so the caller can fall back.
    """
    from datetime import date, timedelta

    # The ohsome extract lags real time; use a date comfortably inside the
    # window (the API reports the exact valid range when out of bounds).
    count_date = (date.today() - timedelta(days=30)).isoformat()
    counts: Dict[str, int] = {}
    for name, ohsome_filter, _sel in _CATEGORIES:
        body = urllib.parse.urlencode({
            "bcircles": f"{lon},{lat},{radius_m}",
            "filter": ohsome_filter,
            "time": count_date,
        }).encode("utf-8")
        req = urllib.request.Request(
            _OHSOME_URL, data=body, headers={"User-Agent": _UA}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        result = (data.get("result") or [{}])[0]
        counts[name] = int(result.get("value") or 0)
    return {"counts": counts, "count_date": count_date,
            "source": "OpenStreetMap via ohsome API (Heidelberg Institute)"}


def _fetch_counts_overpass(lat: float, lon: float, radius_m: int) -> Dict:
    """Count OSM features via one Overpass union query (fallback path)."""
    parts = []
    for _name, _filter, selector in _CATEGORIES:
        parts.append(f"{selector}(around:{radius_m},{lat},{lon});out count;")
    query = f"[out:json][timeout:30];{''.join(parts)}"
    data = _post_overpass(query)
    elements = data.get("elements") or []
    counts: Dict[str, int] = {}
    for i, (name, _f, _sel) in enumerate(_CATEGORIES):
        total = 0
        if i < len(elements):
            try:
                total = int((elements[i].get("tags") or {}).get("total", 0))
            except (TypeError, ValueError):
                total = 0
        counts[name] = total
    return {"counts": counts, "count_date": None,
            "source": "OpenStreetMap (Overpass API)"}


@cached("osm_exposure", TTL_EXPOSURE)
def fetch_osm_context(lat: float, lon: float, radius_m: int = 2000) -> Dict:
    """
    Count mapped OSM features around a point.

    Primary source: ohsome API (fast, aggregation-designed). Fallback:
    Overpass union query across several public instances. Returns
    per-category counts of *mapped* features (declared: OSM completeness
    varies) or an honest error. Cached 7 days.
    """
    lat, lon = float(lat), float(lon)
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return {"error": "Coordinates out of range"}
    radius_m = max(250, min(int(radius_m), 5000))

    errors = []
    for fetcher in (_fetch_counts_ohsome, _fetch_counts_overpass):
        try:
            out = fetcher(lat, lon, radius_m)
            out.update({
                "radius_m": radius_m,
                "note": "Counts are mapped OSM features; OSM completeness "
                        "varies by region.",
            })
            return out
        except Exception as exc:
            errors.append(str(exc))
    return {"error": "OpenStreetMap context unavailable: " + " | ".join(errors)}


# --------------------------------------------------------------------------
# Derived assessment (transparent, declared thresholds, not in the score)
# --------------------------------------------------------------------------

def build_exposure_block(analysis: Dict, radius_m: int = 2000) -> Dict:
    """
    Merge real OSM context with the analysis' land cover and terrain into a
    transparent exposure / vulnerability / access assessment.
    """
    loc = analysis.get("location") or {}
    lat, lon = loc.get("latitude"), loc.get("longitude")
    landcover = analysis.get("landcover") or {}
    terrain = analysis.get("terrain") or {}
    burnable = landcover.get("burnable", True) if "error" not in landcover else True
    slope = terrain.get("slope_degrees") if "error" not in terrain else None

    if lat is None or lon is None:
        return {"status": "unavailable", "reason": "no coordinates"}

    ctx = fetch_osm_context(lat, lon, radius_m)
    if "error" in ctx:
        return {
            "status": "unavailable",
            "reason": ctx["error"],
            "provenance": {
                "kind": "unavailable",
                "source": "OpenStreetMap (ohsome / Overpass)",
                "quality": "missing",
                "limitations": ctx["error"],
            },
        }

    c = ctx["counts"]
    buildings = c.get("buildings", 0)
    vulnerable = {
        "hospitals": c.get("hospitals", 0),
        "schools": c.get("schools", 0),
        "fire_stations": c.get("fire_stations", 0),
        "power_facilities": c.get("power_facilities", 0),
    }
    n_vulnerable = sum(vulnerable.values())

    exposure_level = ("none mapped" if buildings == 0 else
                      "low" if buildings < 20 else
                      "moderate" if buildings < 100 else "high")

    major_road = c.get("roads_major", 0) > 0
    road_count = c.get("roads_all", 0)
    limited_access = road_count < 5
    access_constraints = []
    if limited_access:
        access_constraints.append(
            f"sparse mapped road network ({road_count} ways within {ctx['radius_m']} m)"
        )
    if not major_road:
        access_constraints.append("no major road mapped within the radius")
    if slope is not None and slope >= 12.0:
        access_constraints.append(f"steep terrain ({slope:.1f}°)")

    wui = buildings >= 20 and burnable
    water_features = c.get("water_features", 0) + c.get("waterways", 0)

    return {
        "status": "ok",
        "radius_m": ctx["radius_m"],
        "exposure": {
            "buildings_mapped": buildings,
            "level": exposure_level,
            "note": "Mapped OSM buildings; not a census of structures.",
        },
        "vulnerable_assets": {
            **vulnerable,
            "total": n_vulnerable,
            "note": "Mapped critical facilities within the radius.",
        },
        "access": {
            "roads_mapped": road_count,
            "major_road_nearby": major_road,
            "constraints": access_constraints,
            "limited": bool(access_constraints),
        },
        "water_resources": {
            "features_mapped": water_features,
            "note": "Mapped surface-water features; availability for suppression "
                    "is not implied.",
        },
        "wui_indicator": {
            "potential_wui": wui,
            "note": ("Mapped buildings adjacent to burnable land cover."
                     if wui else
                     "No mapped wildland-urban interface signal at this radius."
                     if not burnable else
                     "Few mapped buildings near burnable land cover."),
        },
        "separate_from_score_note": "Exposure/vulnerability/access are reported "
                                    "separately and are NOT part of the 0-100 "
                                    "risk score.",
        "provenance": {
            "kind": "observed",
            "source": ctx["source"],
            "resolution": f"features within {ctx['radius_m']} m",
            "quality": "ok",
            "limitations": ctx["note"],
        },
    }
