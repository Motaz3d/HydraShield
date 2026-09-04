"""
/api/v2 analytics blueprint — compound, cascading and economic-impact
engines (additive; does not change any existing endpoint).

Exposes:

- ``GET /api/v2/compound?lat&lon``         — Compound Risk Engine v1
- ``GET /api/v2/cascading?lat&lon``        — Cascading Risk Graph v1
- ``GET /api/v2/economic-impact?lat&lon``  — Economic Impact Engine v1

Every response is the engine payload plus an ``uncertainty_envelope``
(source, timestamp, method, confidence, coverage, and the
observed/derived/modelled status per block). The blueprint is deliberately
NOT registered here — the lead registers it in ``src/dashboard/api.py``.

Honesty contract: engine payloads carry their own labels; the envelope only
summarises them — no numeric compound/cascade scores, no monetary values.
"""

from __future__ import annotations

from typing import Any, Dict

from flask import Blueprint, jsonify, request

from .api_v2 import _err, _parse_latlon, _rate
from .evidence import utcnow_iso

analytics_bp = Blueprint("analytics", __name__, url_prefix="/api/v2")

_RATE_MAX = 10
_RATE_WINDOW = 60.0


def _uncertainty_envelope(
    *,
    source: str,
    method: str,
    confidence: str,
    coverage: str,
    block_status: Dict[str, str],
) -> Dict[str, Any]:
    """The per-response uncertainty envelope.

    Shape (shared by all analytics endpoints): source, timestamp, method,
    confidence, coverage, and per-block status using the platform's
    observed/derived/modelled vocabulary (plus ``unavailable`` /
    ``not_computable`` where a block honestly cannot be produced).
    """

    return {
        "source": source,
        "timestamp": utcnow_iso(),
        "method": method,
        "confidence": confidence,
        "coverage": coverage,
        "block_status": block_status,
    }


def _latlon_or_err():
    lat, lon, err = _parse_latlon(request.args)
    if err:
        return None, None, _err(err, 400)
    return lat, lon, None


@analytics_bp.get("/compound")
def compound():
    """Compound-risk assessment: /api/v2/compound?lat=…&lon=…

    Qualitative compound-event signals (multivariate, temporally
    compounding, preconditioned) over the location's real light hazard
    signals. No numeric compound score; spatially compounding is returned
    as not_computable at point scale.
    """
    if not _rate("v2compound", _RATE_MAX, _RATE_WINDOW):
        return _err("Rate limit exceeded", 429)
    lat, lon, err_resp = _latlon_or_err()
    if err_resp:
        return err_resp

    from .compound import assess_compound

    payload = dict(assess_compound(lat, lon))
    if "error" in payload:
        return _err(payload["error"], 400)
    payload["uncertainty_envelope"] = _uncertainty_envelope(
        source="Talaix Compound Risk Engine v1 (ERA5/ERA5-Land via "
               "Open-Meteo archive; GloFAS discharge; Canadian FWI)",
        method="Declared qualitative detector on the zscheischler2020typology "
               "four-class typology over light per-hazard screening signals; "
               "no numeric compound score.",
        confidence="low",
        coverage="Point analysis; hazards analysed: "
                 + ", ".join(payload.get("hazards_analysed") or []),
        block_status={
            "hazard_signals": "modelled",
            "compound_signals": "modelled",
            "preconditioned_signals": "derived (INFERRED)",
            "spatially_compounding": "not_computable",
        },
    )
    return jsonify(payload)


@analytics_bp.get("/cascading")
def cascading():
    """Cascading-risk relevance: /api/v2/cascading?lat=…&lon=…

    Cascade paths from the curated graph whose hazard is currently elevated
    and whose directly-exposed system has real mapped exposure anchors.
    Propagation likelihoods and losses are NOT quantified.
    """
    if not _rate("v2cascading", _RATE_MAX, _RATE_WINDOW):
        return _err("Rate limit exceeded", 429)
    lat, lon, err_resp = _latlon_or_err()
    if err_resp:
        return err_resp

    from .cascading import assess_cascading

    payload = dict(assess_cascading(lat, lon))
    if "error" in payload:
        return _err(payload["error"], 400)
    payload["uncertainty_envelope"] = _uncertainty_envelope(
        source="Talaix Cascading Risk Graph v1 "
               "(config/cascading_graph.json; OSM/ohsome exposure anchors)",
        method="Structural relevance screening: curated hazard->system->system "
               "paths filtered by real elevated hazards and real mapped "
               "anchors; no propagation likelihoods or losses.",
        confidence="low",
        coverage="Point analysis within the exposure radius (≤5 km mapped "
                 "features)",
        block_status={
            "active_hazards": "modelled",
            "exposure_anchors": "observed",
            "cascade_paths": "derived",
        },
    )
    return jsonify(payload)


@analytics_bp.get("/economic-impact")
def economic_impact():
    """Economic-impact formalization: /api/v2/economic-impact?lat=…&lon=…

    Strictly separated blocks: observed losses (documented figures from
    integrated free sources when the queried point is within their coverage,
    else unavailable), modelled estimates (exposure-bounded qualitative
    profile, monetary quantification not_quantified), the Talaix loss
    screening estimate (ESTIMATED exposed-value range computed from the
    real mapped building count and declared benchmarks) and projections
    (not_available — no scenario-labelled datasets integrated).
    """
    if not _rate("v2econimpact", _RATE_MAX, _RATE_WINDOW):
        return _err("Rate limit exceeded", 429)
    lat, lon, err_resp = _latlon_or_err()
    if err_resp:
        return err_resp

    from .economic_impact import assess_economic_impact

    payload = dict(assess_economic_impact(lat, lon))
    if "error" in payload:
        return _err(payload["error"], 400)
    observed_status = payload.get("observed_losses", {}).get("status", "unavailable")
    estimate_status = payload.get("loss_screening_estimate", {}).get(
        "status", "unavailable")
    payload["uncertainty_envelope"] = _uncertainty_envelope(
        source="Talaix Economic Impact Engine v1 "
               "(src/climate/exposure_econ.py: OSM/ohsome + Overpass counts, "
               "ESA WorldCover; src/climate/losses.py: NOAA NCEI billion-dollar "
               "disasters where US-covered; src/climate/loss_estimate.py: "
               "Talaix screening estimate)",
        method="Exposure-bounded qualitative profile; observed losses from "
               "integrated free sources when coverage matches; ESTIMATED "
               "exposed-value screening computed from the real mapped "
               "building count and declared benchmarks; no monetary loss "
               "figures are invented (no-fake-money rule, "
               "docs/ECONOMIC_INTELLIGENCE.md §3).",
        confidence="low",
        coverage="Point analysis within the exposure radius (≤5 km mapped "
                 "features); observed losses US-only via NOAA state-level aggregates",
        block_status={
            "observed_losses": observed_status,
            "modelled_estimates": "modelled",
            "loss_screening_estimate": (
                "estimated" if estimate_status == "ok" else "unavailable"),
            "projections": "unavailable",
        },
    )
    return jsonify(payload)
