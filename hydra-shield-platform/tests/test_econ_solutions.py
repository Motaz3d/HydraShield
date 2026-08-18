"""Offline tests for the Stage-5 Economic Exposure layer
(src/climate/exposure_econ.py), the Solutions Intelligence engine
(src/climate/solutions.py + config/solutions_knowledge.json) and their
/api/v2 endpoints.

No network: all upstream fetchers are monkeypatched; the solutions engine
runs on synthetic site dicts (test fixtures, not product data).
"""

import os

import pytest

os.environ["HYDRASHIELD_CACHE_DB"] = "/tmp/hydrashield_test_econ_cache.sqlite3"
if os.path.exists(os.environ["HYDRASHIELD_CACHE_DB"]):
    os.remove(os.environ["HYDRASHIELD_CACHE_DB"])

from src.climate import exposure_econ as econ_module  # noqa: E402
from src.climate import solutions as sol_module  # noqa: E402
from src.climate.ontology import EvidenceClass, HazardType  # noqa: E402
from src.dashboard.api import create_app  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures: canned fetcher payloads
# ---------------------------------------------------------------------------

def _osm_counts():
    return {
        "counts": {
            "hospitals": 2, "schools": 5, "fire_stations": 1,
            "power_facilities": 3, "buildings": 214,
            "roads_all": 130, "roads_major": 6,
            "water_features": 4, "waterways": 2,
        },
        "count_date": "2026-07-01",
        "source": "OpenStreetMap via ohsome API (Heidelberg Institute)",
        "radius_m": 5000,
        "note": "Counts are mapped OSM features; OSM completeness varies by region.",
    }


def _landcover():
    return {
        "dominant_class": 40,
        "dominant_label": "Cropland",
        "dominant_fraction": 0.38,
        "histogram": {
            40: {"label": "Cropland", "fraction": 0.38},
            50: {"label": "Built-up", "fraction": 0.12},
            30: {"label": "Grassland", "fraction": 0.5},
        },
        "resolution": "10 m",
        "source": "ESA WorldCover 10m 2021 v200",
    }


def _sector_counts():
    return {
        "counts": {"tourism_features": 7, "industrial_areas": 3},
        "count_date": "2026-07-01",
        "source": "OpenStreetMap via ohsome API (Heidelberg Institute)",
    }


def _mock_fetchers(monkeypatch):
    monkeypatch.setattr(econ_module._exposure, "fetch_osm_context",
                        lambda lat, lon, radius_m=2000: _osm_counts())
    monkeypatch.setattr(econ_module, "fetch_landcover",
                        lambda lat, lon: _landcover())
    monkeypatch.setattr(econ_module, "_fetch_sector_counts",
                        lambda lat, lon, radius_m: _sector_counts())


# ---------------------------------------------------------------------------
# Economic exposure block
# ---------------------------------------------------------------------------

def test_economy_block_counts_and_no_fake_money(monkeypatch):
    _mock_fetchers(monkeypatch)
    out = econ_module.build_economic_exposure.__wrapped__(11.111, 22.222)
    exp = out["exposure"]
    assert exp["buildings"]["count"] == 214
    assert exp["buildings"]["status"] == "mapped"
    assert exp["critical_facilities"]["count"] == 8
    assert exp["critical_facilities"]["breakdown"]["schools"] == 5
    assert exp["transport"]["count"] == 130
    assert exp["transport"]["major_roads_mapped"] == 6
    assert exp["energy"]["count"] == 3
    assert exp["water"]["count"] == 6
    assert exp["tourism"]["count"] == 7
    assert exp["industry"]["count"] == 3
    assert exp["population"]["status"] == "proxy"
    assert exp["population"]["buildings_mapped"] == 214
    assert exp["agriculture"]["cropland_fraction"] == 0.38
    assert exp["agriculture"]["source"].startswith("ESA WorldCover")
    assert exp["built_up"]["built_up_fraction"] == 0.12
    assert exp["supply_chain"]["status"] == "not_mapped"

    mq = out["monetary_quantification"]
    assert mq["status"] == "not_quantified"
    assert mq["statement"] == (
        "Economic exposure cannot currently be quantified from available data.")

    assert out["framework"] == {
        "physical_risk": "exposure-profile stage",
        "transition_risk": "framework slot — no data",
        "business_interruption": "qualitative",
        "supply_chain": "framework slot — no data",
    }
    assert "provenance" in out
    assert out["provenance"]["evidence"]
    caveats = " ".join(
        str(v.get("completeness_caveat")) for v in exp.values())
    assert "completeness varies" in caveats


