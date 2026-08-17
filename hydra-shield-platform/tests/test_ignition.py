"""Tests for the Relative Ignition-Likelihood Indicator (RILI) layer.

The indicator is a declared, unvalidated screening heuristic — tests pin the
threshold math, the weight renormalisation and the honesty labelling
(NOT a probability, NOT VALIDATED). No network: WorldPop/OSM fetchers are
monkeypatched.
"""

import json
import os

import pytest

os.environ["HYDRASHIELD_CACHE_DB"] = "/tmp/hydrashield_test_ignition_cache.sqlite3"
if os.path.exists(os.environ["HYDRASHIELD_CACHE_DB"]):
    os.remove(os.environ["HYDRASHIELD_CACHE_DB"])

from src.dashboard import ignition as ignition_module  # noqa: E402
from src.dashboard.api import create_app  # noqa: E402


# --------------------------------------------------------------------------
# Declared constants (honesty labelling)
# --------------------------------------------------------------------------

def test_validation_status_is_not_validated():
    vs = ignition_module.VALIDATION_STATUS
    assert vs["validated"] is False
    assert "NOT VALIDATED" in vs["status"]
    assert "FIRMS" in vs["method_when_run"]
    assert "never promoted from a single event" in vs["promotion_rule"]


def test_not_a_probability_note_and_distinctions():
    assert "NOT a calibrated probability" in ignition_module.NOT_A_PROBABILITY_NOTE
    assert len(ignition_module.DISTINCTIONS) >= 3
    assert any("≠" in d for d in ignition_module.DISTINCTIONS)
    assert any("never merged" in d for d in ignition_module.DISTINCTIONS)


# --------------------------------------------------------------------------
# indicator_from_components (pure)
# --------------------------------------------------------------------------

def test_indicator_none_without_inputs():
    out = ignition_module.indicator_from_components()
    assert out["indicator"] is None
    assert out["class"] is None
    assert out["components"] == {}
    assert out["input_coverage"] == []
    assert "No real component inputs" in out["coverage_note"]


def test_indicator_class_thresholds_single_component():
    # Single component -> indicator equals the declared FFMC sub-score.
    cases = [(60.0, 10.0, "low"), (74.0, 25.0, "moderate"),
             (83.0, 60.0, "elevated"), (91.0, 95.0, "high")]
    for ffmc, expected, label in cases:
        out = ignition_module.indicator_from_components(ffmc=ffmc)
        assert out["indicator"] == expected
        assert out["class"] == label


def test_indicator_bounds_0_100():
    hot = ignition_module.indicator_from_components(
        ffmc=95.0, population_density_per_km2=3000.0, roads_mapped=200, fmc_pct=5.0)
    cold = ignition_module.indicator_from_components(
        ffmc=50.0, population_density_per_km2=0.5, roads_mapped=0, fmc_pct=40.0)
    assert 0.0 <= cold["indicator"] <= hot["indicator"] <= 100.0
    # weighted: 95*0.5 + (0.6*95+0.4*90)*0.3 + 95*0.2 = 94.4
    assert hot["indicator"] == 94.4
    assert hot["class"] == "high"


def test_indicator_weight_renormalisation_when_components_missing():
    out = ignition_module.indicator_from_components(ffmc=91.0)
    # Only fire_weather available: weight 0.5 renormalised to 1.0.
    assert out["indicator"] == 95.0
    assert out["input_coverage"] == ["fire_weather"]
    assert "renormalised" in out["coverage_note"]
    assert "human_presence" in out["coverage_note"]
    assert "fuel_dryness" in out["coverage_note"]


def test_indicator_human_presence_subweights():
    density_only = ignition_module.indicator_from_components(
        population_density_per_km2=300.0)
    assert density_only["components"]["human_presence"]["score"] == 60.0
    both = ignition_module.indicator_from_components(
        population_density_per_km2=300.0, roads_mapped=5)
    # 0.6*60 + 0.4*25 = 46.0
    assert both["components"]["human_presence"]["score"] == 46.0
    assert both["components"]["human_presence"]["inputs"]["roads_mapped_within_2km"] == 5


def test_indicator_fmc_preferred_over_ndmi():
    out = ignition_module.indicator_from_components(fmc_pct=10.0, ndmi=0.05)
    fuel = out["components"]["fuel_dryness"]
    assert fuel["inputs"] == {"fmc_pct": 10.0}
    assert fuel["score"] == 75.0
    ndmi_only = ignition_module.indicator_from_components(ndmi=0.05)
    assert ndmi_only["components"]["fuel_dryness"]["inputs"] == {"ndmi": 0.05}
    assert ndmi_only["components"]["fuel_dryness"]["score"] == 65.0


def test_indicator_non_burnable_landcover_note():
    out = ignition_module.indicator_from_components(ffmc=90.0, burnable=False)
    assert "non-burnable" in out["landcover_note"]
    burnable = ignition_module.indicator_from_components(ffmc=90.0, burnable=True)
    assert "landcover_note" not in burnable


