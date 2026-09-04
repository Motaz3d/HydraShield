"""Tests for the decision-support layers: ecology, exposure, micro-area,
scenarios, environmental recommendations, audit trail, PDF report."""

import io
import os

import pytest

os.environ["HYDRASHIELD_CACHE_DB"] = "/tmp/hydrashield_test_ds_cache.sqlite3"
if os.path.exists(os.environ["HYDRASHIELD_CACHE_DB"]):
    os.remove(os.environ["HYDRASHIELD_CACHE_DB"])

from src.dashboard import ecology as eco_module  # noqa: E402
from src.dashboard import exposure as exp_module  # noqa: E402
from src.dashboard import micro as micro_module  # noqa: E402
from src.dashboard import scenarios as scen_module  # noqa: E402
from src.dashboard import recommendations as recs_module  # noqa: E402
from src.dashboard import report as report_module  # noqa: E402
from src.dashboard.api import create_app  # noqa: E402


# --------------------------------------------------------------------------
# Ecology
# --------------------------------------------------------------------------

def _analysis_for_ecology(climate=None, fmc=10.0, sm=0.1, elevation=350.0,
                          slope=8.0, landcover="Shrubland"):
    return {
        "terrain": {"elevation_m": elevation, "slope_degrees": slope,
                    "aspect_degrees": 180.0},
        "landcover": {"dominant_label": landcover, "burnable": True,
                      "dominant_fraction": 0.7},
        "weather": {"soil_moisture_m3m3": sm},
        "climate": climate or {"available": True, "mean_temp_max_c": 31.2,
                               "total_precip_mm": 0.4},
        "analysis": {"fuel_moisture_baseline_pct": fmc},
        "active_fires": {"available": False},
    }


def test_species_knowledge_base_loads():
    kb = eco_module.load_species_knowledge()
    assert len(kb["species"]) >= 12
    for sp in kb["species"]:
        assert sp["scientific_name"] and sp["sources"]
        assert sp["recommendation"] in (
            "recommended", "recommended_with_caution",
            "not_recommended_in_protection_zones", "not_recommended")


def test_climate_zone_classification():
    assert eco_module.classify_climate_zone(
        {"mean_temp_max_c": 31.0, "total_precip_mm": 0.5}, 300.0) == "mediterranean"
    assert eco_module.classify_climate_zone(
        {"mean_temp_max_c": 21.0, "total_precip_mm": 25.0}, 300.0) == "temperate"
    assert eco_module.classify_climate_zone({}, 300.0) is None


def test_moisture_regime_classification():
    assert eco_module.classify_moisture_regime(10.0, 0.1, 0.0) == "dry"
    assert eco_module.classify_moisture_regime(35.0, 0.4, 40.0) == "moist"
    assert eco_module.classify_moisture_regime(22.0, 0.28, 12.0) == "normal"
    assert eco_module.classify_moisture_regime(None, None, None) is None


def test_ecology_mediterranean_dry_site():
    eco = eco_module.build_ecology_block(_analysis_for_ecology())
    assert eco["status"] == "ok"
    names = [e["common_name"] for e in eco["recommended"]]
    assert "Cork oak" in names          # native mediterranean, drought-tolerant
    not_rec = [e["common_name"] for e in eco["not_recommended"]]
    assert any("Eucalyptus" in n for n in not_rec)
    cork = next(e for e in eco["recommended"] if e["common_name"] == "Cork oak")
    assert cork["native"] is True
    assert cork["site_fit"]["reasons_for"]  # quotes the real site values
    assert any("31.2" in str(eco["site_conditions"].get("climate_zone")) or
               "mediterranean" in r for r in cork["site_fit"]["reasons_for"]
               for _ in [0])
    assert "fireproof" in eco["fire_note"]
    assert "verify" in eco["verification_note"].lower()
    for e in eco["recommended"] + eco["not_recommended"]:
        assert e["evidence"] and e["confidence"]


def test_ecology_temperate_site():
    eco = eco_module.build_ecology_block(_analysis_for_ecology(
        climate={"available": True, "mean_temp_max_c": 20.0, "total_precip_mm": 35.0},
        fmc=28.0, sm=0.3, elevation=400.0, landcover="Tree cover"))
    names = [e["common_name"] for e in eco["recommended"]]
    assert any("beech" in n.lower() or "oak" in n.lower() for n in names)
    assert "Cork oak" not in names  # mediterranean species filtered out


def test_ecology_insufficient_data_is_honest():
    eco = eco_module.build_ecology_block({
        "terrain": {"error": "x"}, "landcover": {"error": "x"},
        "weather": {}, "climate": {}, "analysis": {}, "active_fires": {},
    })
    assert eco["status"] == "insufficient_data"
    assert eco["message"] == (
        "Local ecological suitability could not be established from the available data.")