def test_economy_hazard_context_passthrough(monkeypatch):
    _mock_fetchers(monkeypatch)
    ctx = {"hazard": "wildfire", "status": "ok", "level": {"label": "High"}}
    out = econ_module.build_economic_exposure.__wrapped__(
        33.333, 44.444, hazard_context=ctx)
    assert out["hazard_context"]["hazard"] == "wildfire"
    out2 = econ_module.build_economic_exposure.__wrapped__(33.334, 44.445)
    assert out2["hazard_context"]["status"] == "not_provided"


def test_economy_osm_failure_is_honest(monkeypatch):
    monkeypatch.setattr(
        econ_module._exposure, "fetch_osm_context",
        lambda lat, lon, radius_m=2000: {"error": "OpenStreetMap context unavailable: down"})
    monkeypatch.setattr(econ_module, "fetch_landcover",
                        lambda lat, lon: {"error": "WorldCover read failed: x",
                                          "source": "ESA WorldCover 10m 2021 v200"})
    monkeypatch.setattr(econ_module, "_fetch_sector_counts",
                        lambda lat, lon, radius_m: None)
    out = econ_module.build_economic_exposure.__wrapped__(55.555, 66.666)
    assert out["exposure"]["buildings"]["status"] == "not_mapped"
    assert out["exposure"]["agriculture"]["status"] == "not_mapped"
    assert out["exposure"]["tourism"]["status"] == "not_mapped"
    # The no-fake-money rule holds even when everything upstream failed.
    assert out["monetary_quantification"]["status"] == "not_quantified"
    assert out["monetary_quantification"]["statement"] == (
        "Economic exposure cannot currently be quantified from available data.")
    assert out["provenance"]["evidence"]  # UNKNOWN record for the failure


def test_economy_rejects_bad_coordinates():
    out = econ_module.build_economic_exposure.__wrapped__(999.0, 0.0)
    assert "error" in out


# ---------------------------------------------------------------------------
# Solutions engine (synthetic site dicts)
# ---------------------------------------------------------------------------

def _site_full():
    return {
        "lat": 37.6, "lon": -6.5,
        "hazards": [{"id": "flood", "level": "High"},
                    {"id": "drought", "level": "Moderate"}],
        "climate_zone": "temperate",
        "moisture_regime": "dry",
        "elevation_m": 120.0,
        "landcover_classes": ["Cropland", "Grassland"],
        "water_features_count": 12,
        "buildings_count": 5,
        "historical_events": {"flood": "2 high-discharge events since 2015"},
    }


def test_solutions_fit_matching_and_why_it_fits():
    out = sol_module.recommend_solutions(_site_full())
    assert out["status"] == "ok"
    by_hazard = out["recommendations_by_hazard"]
    assert set(by_hazard) == {"flood", "drought"}

    flood_ids = [s["solution_id"] for s in by_hazard["flood"]]
    assert "wetland_restoration" in flood_ids
    wet = next(s for s in by_hazard["flood"]
               if s["solution_id"] == "wetland_restoration")
    # why_it_fits quotes real site values, not filler.
    assert "12 water features mapped" in wet["why_it_fits"]
    assert "2 high-discharge events since 2015" in wet["why_it_fits"]
    assert "level: High" in wet["why_it_fits"]

    drought_ids = [s["solution_id"] for s in by_hazard["drought"]]
    assert "smart_irrigation" in drought_ids
    irr = next(s for s in by_hazard["drought"]
               if s["solution_id"] == "smart_irrigation")
    assert "Cropland" in irr["why_it_fits"]
    assert irr["fit"]["conditions_matched"] == irr["fit"]["conditions_relevant"]

    # Sorted by fit score (descending).
    for solutions in by_hazard.values():
        scores = [s["fit_score"] for s in solutions]
        assert scores == sorted(scores, reverse=True)