# --------------------------------------------------------------------------
# build_ignition_block (WorldPop + OSM monkeypatched)
# --------------------------------------------------------------------------

def _analysis():
    return {
        "location": {"latitude": 37.6, "longitude": -6.5},
        "fire_danger": {"available": True, "ffmc": 90.0},
        "analysis": {"fuel_moisture_baseline_pct": 10.0},
        "satellite": {"ndmi": 0.1},
        "landcover": {"burnable": True},
    }


def _patch_inputs(monkeypatch, density=120.0, roads=25):
    monkeypatch.setattr(
        "src.dashboard.population.fetch_population",
        lambda lat, lon: {"status": "ok", "mean_density_per_km2": density})
    monkeypatch.setattr(
        "src.dashboard.exposure.fetch_osm_context",
        lambda lat, lon: {"counts": {"roads_all": roads}})


def test_ignition_block_ok_and_honestly_labelled(monkeypatch):
    _patch_inputs(monkeypatch)
    block = ignition_module.build_ignition_block(_analysis())
    assert block["status"] == "ok"
    # FFMC 90 -> 95; density 120 -> 60, roads 25 -> 50 -> human 56; FMC 10 -> 75
    # (95*0.5 + 56*0.3 + 75*0.2) / 1.0 = 79.3
    assert block["indicator"] == 79.3
    assert block["class"] == "high"
    assert isinstance(block["indicator"], (int, float)) and block["indicator"] <= 100
    assert block["weights"] == ignition_module.WEIGHTS
    assert block["model_version"] == ignition_module.MODEL_VERSION
    # honesty labelling
    assert block["validation_status"]["validated"] is False
    assert "NOT VALIDATED" in block["validation_status"]["status"]
    assert "NOT a calibrated probability" in block["not_a_probability"]
    assert block["distinctions"] == ignition_module.DISTINCTIONS
    assert "never folded into it" in block["separate_from_score_note"]
    assert "lightning" in block["lightning_note"]
    assert block["provenance"]["kind"] == "derived"
    assert block["provenance"]["quality"] == "ok"


def test_ignition_block_probability_word_only_in_negation(monkeypatch):
    _patch_inputs(monkeypatch)
    block = ignition_module.build_ignition_block(_analysis())
    text = json.dumps(block).lower()
    idx = 0
    occurrences = 0
    while True:
        i = text.find("probability", idx)
        if i == -1:
            break
        occurrences += 1
        window = text[max(0, i - 60):i]
        assert "not" in window, f"'probability' without negation near: {text[max(0, i-60):i+20]}"
        idx = i + 1
    assert occurrences > 0  # the negation wording must actually be present


def test_ignition_block_unavailable_without_components(monkeypatch):
    monkeypatch.setattr("src.dashboard.population.fetch_population",
                        lambda lat, lon: {"error": "no raster"})
    monkeypatch.setattr("src.dashboard.exposure.fetch_osm_context",
                        lambda lat, lon: {"error": "osm down"})
    analysis = {
        "location": {"latitude": 37.6, "longitude": -6.5},
        "fire_danger": {"available": False},
        "analysis": {},
        "satellite": {"error": "clouds"},
        "landcover": {"error": "unavailable"},
    }
    block = ignition_module.build_ignition_block(analysis)
    assert block["status"] == "unavailable"
    assert "No real component inputs" in block["reason"]
    assert block["validation_status"]["validated"] is False
    assert "NOT a calibrated probability" in block["not_a_probability"]
    assert block["provenance"]["kind"] == "unavailable"


def test_ignition_block_without_location_is_unavailable():
    block = ignition_module.build_ignition_block({"fire_danger": {"available": True}})
    assert block["status"] == "unavailable"
    assert block["reason"] == "No analysis location"


def test_ignition_block_degraded_quality_with_reduced_coverage(monkeypatch):
    # Only FFMC + OSM available (no WorldPop density, no fuel dryness).
    monkeypatch.setattr("src.dashboard.population.fetch_population",
                        lambda lat, lon: {"error": "no raster"})
    monkeypatch.setattr("src.dashboard.exposure.fetch_osm_context",
                        lambda lat, lon: {"counts": {"roads_all": 25}})
    analysis = _analysis()
    analysis["analysis"] = {}
    analysis["satellite"] = {"error": "clouds"}
    block = ignition_module.build_ignition_block(analysis)
    assert block["status"] == "ok"
    assert block["coverage_note"]
    assert "fuel_dryness" in block["coverage_note"]
    assert block["provenance"]["quality"] == "degraded"


# --------------------------------------------------------------------------
# /api/ignition-risk and /api/exposure-summary
# --------------------------------------------------------------------------

