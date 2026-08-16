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
_OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

# Category -> Overpass selector (order defines parsing order).
_CATEGORIES = [
    ("hospitals", 'node["amenity"="hospital"]'),
    ("schools", 'node["amenity"="school"]'),
    ("fire_stations", 'node["amenity"="fire_station"]'),
    ("power_facilities", 'node["power"~"substation|plant"]'),
    ("buildings", 'way["building"]'),
    ("roads_all", 'way["highway"]'),
    ("roads_major", 'way["highway"~"^(motorway|trunk|primary|secondary)$"]'),
    ("water_features", 'way["natural"="water"]'),
    ("waterways", 'way["waterway"]'),
]


def _post_overpass(query: str, timeout: float = 35.0) -> Dict:
    """POST to the Overpass API (main instance, then a mirror on failure)."""
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


@cached("osm_exposure", TTL_EXPOSURE)
def fetch_osm_context(lat: float, lon: float, radius_m: int = 2000) -> Dict:
    """
    Count mapped OSM features around a point (one Overpass round-trip).

    Returns per-category counts of *mapped* features (declared: OSM
    completeness varies) or an honest error. Cached 7 days.
    """
    lat, lon = float(lat), float(lon)
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return {"error": "Coordinates out of range"}
    radius_m = max(250, min(int(radius_m), 5000))

    parts = []
    for _name, selector in _CATEGORIES:
        parts.append(f"{selector}(around:{radius_m},{lat},{lon});out count;")
    query = f"[out:json][timeout:30];{''.join(parts)}"

    try:
        data = _post_overpass(query)
    except Exception as exc:
        return {"error": f"OpenStreetMap context unavailable: {exc}"}

    elements = data.get("elements") or []
    counts: Dict[str, int] = {}
    for i, (name, _sel) in enumerate(_CATEGORIES):
        total = 0
        if i < len(elements):
            try:
                total = int((elements[i].get("tags") or {}).get("total", 0))
            except (TypeError, ValueError):
                total = 0
        counts[name] = total

    return {
        "counts": counts,
        "radius_m": radius_m,
        "source": "OpenStreetMap (Overpass API)",
        "note": "Counts are mapped OSM features; OSM completeness varies by region.",
    }


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
                "source": "OpenStreetMap (Overpass API)",
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