# --------------------------------------------------------------------------
# Exposure (Overpass mocked)
# --------------------------------------------------------------------------

def _overpass_payload(counts):
    return {"elements": [{"type": "count", "tags": {"total": str(c)}} for c in counts]}


def _ohsome_result(counts):
    """Mock both OSM fetchers (ohsome primary + Overpass fallback)."""
    return {"counts": dict(zip(
        ["hospitals", "schools", "fire_stations", "power_facilities",
         "buildings", "roads_all", "roads_major", "water_features", "waterways"],
        counts)), "count_date": "2026-07-01",
        "source": "OpenStreetMap via ohsome API (Heidelberg Institute)"}


def _mock_osm(monkeypatch, counts):
    monkeypatch.setattr(exp_module, "_fetch_counts_ohsome",
                        lambda lat, lon, r: _ohsome_result(counts))


def test_fetch_osm_context_parses_counts(monkeypatch):
    _mock_osm(monkeypatch, [1, 3, 0, 2, 45, 60, 4, 1, 2])
    out = exp_module.fetch_osm_context.__wrapped__(37.6, -6.5, 2000)
    assert out["counts"]["hospitals"] == 1
    assert out["counts"]["schools"] == 3
    assert out["counts"]["buildings"] == 45
    assert out["counts"]["roads_major"] == 4
    assert "OpenStreetMap" in out["source"]


def test_fetch_osm_context_falls_back_to_overpass(monkeypatch):
    def boom(lat, lon, r):
        raise OSError("ohsome down")
    monkeypatch.setattr(exp_module, "_fetch_counts_ohsome", boom)
    monkeypatch.setattr(exp_module, "_fetch_counts_overpass",
                        lambda lat, lon, r: {"counts": {"hospitals": 2}, "count_date": None,
                                             "source": "OpenStreetMap (Overpass API)"})
    out = exp_module.fetch_osm_context.__wrapped__(41.0, -7.5, 2000)
    assert out["counts"]["hospitals"] == 2
    assert "Overpass" in out["source"]


def test_fetch_osm_context_unavailable_is_honest(monkeypatch):
    def boom(lat, lon, r):
        raise OSError("timeout")
    monkeypatch.setattr(exp_module, "_fetch_counts_ohsome", boom)
    monkeypatch.setattr(exp_module, "_fetch_counts_overpass", boom)
    out = exp_module.fetch_osm_context.__wrapped__(37.6, -6.5)
    assert "error" in out


def _analysis_for_exposure(counts, slope=5.0, burnable=True):
    payload_counts = counts
    return {
        "location": {"latitude": 37.6, "longitude": -6.5},
        "landcover": ({"burnable": burnable, "dominant_label": "Shrubland"}
                      if burnable else {"burnable": False}),
        "terrain": {"slope_degrees": slope},
        "_counts": payload_counts,
    }


def test_exposure_block_assessment(monkeypatch):
    _mock_osm(monkeypatch, [1, 2, 0, 1, 120, 80, 2, 0, 1])
    analysis = {
        "location": {"latitude": 37.6, "longitude": -6.5},
        "landcover": {"burnable": True, "dominant_label": "Shrubland"},
        "terrain": {"slope_degrees": 5.0},
    }
    x = exp_module.build_exposure_block(analysis)
    assert x["status"] == "ok"
    assert x["exposure"]["level"] == "high"
    assert x["vulnerable_assets"]["total"] == 4
    assert x["access"]["major_road_nearby"] is True
    assert x["wui_indicator"]["potential_wui"] is True  # buildings + burnable
    assert "NOT part of the 0-100" in x["separate_from_score_note"]
    assert x["provenance"]["kind"] == "observed"


def test_exposure_limited_access_and_steep(monkeypatch):
    _mock_osm(monkeypatch, [0, 0, 0, 0, 3, 2, 0, 0, 0])
    analysis = {
        # distinct coords -> fresh cache entry (exposure cache TTL is 7 days)
        "location": {"latitude": 10.123, "longitude": 20.456},
        "landcover": {"burnable": True},
        "terrain": {"slope_degrees": 16.0},
    }
    x = exp_module.build_exposure_block(analysis)
    assert x["access"]["limited"] is True
    assert any("steep" in c for c in x["access"]["constraints"])
    assert x["exposure"]["level"] == "low"
    assert x["wui_indicator"]["potential_wui"] is False


# --------------------------------------------------------------------------
# Micro-area
# --------------------------------------------------------------------------

def test_grid_stats_math():
    stats = micro_module._grid_stats([[0.1, 0.3], [None, 0.5]])
    assert stats["cells"] == 3
    assert stats["mean"] == 0.3
    assert stats["range"] == 0.4
    assert stats["std"] > 0
    assert micro_module._grid_stats([[None, None]]) is None
    assert micro_module._grid_stats(None) is None