def test_solutions_contract_fields_and_disclaimers():
    out = sol_module.recommend_solutions(_site_full())
    seen = []
    for solutions in out["recommendations_by_hazard"].values():
        seen.extend(solutions)
    assert seen
    for s in seen:
        assert s["limitations"], s["solution_id"]
        assert s["guarantee_disclaimer"] == "No solution guarantees prevention of an event."
        assert s["sources"], s["solution_id"]
        assert s["evidence"], s["solution_id"]
        for src in s["sources"]:
            assert src["name"] and src["url"].startswith("http")
            EvidenceClass(src["class"])
        assert s["expected_benefit"]["quantified"] is False
        assert s["cost_basis"] == "not quantified"
        assert s["data_confidence"] in ("high", "medium", "low")
    assert out["guarantee_disclaimer"] == "No solution guarantees prevention of an event."


def test_solutions_hard_conditions_exclude():
    out = sol_module.recommend_solutions(_site_full())  # buildings_count=5
    all_ids = [s["solution_id"]
               for sols in out["recommendations_by_hazard"].values()
               for s in sols]
    # Urban cooling requires >= 20 mapped buildings — excluded here.
    assert "urban_green_cooling" not in all_ids
    assert "suds_green_infrastructure" not in all_ids
    # smart_irrigation requires Cropland — a forest-only site must not get it.
    forest_site = dict(_site_full())
    forest_site["landcover_classes"] = ["Tree cover"]
    forest_site["hazards"] = [{"id": "drought"}]
    out2 = sol_module.recommend_solutions(forest_site)
    ids2 = [s["solution_id"] for s in out2["recommendations_by_hazard"]["drought"]]
    assert "smart_irrigation" not in ids2


def test_solutions_missing_values_are_unverified_not_assumed():
    site = {"lat": 50.0, "lon": 6.0, "hazards": [{"id": "heat", "level": "Moderate"}]}
    out = sol_module.recommend_solutions(site)
    assert out["status"] == "ok"
    heat = out["recommendations_by_hazard"]["heat"]
    assert heat
    green = next(s for s in heat if s["solution_id"] == "urban_green_cooling")
    # requires_urban could not be checked (no buildings count): unverified.
    assert any("unverified" in u for u in green["fit"]["unverified"])
    assert green["data_confidence"] in ("medium", "low")
    missing = {m["input"] for m in out["insufficient_data"]["missing_inputs"]}
    assert {"climate_zone", "moisture_regime", "elevation_m",
            "landcover_classes", "water_features_count",
            "buildings_count"} <= missing


def test_solutions_insufficient_data_without_hazards():
    out = sol_module.recommend_solutions({"lat": 1.0, "lon": 2.0, "hazards": []})
    assert out["status"] == "insufficient_data"
    assert "hazard levels" in out["message"]
    assert out["recommendations_by_hazard"] == {}
    inputs = {m["input"] for m in out["insufficient_data"]["missing_inputs"]}
    assert "hazards" in inputs
    assert out["guarantee_disclaimer"]


# ---------------------------------------------------------------------------
# Knowledge-base validation
# ---------------------------------------------------------------------------

_REQUIRED_FIELDS = [
    "solution_id", "name", "classes", "hazards_addressed", "economic_sectors",
    "applicability", "mechanism", "limitations", "implementation_complexity",
    "maintenance", "environmental_considerations", "technology_maturity",
    "cost_basis", "quantified", "confidence", "quantification_status",
    "sources",
]