@pytest.fixture()
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _fake_analysis(lat=37.6, lon=-6.5):
    return {
        "location": {"latitude": lat, "longitude": lon, "name": "Testville"},
        "generated_at": "2026-08-17T00:00:00Z",
        "fire_danger": {"available": True, "fwi": 41.0, "class": "Extreme",
                        "effis_class": "Very high"},
        "analysis": {"risk": {"baseline": 68.0}},
        "ignition": {
            "status": "ok",
            "name": "Relative Ignition-Likelihood Indicator",
            "indicator": 55.0, "class": "elevated",
            "not_a_probability": ignition_module.NOT_A_PROBABILITY_NOTE,
            "validation_status": ignition_module.VALIDATION_STATUS,
        },
        "population": {
            "status": "ok",
            "estimated_population": 4820,
            "mean_density_per_km2": 170.8,
            "density_level": "high",
            "estimated_population_in_hazard_area": 4820,
            "estimate_note": ("Estimated population exposure based on WorldPop, "
                              "reference year 2025 — not an exact count."),
            "reference_year": 2025,
            "human_exposure_priority": "high",
            "human_exposure_note": "Very high hazard coincides with high density.",
        },
        "exposure": {
            "status": "ok",
            "exposure": {"buildings_mapped": 120},
            "vulnerable_assets": {"total": 3, "hospitals": 1},
            "wui_indicator": {"potential_wui": True},
        },
        "smoke_scenario": {
            "status": "ok",
            "mode_label": "SCENARIO / MODELLED — no fire is observed at this location",
            "transport": {"dominant_transport_direction": "E",
                          "mean_transport_speed_kmh": 18.5,
                          "confidence": "moderate"},
        },
        "provenance": {"ignition": {"kind": "derived"},
                       "population": {"kind": "modeled"}},
    }


def test_ignition_risk_endpoint_requires_input(client):
    assert client.get("/api/ignition-risk").status_code == 400


def test_ignition_risk_endpoint_ok(client, monkeypatch):
    monkeypatch.setattr("src.dashboard.api._cached_analysis",
                        lambda lat, lon, name: _fake_analysis(lat, lon))
    resp = client.get("/api/ignition-risk?lat=37.6&lon=-6.5")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ignition"]["indicator"] == 55.0
    assert body["ignition"]["validation_status"]["validated"] is False
    assert "NOT a calibrated probability" in body["ignition"]["not_a_probability"]
    assert "≠" in body["hazard_context"]["note"]
    assert body["hazard_context"]["fwi"] == 41.0


def test_ignition_risk_endpoint_upstream_failure(client, monkeypatch):
    def boom(lat, lon, name):
        raise RuntimeError("upstream timeout")
    monkeypatch.setattr("src.dashboard.api._cached_analysis", boom)
    resp = client.get("/api/ignition-risk?lat=37.6&lon=-6.5")
    assert resp.status_code == 502
    assert "upstream timeout" in resp.get_json()["error"]


def test_ignition_risk_endpoint_analysis_error(client, monkeypatch):
    monkeypatch.setattr("src.dashboard.api._cached_analysis",
                        lambda lat, lon, name: {"error": "no data here"})
    resp = client.get("/api/ignition-risk?lat=37.6&lon=-6.5")
    assert resp.status_code == 404


def test_exposure_summary_endpoint_ok(client, monkeypatch):
    monkeypatch.setattr("src.dashboard.api._cached_analysis",
                        lambda lat, lon, name: _fake_analysis(lat, lon))
    resp = client.get("/api/exposure-summary?lat=37.6&lon=-6.5")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["wildfire_hazard"]["fwi"] == 41.0
    assert body["wildfire_hazard"]["risk_score"] == 68.0
    assert body["population_exposure"]["reference_year"] == 2025
    assert "Estimated" in body["population_exposure"]["estimate_note"]
    assert body["ignition_likelihood"]["validation_status"]["validated"] is False
    assert body["smoke_scenario"]["dominant_transport_direction"] == "E"
    assert body["human_exposure_priority"] == "high"
    assert "separately" in body["separation_note"]
    assert "unvalidated" in body["separation_note"]


def test_exposure_summary_endpoint_without_smoke(client, monkeypatch):
    analysis = _fake_analysis()
    analysis.pop("smoke_scenario")
    monkeypatch.setattr("src.dashboard.api._cached_analysis",
                        lambda lat, lon, name: analysis)
    resp = client.get("/api/exposure-summary?lat=37.6&lon=-6.5")
    assert resp.status_code == 200
    assert resp.get_json()["smoke_scenario"] is None


def test_exposure_summary_endpoint_requires_input(client):
    assert client.get("/api/exposure-summary").status_code == 400


def test_exposure_summary_endpoint_upstream_failure(client, monkeypatch):
    def boom(lat, lon, name):
        raise RuntimeError("upstream timeout")
    monkeypatch.setattr("src.dashboard.api._cached_analysis", boom)
    resp = client.get("/api/exposure-summary?lat=37.6&lon=-6.5")
    assert resp.status_code == 502
