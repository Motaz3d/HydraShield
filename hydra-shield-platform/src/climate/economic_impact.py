"""
Economic Impact Engine v1 (docs/ECONOMIC_INTELLIGENCE.md — no-fake-money rule).

Formalises the three strictly separated economic blocks for a location:

- ``observed_losses`` — always ``unavailable``: no documented loss dataset
  (e.g. EM-DAT, insurance loss databases) is integrated yet. Declared as
  research candidates, never populated with invented figures.
- ``modelled_estimates`` — the exposure-bounded qualitative profile from
  ``exposure_econ.build_economic_exposure`` (real mapped categories, counts
  and caveats) with the mandatory ``monetary_quantification:
  not_quantified`` statement (exact wording, doc §3).
- ``projections`` — always ``not_available``: economic projections require
  scenario-labelled datasets that are not integrated.

Absolute norm: Talaix does not output euro/dollar loss figures unless a
documented valuation dataset with a stated method is integrated. Everything
economic here carries ``confidence: low``.
"""

from __future__ import annotations

from typing import Any, Dict, List

from ..dashboard.cache import cached
from .evidence import EvidenceRecord, utcnow_iso
from .exposure_econ import NOT_QUANTIFIED_STATEMENT, build_economic_exposure
from .ontology import Confidence

TTL_ECON_IMPACT = 3600.0  # 1 h

OBSERVED_LOSSES_STATEMENT = "No documented loss figures in integrated sources."

OBSERVED_LOSSES_RESEARCH_CANDIDATES = [
    "EM-DAT international disaster database (documented event losses) — research candidate, not integrated",
    "Insurance/reinsurance loss databases (e.g. Munich Re NatCatSERVICE, Swiss Re sigma) — research candidate, not integrated",
]

PROJECTIONS_STATEMENT = (
    "Economic projections require scenario-labelled datasets not yet integrated."
)


@cached("economic_impact", TTL_ECON_IMPACT)
def assess_economic_impact(lat: float, lon: float) -> Dict[str, Any]:
    """Economic-impact formalization for a point. Cached 1 h.

    Three strictly separated blocks — observed losses, modelled estimates,
    projections — plus evidence. No monetary values anywhere.
    """

    lat, lon = float(lat), float(lon)
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return {"error": "Coordinates out of range"}

    evidence: List[Dict[str, Any]] = []

    # -- observed losses (never fabricated) -----------------------------------
    observed_losses = {
        "status": "unavailable",
        "statement": OBSERVED_LOSSES_STATEMENT,
        "research_candidates": OBSERVED_LOSSES_RESEARCH_CANDIDATES,
        "confidence": Confidence.LOW.value,
    }
    evidence.append(EvidenceRecord.unknown(
        "Talaix economic impact engine",
        why=OBSERVED_LOSSES_STATEMENT + " Documented loss datasets "
            "(EM-DAT, insurance loss databases) are research candidates, "
            "not integrated.",
        location={"lat": lat, "lon": lon},
    ).to_dict())

    # -- modelled estimates: exposure-bounded qualitative profile -------------
    exposure = build_economic_exposure(lat, lon)
    exposure_ok = "error" not in exposure
    if exposure_ok:
        categories = exposure.get("exposure") or {}
        modelled_estimates = {
            "status": "ok",
            "basis": "Exposure-bounded qualitative profile: real mapped "
                     "exposure categories and counts bound what could be "
                     "affected; no susceptibility or valuation model exists.",
            "exposure_profile": categories,
            "analysis_window": exposure.get("analysis_window"),
            "radius_km": exposure.get("radius_km"),
            "monetary_quantification": {
                "status": "not_quantified",
                "statement": NOT_QUANTIFIED_STATEMENT,
            },
            "caveats": sorted({
                str(v.get("completeness_caveat"))
                for v in categories.values()
                if isinstance(v, dict) and v.get("completeness_caveat")
            }),
            "confidence": Confidence.LOW.value,
        }
        evidence.extend((exposure.get("provenance") or {}).get("evidence") or [])
    else:
        modelled_estimates = {
            "status": "unavailable",
            "reason": exposure.get("error"),
            "monetary_quantification": {
                "status": "not_quantified",
                "statement": NOT_QUANTIFIED_STATEMENT,
            },
            "confidence": Confidence.LOW.value,
        }
        evidence.append(EvidenceRecord.unknown(
            "OpenStreetMap (ohsome / Overpass) / ESA WorldCover",
            why=str(exposure.get("error")),
            location={"lat": lat, "lon": lon},
        ).to_dict())

    # -- projections (structurally separated, never invented) -----------------
    projections = {
        "status": "not_available",
        "statement": PROJECTIONS_STATEMENT,
        "confidence": Confidence.LOW.value,
    }

    return {
        "status": "ok" if exposure_ok else "partial",
        "location": {"lat": lat, "lon": lon},
        "generated_at": utcnow_iso(),
        "observed_losses": observed_losses,
        "modelled_estimates": modelled_estimates,
        "projections": projections,
        "evidence": evidence,
        "confidence": Confidence.LOW.value,
        "separation_note": (
            "The three blocks are strictly separated: observed losses "
            "(documented figures — none integrated), modelled estimates "
            "(exposure-bounded qualitative profile — no monetary values) and "
            "projections (scenario-conditioned — none integrated). They are "
            "never merged into a single figure."
        ),
        "limitations": [
            "No monetary loss, premium or market-size figure is produced "
            "anywhere in this payload.",
            "Exposure counts are mapped OpenStreetMap features; completeness "
            "varies by region.",
        ],
        "provenance": {
            "engine": "economic_impact_v1",
            "research": [
                {"id": "ipccar6wg2",
                 "role": "risk framework: hazard x exposure x vulnerability"},
            ],
            "exposure_source": "src/climate/exposure_econ.py (OSM/ohsome + "
                               "Overpass counts, ESA WorldCover)",
            "no_fake_money_rule": "docs/ECONOMIC_INTELLIGENCE.md §3",
        },
    }