def test_micro_block_with_real_grid():
    analysis = {
        "satellite": {"ndmi": 0.2, "ndmi_grid": [[0.1, 0.2], [0.3, 0.9]],
                      "grid_bounds": [-6.6, 37.5, -6.4, 37.7]},
        "terrain": {"resolution": "25 m"},
        "landcover": {"resolution": "10 m"},
    }
    m = micro_module.build_micro_area_block(analysis)
    mc = m["micro_context"]
    assert mc["scene_available"] is True
    assert mc["ndmi_variability"]["range"] == 0.8
    assert "heterogeneous" in mc["variability_note"]
    assert mc["scene_extent_m"]["width_m"] > 0
    assert "~11 km" in m["regional_context"]["note"]


def test_micro_block_without_scene_is_honest():
    m = micro_module.build_micro_area_block({"satellite": {"error": "clouds"},
                                             "terrain": {}, "landcover": {}})
    assert m["micro_context"]["scene_available"] is False
    assert "unavailable, not estimated" in m["micro_context"]["unavailable_note"]


# --------------------------------------------------------------------------
# Scenarios
# --------------------------------------------------------------------------

def _analysis_for_scenarios(fmc=10.0, risk=70.0, ros=6.0):
    return {
        "analysis": {
            "fuel_moisture_baseline_pct": fmc,
            "risk": {"baseline": risk},
            "fire_spread": {"fuel_model": "TL3", "ros_current_m_min": ros},
        },
        "fire_danger": {"available": True, "fwi": 40.0},
        "landcover": {"burnable": True},
        "terrain": {"slope_degrees": 8.0},
        "weather": {"wind_speed_kmh": 15.0},
    }


def test_scenarios_modelled_and_not_quantified():
    out = scen_module.build_scenarios(_analysis_for_scenarios())
    modelled = [s for s in out if s["status"] == "modelled"]
    not_q = [s for s in out if s["status"] == "not_quantified"]
    assert {s["id"] for s in modelled} == {"hydration", "fuel-management", "combined"}
    assert len(not_q) == 4  # monitoring, water, restoration, access
    hyd = next(s for s in modelled if s["id"] == "hydration")
    assert hyd["result"]["risk"] < hyd["baseline"]["risk"]
    assert hyd["result"]["risk_delta"] < 0
    assert hyd["result"]["ros_m_min"] < hyd["baseline"]["ros_m_min"]
    assert hyd["assumptions"] and hyd["uncertainty"] and hyd["limitations"]
    assert "not an observed result" in hyd["label"]
    for s in not_q:
        assert s.get("mechanism") or s.get("reason")


def test_scenarios_without_fmc_are_not_quantified():
    out = scen_module.build_scenarios(_analysis_for_scenarios(fmc=None, risk=None, ros=None))
    hyd = next(s for s in out if s["id"] == "hydration")
    assert hyd["status"] == "not_quantified"
    assert "fabricating" in hyd["reason"]


# --------------------------------------------------------------------------
# Environmental recommendations + audit trail
# --------------------------------------------------------------------------

def _full_analysis_for_recs():
    return {
        "fire_danger": {"available": True, "fwi": 42.0, "class": "Extreme"},
        "analysis": {"fuel_moisture_baseline_pct": 9.0,
                     "risk": {"baseline": 72.0, "class": "Extreme"}},
        "weather": {"wind_speed_kmh": 10.0},
        "terrain": {"slope_degrees": 17.0},
        "landcover": {"burnable": True, "dominant_label": "Shrubland",
                      "dominant_fraction": 0.75},
        "active_fires": {"available": False},
        "fire_danger_trend": {"trend": "rising", "slope_per_day": 1.2},
        "ecology": {"status": "ok",
                    "site_conditions": {"moisture_regime": "dry",
                                        "fuel_moisture_pct": 9.0,
                                        "soil_moisture_m3m3": 0.1,
                                        "recent_precip_mm": 0.0}},
        "exposure": {"status": "ok", "radius_m": 2000,
                     "vulnerable_assets": {"total": 2, "hospitals": 1, "schools": 1,
                                           "fire_stations": 0, "power_facilities": 0},
                     "access": {"limited": True, "constraints": ["sparse roads"]}},
    }


def test_environmental_rules_fire_with_evidence():
    recs = recs_module.build_recommendations(_full_analysis_for_recs())
    ids = [r["id"] for r in recs]
    assert "fuel-break" in ids
    assert "ecological-restoration" in ids
    assert "drought-preparedness" in ids
    assert "erosion-slope" in ids
    assert "protect-critical-facilities" in ids
    assert "access-routes" in ids
    crit = next(r for r in recs if r["id"] == "protect-critical-facilities")
    assert crit["priority"] in ("critical", "high")
    assert "1 hospitals" in crit["why"]
    for r in recs:
        assert r["evidence"]["value"] is not None


