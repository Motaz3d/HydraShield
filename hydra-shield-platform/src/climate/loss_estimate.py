"""
Talaix Loss Screening Estimate — the ESTIMATED monetary layer
(docs/ECONOMIC_INTELLIGENCE.md §9).

The platform's first monetary function of its own. It COMPUTES an
exposed-value screening range from real engine inputs (mapped building
counts, location) and declared published benchmarks
(``config/loss_estimate_benchmarks.json``): replacement cost per country
and a floor-area-per-building assumption. This is engine work, not quoted
content — nothing here is a figure republished from someone else's
database.

Honesty contract (absolute, same weight as the no-fake-money rule):

- Inputs are either real (OSM mapped building counts with their
  completeness caveats) or declared (benchmarks carry basis notes and
  deliberately wide ranges — declared screening assumptions, never
  presented as valuations).
- The output is an exposed-VALUE range — what could be at stake — NOT an
  expected loss. The expected-loss slot (damage ratio × exposed value) is
  reported ``not_available`` until a validated damage model is integrated
  (JRC depth–damage functions for flood are the documented next step).
- ESTIMATED figures are never merged with DOCUMENTED loss figures; the
  two blocks stay strictly separated everywhere they are served.
- Wide ranges are deliberate: the function reports its own sensitivity
  instead of pretending precision.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from .evidence import utcnow_iso
from .ontology import Confidence

_DEFAULT_CONFIG = os.path.join(
    os.path.dirname(__file__), "..", "..", "config", "loss_estimate_benchmarks.json"
)

EXPECTED_LOSS_STATEMENT = (
    "No validated damage-ratio model is integrated; the exposed value is not "
    "converted into an expected loss. JRC depth–damage functions (flood) are "
    "the documented next step (docs/ECONOMIC_INTELLIGENCE.md §9)."
)

SEPARATION_NOTE = (
    "ESTIMATED figures are computed by the Talaix screening function from "
    "declared benchmarks; they are never merged with DOCUMENTED loss figures "
    "(docs/ECONOMIC_INTELLIGENCE.md §3)."
)


def load_benchmarks(path: str | None = None) -> Dict[str, Any]:
    cfg_path = path or os.environ.get("HYDRASHIELD_LOSS_BENCHMARKS") or _DEFAULT_CONFIG
    with open(cfg_path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def validate_benchmarks(cfg: Dict[str, Any]) -> List[str]:
    """Structural validation; returns a list of problems (empty = valid)."""

    problems: List[str] = []

    def _band(problems_out: List[str], where: str, band: Any) -> None:
        if not isinstance(band, dict):
            problems_out.append(f"{where}: must be an object")
            return
        for field in ("low", "central", "high"):
            if not isinstance(band.get(field), (int, float)):
                problems_out.append(f"{where}: missing numeric {field}")
        if isinstance(band.get("low"), (int, float)) and isinstance(
                band.get("high"), (int, float)) and not band["low"] <= band["central"] <= band["high"]:
            problems_out.append(f"{where}: low <= central <= high violated")
        if not band.get("basis"):
            problems_out.append(f"{where}: missing basis note")

    defaults = cfg.get("defaults") or {}
    _band(problems, "defaults.replacement_cost_per_m2",
          defaults.get("replacement_cost_per_m2"))
    _band(problems, "defaults.floor_area_per_building_m2",
          defaults.get("floor_area_per_building_m2"))

    countries = cfg.get("countries")
    if not isinstance(countries, list) or not countries:
        problems.append("countries must be a non-empty list")
        countries = []
    seen: set = set()
    for i, c in enumerate(countries):
        cid = c.get("code") or f"country {i}"
        if c.get("code") in seen:
            problems.append(f"countries '{cid}': duplicate code")
        seen.add(c.get("code"))
        if not c.get("name"):
            problems.append(f"countries '{cid}': missing name")
        bbox = c.get("bbox")
        if not (isinstance(bbox, list) and len(bbox) == 4
                and all(isinstance(v, (int, float)) for v in bbox)):
            problems.append(f"countries '{cid}': numeric bbox[4] required")
        _band(problems, f"countries '{cid}'.replacement_cost_per_m2",
              c.get("replacement_cost_per_m2"))
    return problems


def _point_in_bbox(lat: float, lon: float, bbox: List[float]) -> bool:
    min_lon, min_lat, max_lon, max_lat = bbox
    return min_lat <= lat <= max_lat and min_lon <= lon <= max_lon


def match_country(lat: float, lon: float,
                  cfg: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """The benchmark country whose bbox contains the point.

    Country bounding boxes overlap (a small country can sit inside a
    neighbour's bbox), so the SMALLEST containing bbox wins — the most
    specific match. Returns the country record or None.
    """
    cfg = cfg if cfg is not None else load_benchmarks()
    best: Optional[tuple] = None
    for country in cfg.get("countries") or []:
        bbox = country.get("bbox")
        if not (isinstance(bbox, list) and len(bbox) == 4):
            continue
        if not _point_in_bbox(lat, lon, bbox):
            continue
        span = abs((bbox[2] - bbox[0]) * (bbox[3] - bbox[1]))
        if best is None or span < best[0]:
            best = (span, country)
    return best[1] if best else None


def estimate_exposed_value(buildings_count: float,
                           cost_band: Dict[str, Any],
                           area_band: Dict[str, Any]) -> Dict[str, Any]:
    """Pure: mapped buildings × floor-area-per-building × cost-per-m2.

    Computes the three bands independently (low×low×low, central³,
    high×high×high) so the range honestly compounds the declared
    uncertainties instead of hiding them.
    """
    def band(key: str) -> float:
        return float(buildings_count) * float(area_band[key]) * float(cost_band[key])

    return {
        "low": round(band("low")),
        "central": round(band("central")),
        "high": round(band("high")),
        "unit": "EUR (2025 price context, screening range)",
    }


def loss_screening_estimate(
    lat: float,
    lon: float,
    buildings_count: Optional[float],
    *,
    buildings_source: Optional[str] = None,
    radius_m: Optional[float] = None,
) -> Dict[str, Any]:
    """Full ESTIMATED payload for a point.

    ``buildings_count`` is the real mapped-building count from the calling
    engine (analysis payload or exposure engine) — never fetched here, so
    the function stays pure and offline-testable. Missing/zero counts yield
    an honest ``unavailable``.
    """
    lat, lon = float(lat), float(lon)
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return {"status": "unavailable", "reason": "coordinates out of range"}
    if not buildings_count or buildings_count <= 0:
        return {
            "status": "unavailable",
            "reason": "no mapped building count available for this location "
                      "(OSM completeness varies by region)",
            "claim_status": "ESTIMATED",
        }

    cfg = load_benchmarks()
    country = match_country(lat, lon, cfg)
    defaults = cfg.get("defaults") or {}
    cost_band = (country or {}).get("replacement_cost_per_m2") or \
        defaults.get("replacement_cost_per_m2")
    area_band = defaults.get("floor_area_per_building_m2")

    value = estimate_exposed_value(buildings_count, cost_band, area_band)

    return {
        "status": "ok",
        "claim_status": "ESTIMATED",
        "confidence": Confidence.LOW.value,
        "estimate": {
            "kind": "exposed_value_screening",
            "exposed_value_eur": value,
        },
        "expected_loss": {
            "status": "not_available",
            "statement": EXPECTED_LOSS_STATEMENT,
        },
        "inputs": {
            "buildings_count": {
                "value": float(buildings_count),
                "source": buildings_source or "mapped building count supplied by the calling engine",
                "radius_m": radius_m,
                "caveat": "OpenStreetMap completeness varies by region; counts are a lower bound.",
            },
            "country_benchmark": (
                {"code": country.get("code"), "name": country.get("name")}
                if country else
                {"code": None, "name": "fallback defaults (no country benchmark matched)"}
            ),
            "benchmarks": {
                "replacement_cost_per_m2": cost_band,
                "floor_area_per_building_m2": area_band,
                "config": "config/loss_estimate_benchmarks.json",
            },
        },
        "method": (
            "exposed_value = mapped_buildings × floor_area_per_building × "
            "replacement_cost_per_m2, computed independently for the low, "
            "central and high declared benchmark bands. Benchmarks are declared "
            "screening ranges with stated bases — not valuations."
        ),
        "limitations": [
            "Exposed-value screening, NOT an expected loss: no damage ratio, "
            "no vulnerability model and no hazard footprint is applied.",
            "OSM building counts are mapped features; completeness varies by "
            "region and non-residential buildings are not separated.",
            "Benchmarks are declared screening ranges; country-level licensed "
            "valuation data would narrow them.",
            "The wide low–high span is the honest compound of the declared "
            "input uncertainties.",
        ],
        "separation_note": SEPARATION_NOTE,
        "generated_at": utcnow_iso(),
    }