def test_solutions_knowledge_base_is_valid():
    kb = sol_module.load_solutions_knowledge()
    entries = kb["solutions"]
    assert len(entries) >= 18
    declared_classes = set(kb["solution_classes"])
    ids = set()
    for e in entries:
        for field in _REQUIRED_FIELDS:
            assert e.get(field) is not None, (e["solution_id"], field)
        assert e["solution_id"] not in ids
        ids.add(e["solution_id"])
        assert set(e["classes"]) <= declared_classes
        for h in e["hazards_addressed"]:
            HazardType(h)  # raises on an unregistered hazard
        assert e["limitations"], e["solution_id"]
        assert e["economic_sectors"], e["solution_id"]
        assert e["confidence"] in ("high", "medium", "low")
        assert e["quantification_status"] == "not_quantified"
        assert e["sources"], e["solution_id"]
        for src in e["sources"]:
            assert src["name"] and src["url"].startswith("http")
            assert src.get("accessed"), (e["solution_id"], src["name"])
            EvidenceClass(src["class"])
        assert e["cost_basis"] == "not quantified"
        assert e["quantified"] is False

    # Coverage: every registered hazard and every declared class is served.
    all_hazards = {h for e in entries for h in e["hazards_addressed"]}
    assert all_hazards == {h.value for h in HazardType}
    all_classes = {c for e in entries for c in e["classes"]}
    assert all_classes == declared_classes


def test_solution_packages_reference_valid_solutions():
    """Every declared package references existing solutions and a
    registered hazard, and explains why the combination is useful."""
    kb = sol_module.load_solutions_knowledge()
    packages = kb.get("solution_packages")
    assert packages, "solution_packages must be declared in the KB"
    ids = {e["solution_id"] for e in kb["solutions"]}
    for pkg in packages:
        HazardType(pkg["hazard"])
        assert pkg["package_id"] and pkg["name"]
        assert len(pkg["components"]) >= 2, pkg["package_id"]
        for sid in pkg["components"]:
            assert sid in ids, (pkg["package_id"], sid)
        assert pkg.get("why_together"), pkg["package_id"]


# ---------------------------------------------------------------------------
# Fit bands, packages, sectors, resilience economics (Phase A)
# ---------------------------------------------------------------------------


def test_solutions_fit_bands_declared():
    full = sol_module.recommend_solutions(_site_full())
    seen = [s for sols in full["recommendations_by_hazard"].values() for s in sols]
    assert seen
    for s in seen:
        assert s["fit_band"] in ("high", "moderate", "low", "hazard_match_only")
        if s["fit"]["conditions_relevant"] == 0:
            assert s["fit_band"] == "hazard_match_only", s["solution_id"]
        elif s["fit_score"] >= 0.99:
            assert s["fit_band"] == "high", s["solution_id"]
    # A condition-free entry (water_conservation) must be honestly labelled.
    drought = full["recommendations_by_hazard"]["drought"]
    wc = next(s for s in drought if s["solution_id"] == "water_conservation")
    assert wc["fit_band"] == "hazard_match_only"


def test_solutions_packages_assemble_from_fitted_components():
    out = sol_module.recommend_solutions(_site_full())
    packages = {p["package_id"]: p for p in out["packages"]}
    # The full site fits flood and drought components of both packages.
    assert "flood_resilience_package" in packages
    assert "drought_resilience_package" in packages
    flood = packages["flood_resilience_package"]
    assert flood["hazard"] == "flood"
    assert len(flood["components"]) >= 2
    assert flood["why_together"]
    assert flood["guarantee_disclaimer"] == sol_module.GUARANTEE_DISCLAIMER
    for comp in flood["components"]:
        assert comp["fit_band"] and comp["name"]


def test_solutions_package_requires_two_fitted_components():
    """A package is offered only when at least two components actually fit
    the site — a single match stays a plain recommendation."""
    site = {
        "lat": 40.0, "lon": -3.7,
        "hazards": [{"id": "heat", "level": "High"}],
        # buildings_count=0 excludes both urban-cooling components, leaving
        # only heat_health_alerting — no package may be offered.
        "buildings_count": 0,
        "landcover_classes": ["Grassland"],
    }
    out = sol_module.recommend_solutions(site)
    heat_pkgs = [p for p in out["packages"] if p["hazard"] == "heat"]
    assert heat_pkgs == []
    heat = out["recommendations_by_hazard"]["heat"]
    assert [s["solution_id"] for s in heat] == ["heat_health_alerting"]