def test_environmental_rules_silent_without_conditions():
    recs = recs_module.build_recommendations({
        "fire_danger": {"available": True, "fwi": 5.0, "class": "Low"},
        "analysis": {"fuel_moisture_baseline_pct": 30.0,
                     "risk": {"baseline": 10.0}},
        "weather": {"wind_speed_kmh": 5.0},
        "terrain": {"slope_degrees": 2.0},
        "landcover": {"burnable": True, "dominant_fraction": 0.3},
        "active_fires": {"available": False},
        "fire_danger_trend": {"trend": "falling"},
        "ecology": {"status": "ok", "site_conditions": {"moisture_regime": "moist"}},
        "exposure": {"status": "unavailable"},
    })
    assert recs == []


def test_audit_trail_roundtrip(tmp_path):
    store = recs_module.PlanAuditStore(str(tmp_path / "audit.sqlite3"))
    pid = store.record("Testville", "escalate", False,
                       {"risk": 80}, [{"id": "x", "type": "recommended",
                                       "status": "requires_operational_configuration"}])
    rows = store.list()
    assert len(rows) == 1
    assert rows[0]["id"] == pid
    assert rows[0]["location"] == "Testville"
    assert rows[0]["automation_enabled"] is False
    assert rows[0]["actions"][0]["status"] == "requires_operational_configuration"


def test_action_plan_records_audit(tmp_path):
    store = recs_module.PlanAuditStore(str(tmp_path / "a.sqlite3"))
    analysis = {
        "analysis": {"risk": {"baseline": 70.0, "class": "High"},
                     "fuel_moisture_baseline_pct": 10.0},
        "fire_danger": {"available": True, "fwi": 40.0},
        "weather": {}, "location": {"name": "Audit Town"},
    }
    plan = recs_module.build_action_plan(analysis, [], ops_config={}, audit_store=store)
    assert plan["audit_id"]
    assert store.list()[0]["location"] == "Audit Town"


# --------------------------------------------------------------------------
# PDF report
# --------------------------------------------------------------------------

