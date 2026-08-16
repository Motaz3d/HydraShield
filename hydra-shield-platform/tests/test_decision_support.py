"""Tests for the decision-support layers: ecology, exposure, micro-area,
scenarios, environmental recommendations, audit trail, PDF report."""

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