def test_solutions_site_sectors_are_declared_inference():
    out = sol_module.recommend_solutions(_site_full())
    sectors = {s["sector"]: s for s in out["site_sectors"]}
    # Cropland in the land-cover window → agriculture, with the basis stated.
    assert sectors["agriculture"]["status"] == "inferred"
    assert "'Cropland'" in sectors["agriculture"]["basis"]
    # 12 water features → water_utilities; 5 buildings → no urban inference.
    assert "water_utilities" in sectors
    assert "population_municipal" not in sectors


def test_solutions_resilience_economics_never_quantified():
    out = sol_module.recommend_solutions(_site_full())
    econ = out["resilience_economics"]
    assert econ["status"] == "not_quantified"
    assert set(econ["fields"]) == {
        "adaptation_cost", "avoided_loss", "resilience_investment",
        "maintenance_cost", "business_interruption_reduction",
    }
    assert all(v == "not_quantified" for v in econ["fields"].values())
    assert "documented source" in econ["rule"]


# ---------------------------------------------------------------------------
# /api/v2 endpoints (builders/fetchers mocked)
# ---------------------------------------------------------------------------

@pytest.fixture()
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_v2_economy_endpoint_requires_coordinates(client):
    assert client.get("/api/v2/economy").status_code == 400
    assert client.get("/api/v2/economy?lat=999&lon=0").status_code == 400


def test_v2_economy_endpoint_with_mocked_fetchers(client, monkeypatch):
    _mock_fetchers(monkeypatch)
    resp = client.get("/api/v2/economy?lat=1.234&lon=5.678&radius_km=3")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["exposure"]["buildings"]["count"] == 214
    assert data["monetary_quantification"]["status"] == "not_quantified"
    assert data["monetary_quantification"]["statement"] == (
        "Economic exposure cannot currently be quantified from available data.")
    assert data["radius_km"] == 3.0


def test_v2_economy_endpoint_tolerates_unknown_hazard(client, monkeypatch):
    _mock_fetchers(monkeypatch)
    resp = client.get("/api/v2/economy?lat=2.345&lon=6.789&hazard=tornado")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["hazard_context"]["status"] == "unavailable"
    assert "Unknown hazard" in data["hazard_context"]["reason"]


def test_v2_solutions_endpoint_requires_coordinates(client):
    assert client.get("/api/v2/solutions").status_code == 400


def test_v2_solutions_endpoint_with_mocked_site(client, monkeypatch):
    import src.climate.api_v2 as v2_module

    monkeypatch.setattr(v2_module, "_assemble_site",
                        lambda lat, lon: _site_full())
    resp = client.get("/api/v2/solutions?lat=37.6&lon=-6.5")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "ok"
    flood = data["recommendations_by_hazard"]["flood"]
    assert any(s["solution_id"] == "wetland_restoration" for s in flood)
    for s in flood:
        assert s["limitations"]
        assert s["guarantee_disclaimer"]


def test_v2_solutions_endpoint_honest_without_hazards(client, monkeypatch):
    import src.climate.api_v2 as v2_module

    monkeypatch.setattr(
        v2_module, "_assemble_site",
        lambda lat, lon: {"lat": lat, "lon": lon, "hazards": []})
    resp = client.get("/api/v2/solutions?lat=40.0&lon=-3.0")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "insufficient_data"
    inputs = {m["input"] for m in data["insufficient_data"]["missing_inputs"]}
    assert "hazards" in inputs