def _report_payload():
    return {
        "location": {"name": "Reportville", "latitude": 37.6, "longitude": -6.5},
        "generated_at": "2026-08-16T00:00:00Z",
        "weather": {"temperature_c": 35.0, "wind_speed_kmh": 9.0,
                    "relative_humidity_pct": 22, "soil_moisture_m3m3": 0.11},
        "terrain": {"elevation_m": 120.0, "slope_degrees": 5.0},
        "landcover": {"dominant_label": "Shrubland", "burnable": True},
        "satellite": {"ndvi": 0.4, "ndmi": 0.1, "observation_date": "2026-08-14"},
        "active_fires": {"available": False, "error": "no key"},
        "fire_danger": {"available": True, "fwi": 41.0, "class": "Extreme",
                        "effis_class": "Very high", "ffmc": 90, "dmc": 50, "dc": 300,
                        "isi": 8, "bui": 60, "date": "2026-08-15",
                        "series": [{"date": f"2026-08-{d:02d}", "fwi": 30.0 + d}
                                   for d in range(1, 8)]},
        "fire_danger_trend": {"trend": "rising"},
        "risk_explanation": {"disclaimer": "Composite indicator.", "formula": "f",
                             "factors": [{"label": "Fire weather (FWI)", "value": 41.0,
                                          "unit": "FWI", "level": "Extreme",
                                          "contribution": 62.1,
                                          "provenance_kind": "derived"}]},
        "analysis": {"fuel_moisture_baseline_pct": 8.0,
                     "fuel_moisture_source": "Derived",
                     "risk": {"baseline": 68.0, "class": "Extreme"},
                     "fire_spread": {"fuel_model": "TL3", "ros_current_m_min": 5.0}},
        "change": {"available": False, "reason": "no series"},
        "exposure": {"status": "unavailable", "reason": "osm down"},
        "micro_area": {"micro_context": {"ndmi_variability": None},
                       "local_context": {"resolution": "25 m"}},
        "ecology": {"status": "insufficient_data",
                    "message": "Local ecological suitability could not be established from the available data."},
        "scenarios": [{"name": "Hydration", "status": "modelled",
                       "baseline": {"risk": 68.0},
                       "result": {"risk": 62.0, "risk_delta": -6.0}}],
        "recommendations": [{"priority": "high", "what": "Do X", "why": "FWI 41."}],
        "action_plan": {"level": "activate", "automation_enabled": False,
                        "audit_id": "abc", "actions": [],
                        "no_guarantee_note": "No guarantee."},
        "provenance": {"fire_danger": {"kind": "derived", "source": "FWI",
                                       "acquired": "2026-08-15", "limitations": "agg"}},
        "population": {
            "status": "ok", "radius_km": 3.0,
            "estimated_population": 4820, "mean_density_per_km2": 170.8,
            "density_level": "high",
            "estimate_note": ("Estimated population exposure based on WorldPop, "
                              "reference year 2025 (modelled gridded estimates at "
                              "~100 m) — not an exact count."),
            "reference_year": 2025,
            "product": "WorldPop Global 2 (R2025A) constrained 100 m",
            "resolution": "100 m (grid cells)",
            "license": "CC-BY 4.0 (WorldPop, University of Southampton)",
            "hazard_class": "Very high",
            "estimated_population_in_hazard_area": 4820,
            "exposure_note": ("Estimated population within 3.0 km of the analysed "
                              "point while the area carries hazard class 'Very high'."),
            "critical_facilities": {"hospitals": 1, "schools": 2, "fire_stations": 0,
                                    "power_facilities": 0,
                                    "note": "Mapped OpenStreetMap features."},
            "mapped_buildings": 120,
            "human_exposure_priority": "high",
            "human_exposure_note": ("Very high wildfire hazard coincides with high "
                                    "population density — elevated human-exposure priority."),
            "separate_from_score_note": ("Population exposure is reported separately from "
                                         "the composite wildfire-risk score; it is never "
                                         "multiplied into a probability."),
            "provenance": {"kind": "modeled",
                           "source": "WorldPop Global 2 (R2025A) constrained 100 m, reference year 2025",
                           "resolution": "100 m", "temporal": "reference year 2025",
                           "quality": "ok",
                           "limitations": "Gridded modelled estimates, not a census count."},
        },
        "ignition": {
            "status": "ok",
            "name": "Relative Ignition-Likelihood Indicator",
            "model_version": "rili-1.0.0",
            "indicator": 79.3, "class": "high",
            "components": {
                "fire_weather": {"score": 95.0, "weight": 0.5,
                                 "inputs": {"ffmc": 90.0},
                                 "basis": "FFMC from the Canadian FWI System (real Open-Meteo daily data)"},
                "human_presence": {"score": 56.0, "weight": 0.3,
                                   "inputs": {"population_density_per_km2": 120.0,
                                              "roads_mapped_within_2km": 25},
                                   "basis": "WorldPop estimated density + mapped OSM roads"},
                "fuel_dryness": {"score": 75.0, "weight": 0.2,
                                 "inputs": {"fmc_pct": 10.0},
                                 "basis": "Fuel moisture content (Sentinel-2 NDMI-derived)"},
            },
            "weights": {"fire_weather": 0.5, "human_presence": 0.3, "fuel_dryness": 0.2},
            "input_coverage": ["fire_weather", "human_presence", "fuel_dryness"],
            "coverage_note": None, "landcover_note": None,
            "not_a_probability": ("This is a relative screening indicator built from "
                                  "declared thresholds and a-priori weights. It is NOT a "
                                  "calibrated probability of ignition and must not be "
                                  "quoted as one."),
            "distinctions": [
                "HIGH FIRE DANGER ≠ FIRE WILL OCCUR — dangerous conditions do not cause ignitions by themselves.",
                "HIGH IGNITION SUSCEPTIBILITY ≠ OBSERVED FIRE — the indicator ranks relative likelihood, not occurrence.",
                "Wildfire hazard, ignition likelihood and observed fires are reported separately and never merged.",
            ],
            "lightning_note": ("Natural ignition sources (lightning) are not included: "
                               "no openly and legally usable lightning dataset passed "
                               "the source audit."),
            "separate_from_score_note": ("Ignition likelihood is reported separately from "
                                         "the composite wildfire-risk score and is never "
                                         "folded into it."),
            "validation_status": {
                "validated": False,
                "status": "NOT VALIDATED — no historical evaluation has been executed yet",
                "method_when_run": ("Temporal train/test split against NASA FIRMS historical "
                                    "detections with positive/negative sampling, "
                                    "class-imbalance handling, precision/recall/F1, ROC-AUC, "
                                    "PR-AUC, Brier score, calibration and reliability analysis "
                                    "(scripts/evaluate_ignition.py; framework: "
                                    "src/prediction/validation.py)."),
                "promotion_rule": ("The indicator is never promoted from a single event; "
                                   "evaluation requires a multi-day historical sample."),
            },
            "provenance": {"kind": "derived",
                           "source": "Talaix ignition layer (declared thresholds)",
                           "resolution": "analysis-area screening (population 100 m; weather ~11 km)",
                           "temporal": "current conditions", "quality": "ok",
                           "limitations": "Unvalidated relative indicator; not a probability."},
        },
        "smoke_scenario": {
            "status": "ok", "mode": "scenario",
            "mode_label": "SCENARIO / MODELLED — no fire is observed at this location",
            "scenario": ("If a fire were to occur near this location under current "
                         "atmospheric conditions, this is where the smoke could move."),
            "location": {"latitude": 37.6, "longitude": -6.5},
            "generated_at": "2026-08-16T00:00:00Z",
            "window": {"from": "2026-08-16T00:00", "to": "2026-08-17T00:00",
                       "hours": 24, "timezone": "UTC"},
            "transport": {
                "dominant_transport_direction": "E",
                "dominant_transport_heading_deg": 90.0,
                "mean_transport_speed_kmh": 18.5,
                "displacement_km": 210.0,
                "confidence": "moderate",
                "confidence_note": ("Steady transport direction. 'Moderate' is the highest "
                                    "confidence a screening trajectory from ~11 km model "
                                    "winds ever receives here."),
                "corridor_model": {"type": "widening envelope (screening), not a deterministic path",
                                   "initial_half_width_km": 1.5,
                                   "growth_km_per_hour": 0.75},
            },
            "overlays": {
                "population": {"available": True,
                               "estimated_population_in_corridor": 3210,
                               "estimate_note": ("Estimated population within the modelled "
                                                 "area based on WorldPop, reference year "
                                                 "2025 (gridded estimates, not an exact count)."),
                               "source": "WorldPop Global 2 (R2025A) constrained 100 m, reference year 2025"},
                "facilities": {"available": True,
                               "counts": {"hospitals": 1, "schools": 2, "fire_stations": 0},
                               "facilities": [],
                               "source": "OpenStreetMap (Overpass API, corridor polygon filter)",
                               "note": "Mapped OSM features inside the modelled corridor."},
            },
            "disclaimer": ("Atmospheric transport guidance, not certainty. Screening "
                           "trajectory from numerical-weather-model wind fields (~11 km "
                           "grid): plume rise, chemistry, deposition, vertical wind shear "
                           "and terrain channelling are not modelled."),
            "safety": {"kind": ("general public-health guidance (WHO / national "
                                "fire-service public advice)"),
                       "not_medical_advice": True,
                       "points": ["Follow instructions from official civil-protection and "
                                  "fire services first."],
                       "distinction_note": ("This section is environmental exposure "
                                            "information from modelled atmospheric "
                                            "transport. It is neither an observation of "
                                            "smoke at ground level nor an official "
                                            "emergency instruction.")},
            "provenance": {"kind": "modeled",
                           "source": "Weather model hourly profile (Open-Meteo) (transport level 850 hPa)",
                           "resolution": "~11 km NWP grid; corridor is a screening envelope",
                           "temporal": "next 24 h from 2026-08-16T00:00:00Z",
                           "quality": "ok",
                           "limitations": "Screening envelope, not a dispersion model."},
        },
        "methodology": {"note": "methodology"},
    }


