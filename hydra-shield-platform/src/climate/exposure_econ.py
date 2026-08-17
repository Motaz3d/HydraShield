"""
Economic Exposure layer (docs/ECONOMIC_INTELLIGENCE.md).

Builds the structured exposure profile for a location from REAL mapped
data — no monetary figures, no invented losses:

    - OSM/ohsome feature counts (buildings, critical facilities, roads,
      water, power) via the existing ``src/dashboard/exposure.py`` layer.
    - ESA WorldCover land-cover classes (agriculture, built-up) via
      ``src/gis_mapping/landcover.py``.
    - A small set of additional OSM sector counts (tourism, industry)
      following exposure.py's ohsome/Overpass query pattern.

Norms (absolute):

    - ``monetary_quantification`` is ALWAYS ``not_quantified`` with the
      exact statement below, until a documented valuation dataset with a
      stated method is integrated.
    - Every category reports what was counted, from which dataset, with the
      completeness caveat ("OpenStreetMap completeness varies by region").
    - Categories that existing helpers cannot map cheaply are reported
      ``not_mapped`` honestly — never filled with invented numbers.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

from ..dashboard import exposure as _exposure
from ..dashboard.cache import cached
from ..gis_mapping.landcover import fetch_landcover
from .evidence import EvidenceRecord, content_hash
from .ontology import Confidence

TTL_ECON_EXPOSURE = 7 * 24 * 3600.0  # mapped features change slowly

#: Exact statement required by the no-fake-money rule (doc §3).
NOT_QUANTIFIED_STATEMENT = (
    "Economic exposure cannot currently be quantified from available data."
)

OSM_COMPLETENESS_CAVEAT = (
    "Counts are mapped OpenStreetMap features; OSM completeness varies by "
    "region, so counts are a lower bound, not a census."
)

_ANALYSIS_WINDOW = "current conditions (mapped features at fetch time)"

#: WorldCover classes that indicate agricultural / built-up exposure.
_CROPLAND_CLASS = 40
_BUILTUP_CLASS = 50

# Extra sector categories (ohsome filter, Overpass selector) — same query
# pattern as src/dashboard/exposure.py, kept separate so the existing
# exposure block is untouched.
_SECTOR_CATEGORIES = [
    ("tourism_features",
     "tourism in (hotel,hostel,guest_house,attraction,museum,viewpoint)",
     'nwr["tourism"~"^(hotel|hostel|guest_house|attraction|museum|viewpoint)$"]'),
    ("industrial_areas", "landuse=industrial", 'nwr["landuse"="industrial"]'),
]


def _fetch_sector_counts_ohsome(lat: float, lon: float, radius_m: int,
                                timeout: float = 15.0) -> Dict:
    """ohsome counts for the sector categories (same pattern as exposure.py)."""
    from datetime import date, timedelta

    count_date = (date.today() - timedelta(days=30)).isoformat()
    counts: Dict[str, int] = {}
    for name, ohsome_filter, _sel in _SECTOR_CATEGORIES:
        body = urllib.parse.urlencode({
            "bcircles": f"{lon},{lat},{radius_m}",
            "filter": ohsome_filter,
            "time": count_date,
        }).encode("utf-8")
        req = urllib.request.Request(
            _exposure._OHSOME_URL, data=body,
            headers={"User-Agent": _exposure._UA},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        result = (data.get("result") or [{}])[0]
        counts[name] = int(result.get("value") or 0)
    return {"counts": counts, "count_date": count_date,
            "source": "OpenStreetMap via ohsome API (Heidelberg Institute)"}


def _fetch_sector_counts_overpass(lat: float, lon: float, radius_m: int) -> Dict:
    """Overpass fallback for the sector categories (union count query)."""
    parts = []
    for _name, _filter, selector in _SECTOR_CATEGORIES:
        parts.append(f"{selector}(around:{radius_m},{lat},{lon});out count;")
    query = f"[out:json][timeout:30];{''.join(parts)}"
    data = _exposure._post_overpass(query)
    elements = data.get("elements") or []
    counts: Dict[str, int] = {}
    for i, (name, _f, _sel) in enumerate(_SECTOR_CATEGORIES):
        total = 0
        if i < len(elements):
            try:
                total = int((elements[i].get("tags") or {}).get("total", 0))
            except (TypeError, ValueError):
                total = 0
        counts[name] = total
    return {"counts": counts, "count_date": None,
            "source": "OpenStreetMap (Overpass API)"}


def _fetch_sector_counts(lat: float, lon: float, radius_m: int) -> Optional[Dict]:
    """Best-effort sector counts; None when every upstream path failed."""
    for fetcher in (_fetch_sector_counts_ohsome, _fetch_sector_counts_overpass):
        try:
            return fetcher(lat, lon, radius_m)
        except Exception:
            continue
    return None


def _not_mapped(reason: str, source: str) -> Dict[str, Any]:
    return {
        "status": "not_mapped",
        "count": None,
        "reason": reason,
        "source": source,
        "completeness_caveat": OSM_COMPLETENESS_CAVEAT,
        "analysis_window": _ANALYSIS_WINDOW,
    }


def _osm_category(count: int, description: str,
                  source: str, extra: Optional[Dict[str, Any]] = None) -> Dict:
    out = {
        "status": "mapped",
        "count": count,
        "description": description,
        "source": source,
        "completeness_caveat": OSM_COMPLETENESS_CAVEAT,
        "analysis_window": _ANALYSIS_WINDOW,
    }
    if extra:
        out.update(extra)
    return out


def _landcover_categories(lc: Dict) -> Dict[str, Dict]:
    """Agriculture + built-up exposure from ESA WorldCover class fractions."""
    source = lc.get("source", "ESA WorldCover 10m 2021 v200")
    caveat = ("10 m land-cover classification; class fractions within the "
              "fetch window, not a cadastral survey.")
    if "error" in lc:
        reason = lc["error"]
        return {
            "agriculture": {
                "status": "not_mapped", "count": None, "reason": reason,
                "source": source, "completeness_caveat": caveat,
                "analysis_window": _ANALYSIS_WINDOW,
            },
            "built_up": {
                "status": "not_mapped", "count": None, "reason": reason,
                "source": source, "completeness_caveat": caveat,
                "analysis_window": _ANALYSIS_WINDOW,
            },
        }
    hist = lc.get("histogram") or {}
    cropland = hist.get(_CROPLAND_CLASS, {})
    builtup = hist.get(_BUILTUP_CLASS, {})
    return {
        "agriculture": {
            "status": "mapped",
            "count": None,
            "cropland_fraction": cropland.get("fraction", 0.0),
            "description": "ESA WorldCover 'Cropland' class fraction within "
                           "the fetch window.",
            "source": source,
            "resolution": lc.get("resolution", "10 m"),
            "completeness_caveat": caveat,
            "analysis_window": _ANALYSIS_WINDOW,
        },
        "built_up": {
            "status": "mapped",
            "count": None,
            "built_up_fraction": builtup.get("fraction", 0.0),
            "description": "ESA WorldCover 'Built-up' class fraction within "
                           "the fetch window.",
            "source": source,
            "resolution": lc.get("resolution", "10 m"),
            "completeness_caveat": caveat,
            "analysis_window": _ANALYSIS_WINDOW,
        },
    }


@cached("econ_exposure", TTL_ECON_EXPOSURE)
def build_economic_exposure(
    lat: float,
    lon: float,
    radius_km: float = 5.0,
    hazard_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build the economic exposure profile for a location.

    Returns the structured exposure block of docs/ECONOMIC_INTELLIGENCE.md
    §5. Monetary quantification is always ``not_quantified`` — see
    ``NOT_QUANTIFIED_STATEMENT``. Cached 7 days (mapped features change
    slowly).
    """
    lat, lon = float(lat), float(lon)
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return {"error": "Coordinates out of range"}
    try:
        radius_km = float(radius_km)
    except (TypeError, ValueError):
        radius_km = 5.0
    radius_m = max(250, min(int(radius_km * 1000), 5000))  # ohsome/Overpass cap

    ctx = _exposure.fetch_osm_context(lat, lon, radius_m)
    lc = fetch_landcover(lat, lon)
    evidence: List[Dict[str, Any]] = []

    if "error" in ctx:
        reason = ctx["error"]
        osm_source = "OpenStreetMap (ohsome / Overpass)"
        categories = {
            "population": _not_mapped(reason, osm_source),
            "buildings": _not_mapped(reason, osm_source),
            "critical_facilities": _not_mapped(reason, osm_source),
            "transport": _not_mapped(reason, osm_source),
            "energy": _not_mapped(reason, osm_source),
            "water": _not_mapped(reason, osm_source),
        }
        evidence.append(EvidenceRecord.unknown(
            "OpenStreetMap (ohsome / Overpass)",
            why=reason,
            location={"lat": lat, "lon": lon},
        ).to_dict())
    else:
        c = ctx.get("counts") or {}
        src = ctx.get("source", "OpenStreetMap (ohsome / Overpass)")
        buildings = c.get("buildings", 0)
        facilities = {
            "hospitals": c.get("hospitals", 0),
            "schools": c.get("schools", 0),
            "fire_stations": c.get("fire_stations", 0),
        }
        categories = {
            "population": {
                "status": "proxy",
                "count": None,
                "proxy_basis": "OSM mapped-building count; no population grid "
                               "is integrated, so population is reported as a "
                               "labelled proxy only.",
                "buildings_mapped": buildings,
                "source": src,
                "completeness_caveat": OSM_COMPLETENESS_CAVEAT,
                "analysis_window": _ANALYSIS_WINDOW,
            },
            "buildings": _osm_category(
                buildings, "Mapped OSM buildings within the radius.", src),
            "critical_facilities": _osm_category(
                sum(facilities.values()),
                "Mapped OSM critical facilities (hospitals, schools, fire "
                "stations) within the radius.", src,
                extra={"breakdown": facilities}),
            "transport": _osm_category(
                c.get("roads_all", 0),
                "Mapped OSM road ways within the radius.", src,
                extra={"major_roads_mapped": c.get("roads_major", 0)}),
            "energy": _osm_category(
                c.get("power_facilities", 0),
                "Mapped OSM power facilities (substations, plants) within the "
                "radius.", src),
            "water": _osm_category(
                c.get("water_features", 0) + c.get("waterways", 0),
                "Mapped OSM surface-water features and waterways within the "
                "radius.", src),
        }
        ev_kw: Dict[str, Any] = {}
        if ctx.get("count_date"):
            ev_kw["reference_period"] = {"start": ctx["count_date"],
                                         "end": ctx["count_date"]}
        evidence.append(EvidenceRecord.open_data(
            src,
            dataset="OpenStreetMap feature counts",
            provider_url="https://api.ohsome.org/" if "ohsome" in src
            else "https://overpass-api.de/",
            location={"lat": lat, "lon": lon},
            method=f"feature counts within {radius_m} m radius",
            resolution=f"{radius_m} m analysis radius",
            confidence=Confidence.MEDIUM.value,
            limitations=OSM_COMPLETENESS_CAVEAT,
            content_hash=content_hash(c),
            **ev_kw,
        ).to_dict())

    categories.update(_landcover_categories(lc))
    if "error" not in lc:
        evidence.append(EvidenceRecord.open_data(
            lc.get("source", "ESA WorldCover 10m 2021 v200"),
            dataset="ESA WorldCover 2021 v200 land-cover classes",
            provider_url="https://esa-worldcover.org/en",
            location={"lat": lat, "lon": lon},
            method="class fractions within the fetch window",
            resolution=lc.get("resolution", "10 m"),
            confidence=Confidence.MEDIUM.value,
            limitations="10 m classification; not a cadastral survey.",
            content_hash=content_hash(lc.get("histogram") or {}),
        ).to_dict())

    # Sector categories (tourism, industry) — cheap OSM counts following the
    # exposure.py query pattern; not_mapped honestly when unavailable.
    sector = _fetch_sector_counts(lat, lon, radius_m)
    if sector is None:
        categories["tourism"] = _not_mapped(
            "OSM sector counts unavailable (ohsome and Overpass both failed).",
            "OpenStreetMap (ohsome / Overpass)")
        categories["industry"] = _not_mapped(
            "OSM sector counts unavailable (ohsome and Overpass both failed).",
            "OpenStreetMap (ohsome / Overpass)")
    else:
        sc = sector.get("counts") or {}
        ssrc = sector.get("source", "OpenStreetMap (ohsome / Overpass)")
        categories["tourism"] = _osm_category(
            sc.get("tourism_features", 0),
            "Mapped OSM tourism features (hotels, attractions, museums, "
            "viewpoints) within the radius.", ssrc)
        categories["industry"] = _osm_category(
            sc.get("industrial_areas", 0),
            "Mapped OSM industrial landuse areas within the radius.", ssrc)

    # Framework-stage categories: declared, never populated with inventions.
    categories["ports_logistics"] = {
        "status": "not_mapped",
        "count": None,
        "reason": "Foundation stage — requires dedicated port/logistics "
                  "mapping not yet integrated.",
        "source": None,
        "completeness_caveat": None,
        "analysis_window": _ANALYSIS_WINDOW,
    }
    categories["supply_chain"] = {
        "status": "not_mapped",
        "count": None,
        "reason": "Framework slot — declared data gap (requires sector "
                  "composition data not integrated).",
        "source": None,
        "completeness_caveat": None,
        "analysis_window": _ANALYSIS_WINDOW,
    }

    result: Dict[str, Any] = {
        "location": {"lat": lat, "lon": lon},
        "radius_km": round(radius_m / 1000.0, 3),
        "analysis_window": _ANALYSIS_WINDOW,
        "exposure": categories,
        "hazard_context": hazard_context if hazard_context is not None else {
            "status": "not_provided",
            "note": "No hazard analysis was supplied; the exposure profile is "
                    "hazard-agnostic (current mapped conditions).",
        },
        "monetary_quantification": {
            "status": "not_quantified",
            "statement": NOT_QUANTIFIED_STATEMENT,
            "note": "No documented valuation dataset with a stated method is "
                    "integrated; the structured exposure profile above is "
                    "provided instead (docs/ECONOMIC_INTELLIGENCE.md §3).",
        },
        "framework": {
            "physical_risk": "exposure-profile stage",
            "transition_risk": "framework slot — no data",
            "business_interruption": "qualitative",
            "supply_chain": "framework slot — no data",
        },
        "provenance": {
            "kind": "observed",
            "source": "HydraShield economic exposure layer: OSM/ohsome + "
                      "Overpass feature counts, ESA WorldCover land cover",
            "quality": "mapped features; completeness varies by region",
            "limitations": OSM_COMPLETENESS_CAVEAT,
            "evidence": evidence,
        },
    }
    return result