def test_v2_solutions_endpoint_accepts_caller_selected_hazards(client, monkeypatch):
    import src.climate.api_v2 as v2_module

    captured = {}

    def fake_assemble(lat, lon):
        return {"lat": lat, "lon": lon, "hazards": [], "climate_zone": "mediterranean"}

    def fake_recommend(site, knowledge_path=None):
        captured.update(site)
        return {"status": "ok", "site": site, "recommendations_by_hazard": {}}

    monkeypatch.setattr(v2_module, "_assemble_site", fake_assemble)
    import src.climate.solutions as solutions_module

    monkeypatch.setattr(solutions_module, "recommend_solutions", fake_recommend)

    resp = client.get("/api/v2/solutions?lat=37.6&lon=-6.5&hazards=wildfire,drought,tornado")
    assert resp.status_code == 200
    hazard_ids = {h["id"] for h in captured.get("hazards", [])}
    assert hazard_ids == {"wildfire", "drought"}  # valid registry ids only
    assert all(h["level"] is None and "caller-selected" in h["basis"]
               for h in captured["hazards"])
    assert captured.get("unknown_hazards_requested") == ["tornado"]


# ---------------------------------------------------------------------------
# Analytical models (the interpretation layer over real inputs)
# ---------------------------------------------------------------------------

def _cats_full():
    return {
        "buildings": {"status": "mapped", "count": 214},
        "critical_facilities": {"status": "mapped", "count": 8},
        "energy": {"status": "mapped", "count": 3},
        "tourism": {"status": "mapped", "count": 7},
        "industry": {"status": "mapped", "count": 2},
        "agriculture": {"status": "mapped", "cropland_fraction": 0.38},
        "built_up": {"status": "mapped", "built_up_fraction": 0.12},
        "water": {"status": "mapped", "count": 6},
        "transport": {"status": "mapped", "count": 130},
    }


def test_models_exposure_and_critical_concentration():
    m = econ_module.build_analytical_models(_cats_full(), None, 2000)
    ec = m["exposure_concentration"]
    assert ec["status"] == "ok"
    assert ec["output"]["band"] == "dense"  # 214 buildings / ~12.6 km²
    assert ec["output"]["buildings_per_km2"] > 0
    ci = m["critical_infrastructure"]
    assert ci["status"] == "ok"
    assert ci["output"]["critical_per_km2"] > 0
    assert "methodology" in ci


def test_models_economic_activity_sectors():
    m = econ_module.build_analytical_models(_cats_full(), None, 2000)
    sectors = {s["sector"] for s in m["economic_activity"]["output"]["sectors_present"]}
    assert "agriculture" in sectors
    assert "tourism" in sectors
    assert "industry" in sectors


def test_models_hazard_exposure_and_priority():
    m = econ_module.build_analytical_models(
        _cats_full(), {"hazard": "flood", "level": {"label": "High"}}, 2000)
    assert m["hazard_exposure"]["output"]["concern"] == "elevated"
    assert m["resilience_priority"]["output"]["priority"] == "high"
    # Without a hazard level the intersection is honestly not computed.
    m2 = econ_module.build_analytical_models(_cats_full(), None, 2000)
    assert m2["hazard_exposure"]["status"] == "not_computed"
    assert "not invented" in m2["hazard_exposure"]["reason"]


def test_models_never_fabricate_monetary():
    import re
    m = econ_module.build_analytical_models(_cats_full(), None, 2000)
    text = str(m)
    # No currency symbols or currency amounts anywhere in the models.
    assert "€" not in text and "$" not in text
    assert not re.search(r"\b(EUR|USD|GBP)\s*\d", text)


def test_models_unmapped_is_honest():
    cats = {"buildings": {"status": "not_mapped"},
            "critical_facilities": {"status": "not_mapped"}}
    m = econ_module.build_analytical_models(cats, None, 2000)
    assert m["exposure_concentration"]["status"] == "unavailable"
    assert m["evidence_completeness"]["output"]["mapped"] == 0


def test_economy_endpoint_includes_models(client, monkeypatch):
    _mock_fetchers(monkeypatch)
    resp = client.get("/api/v2/economy?lat=49.75&lon=6.64")
    assert resp.status_code == 200
    body = resp.get_json()
    assert "analytical_models" in body
    models = body["analytical_models"]
    for key in ("exposure_concentration", "critical_infrastructure",
                "economic_activity", "hazard_exposure",
                "resilience_priority", "evidence_completeness"):
        assert key in models, key
    assert body["monetary_quantification"]["status"] == "not_quantified"