def test_pdf_report_generation():
    pytest.importorskip("reportlab")
    pdf = report_module.build_report_pdf(_report_payload())
    assert pdf[:5] == b"%PDF-"
    assert len(pdf) > 4000


def test_pdf_report_with_history():
    pytest.importorskip("reportlab")
    history = {
        "window": {"start": "2026-05-01", "end": "2026-07-30", "days": 90},
        "high_risk_periods": [{"start": "2026-07-01", "end": "2026-07-03"}],
        "lessons": [{"period": {"start": "2026-07-01", "end": "2026-07-03"},
                     "hydrashield_score": {"value": 70.0, "label": "MODELLED"},
                     "observed_fire": {"status": "unknown", "label": "UNKNOWN"}}],
        "fire_observations": {"available": False, "reason": "no key"},
    }
    pdf = report_module.build_report_pdf(_report_payload(), history=history)
    assert pdf[:5] == b"%PDF-"


def _pdf_text(pdf):
    pypdf = pytest.importorskip("pypdf")
    return "\n".join(page.extract_text() or ""
                     for page in pypdf.PdfReader(io.BytesIO(pdf)).pages)


# --------------------------------------------------------------------------
# PDF report: population / ignition / smoke sections
# --------------------------------------------------------------------------

def test_pdf_decision_report_population_ignition_smoke_sections():
    pytest.importorskip("reportlab")
    text = _pdf_text(report_module.build_report_pdf(_report_payload(),
                                                    report_type="decision"))
    assert "Population & exposure" in text
    assert "Ignition susceptibility" in text
    assert "Smoke intelligence" in text
    # Scenario labelling and population source must be visible.
    assert "SCENARIO / MODELLED" in text
    assert "WorldPop" in text
    assert "reference year 2025" in text
    # Honesty wording from the blocks is rendered verbatim.
    assert "NOT a calibrated probability" in text
    assert "NOT VALIDATED" in text


def test_pdf_scientific_report_validation_method_text():
    pytest.importorskip("reportlab")
    text = _pdf_text(report_module.build_report_pdf(_report_payload(),
                                                    report_type="scientific"))
    assert "Validation method (when run)" in text
    assert "Temporal train/test split" in text
    # Scientific methodology appendix rows for the new layers.
    assert "Population dataset" in text
    assert "Smoke corridor model" in text
    assert "Ignition validation" in text


def test_pdf_simple_report_omits_new_sections():
    pytest.importorskip("reportlab")
    text = _pdf_text(report_module.build_report_pdf(_report_payload(),
                                                    report_type="simple"))
    assert "Smoke intelligence" not in text
    assert "Population & exposure" not in text
    assert "Ignition susceptibility" not in text


def test_pdf_unavailable_blocks_render_unavailable():
    pytest.importorskip("reportlab")
    payload = _report_payload()
    payload["population"] = {"status": "unavailable", "reason": "no WorldPop raster"}
    payload["ignition"] = {"status": "unavailable", "reason": "no component inputs"}
    payload["smoke_scenario"] = {"error": "wind profile unavailable"}
    text = _pdf_text(report_module.build_report_pdf(payload, report_type="decision"))
    assert "Population estimate unavailable" in text
    assert "Ignition indicator unavailable" in text
    assert "Smoke transport estimate unavailable" in text
    assert text.count("(UNAVAILABLE)") >= 3


# --------------------------------------------------------------------------
# /api/report endpoint
# --------------------------------------------------------------------------

@pytest.fixture()
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_report_endpoint_requires_input(client):
    resp = client.get("/api/report")
    assert resp.status_code == 400


def test_report_endpoint_returns_pdf(client, monkeypatch):
    pytest.importorskip("reportlab")
    from src.dashboard import snapshot as snapshot_module

    monkeypatch.setattr(snapshot_module, "cached_analysis",
                        lambda lat, lon, name: _report_payload())
    import src.dashboard.api as api_module
    monkeypatch.setattr(api_module, "_cached_analysis",
                        lambda lat, lon, name: _report_payload())
    resp = client.get("/api/report?lat=37.6&lon=-6.5")
    assert resp.status_code == 200
    assert resp.mimetype == "application/pdf"
    assert resp.data[:5] == b"%PDF-"


def test_pdf_report_solutions_funding_section():
    """The decision report renders the Solutions & potential funding
    section from the real engines — with the no-guarantee and
    not-financial-advice disclaimers."""
    pytest.importorskip("reportlab")
    from src.climate import solutions as sol_module
    from src.climate import funding as funding_module

    site = {
        "lat": 37.6, "lon": -6.5,
        "hazards": [{"id": "wildfire", "level": "High"}],
        "landcover_classes": ["Tree cover", "Shrubland"],
        "water_features_count": 3, "buildings_count": 120,
    }
    solutions = sol_module.recommend_solutions(site)
    funding = funding_module.match_funding({"hazards": ["wildfire"]})
    text = _pdf_text(report_module.build_report_pdf(
        _report_payload(), report_type="decision",
        solutions=solutions, funding=funding))
    assert "Solutions & potential funding" in text
    assert "No solution guarantees prevention" in text
    assert "not financial advice" in text
    assert "Fuel management" in text or "fuel" in text.lower()


def test_pdf_report_without_solutions_omits_section():
    """Without engine results the section is honestly omitted."""
    pytest.importorskip("reportlab")
    text = _pdf_text(report_module.build_report_pdf(
        _report_payload(), report_type="decision"))
    assert "Solutions & potential funding" not in text


def test_pdf_report_population_charts_rendered_from_real_data():
    """Population-by-hazard-class and critical-facilities bar charts render
    when the real data carries them — and are omitted when it doesn't."""
    pytest.importorskip("reportlab")
    payload = _report_payload()
    payload["population"]["population_by_hazard_class"] = {
        "High": 4820, "Moderate": 1200}
    text = _pdf_text(report_module.build_report_pdf(payload,
                                                    report_type="decision"))
    assert "Estimated population by hazard class" in text
    assert "Mapped critical facilities" in text

    # Without the breakdown, no chart title is rendered.
    payload2 = _report_payload()
    text2 = _pdf_text(report_module.build_report_pdf(payload2,
                                                     report_type="decision"))
    assert "Estimated population by hazard class" not in text2


# --------------------------------------------------------------------------
# PDF report: Documented disaster losses section
# --------------------------------------------------------------------------

def _norm(text):
    return " ".join(text.split())


_LOSSES_OK = {
    "status": "ok",
    "figures": [{
        "event": "July 2021 Western and Central European floods (low-pressure system Bernd)",
        "hazard": "flood",
        "label": "Insured losses (Germany)",
        "value": 8.2,
        "unit": "billion EUR (2021 values, published rounded figure)",
        "claim_status": "DOCUMENTED",
        "source": "gdv",
        "reference_period": "July 2021",
        "geographic_scope": "Germany (national aggregate)",
        "licence_note": "cite GDV when quoting",
        "provider_url": "https://www.gdv.de/",
        "method": "published GDV insured-loss estimate",
        "limitations": "national aggregate",
        "matched_area": "Germany",
    }],
    "figure_count": 1,
    "sources": ["gdv"],
    "generated_at": "2026-09-04T00:00:00Z",
}


def test_pdf_report_documented_losses_section_all_types():
    """The Documented disaster losses section renders the published figure
    with its event and source — in every report type (simple included)."""
    pytest.importorskip("reportlab")
    for rtype in ("simple", "decision", "scientific"):
        text = _norm(_pdf_text(report_module.build_report_pdf(
            _report_payload(), report_type=rtype, losses=_LOSSES_OK)))
        assert "Documented disaster losses" in text
        assert "Insured losses (Germany)" in text
        assert "8.2" in text
        assert "gdv" in text
        assert "not a loss estimate for this asset" in text
        assert "strict" in text and "separation" in text


def test_pdf_report_documented_losses_unavailable_is_declared():
    """Without covering figures the section honestly declares the gap."""
    pytest.importorskip("reportlab")
    text = _norm(_pdf_text(report_module.build_report_pdf(
        _report_payload(), report_type="decision",
        losses={"status": "unavailable", "figures": [],
                "reason": "no curated registry event covers this location"})))
    assert "Documented disaster losses" in text
    assert "declared, not estimated" in text
    assert "no curated registry event" in text


def test_documented_losses_rows_pure_data():
    rows = report_module.documented_losses_rows({"figures": [
        {"event": "E", "label": "L", "value": 1, "unit": "u",
         "source": "s", "reference_period": "p"}]})
    assert rows[0] == ["Event", "Figure", "Value", "Source · period"]
    assert rows[1] == ["E", "L", "1 u", "s · p"]
    assert report_module.documented_losses_rows(None) == [["Event", "Figure", "Value", "Source · period"]]


# --------------------------------------------------------------------------
# PDF report: Talaix loss screening estimate (ESTIMATED sub-block)
# --------------------------------------------------------------------------

_LOSS_ESTIMATE_OK = {
    "status": "ok",
    "claim_status": "ESTIMATED",
    "estimate": {
        "kind": "exposed_value_screening",
        "exposed_value_eur": {"low": 93000000, "central": 204600000,
                              "high": 496000000,
                              "unit": "EUR (2025 price context, screening range)"},
    },
    "expected_loss": {"status": "not_available", "statement": "no damage-ratio model"},
    "inputs": {
        "buildings_count": {"value": 775, "source": "test", "radius_m": 2000},
        "country_benchmark": {"code": "LU", "name": "Luxembourg"},
        "benchmarks": {"config": "config/loss_estimate_benchmarks.json"},
    },
    "method": "exposed_value = mapped_buildings × floor_area × cost_per_m2",
    "limitations": ["screening range"],
    "separation_note": "ESTIMATED figures are never merged with DOCUMENTED loss figures.",
    "generated_at": "2026-09-04T00:00:00Z",
}


def test_pdf_report_loss_estimate_sub_block_all_types():
    """The ESTIMATED screening range renders as its own strictly separated
    sub-block — in every report type — and never as a documented figure."""
    pytest.importorskip("reportlab")
    for rtype in ("simple", "decision", "scientific"):
        text = _norm(_pdf_text(report_module.build_report_pdf(
            _report_payload(), report_type=rtype,
            losses=_LOSSES_OK, loss_estimate=_LOSS_ESTIMATE_OK)))
        assert "Talaix loss screening estimate" in text
        assert "ESTIMATED" in text
        assert "not a documented figure" in text
        assert "204,600,000" in text  # central exposed value, formatted
        assert "775 mapped buildings" in text
        assert "Luxembourg" in text
        assert "no validated damage-ratio model" in text
        assert "not an expected loss" in text
        # Strict separation: the documented table keeps its own figures and
        # the estimate never claims to be one of them.
        assert "Insured losses (Germany)" in text
        assert text.count("ESTIMATED") >= 2


def test_pdf_report_loss_estimate_unavailable_is_honest():
    pytest.importorskip("reportlab")
    text = _norm(_pdf_text(report_module.build_report_pdf(
        _report_payload(), report_type="decision",
        loss_estimate={"status": "unavailable",
                       "reason": "no mapped building count available"})))
    assert "Talaix loss screening estimate" in text
    assert "unavailable" in text
    assert "no mapped building count" in text
