"""
Offline tests for the Compound Risk Engine v1 (src/climate/compound.py), the
Cascading Risk Graph v1 (src/climate/cascading.py +
config/cascading_graph.json), the Economic Impact Engine v1
(src/climate/economic_impact.py) and their /api/v2 analytics endpoints.

No network: per-hazard signals are synthetic fixtures; the wiring test
monkeypatches the registry analyzers and the ERA5 archive fetcher with
synthetic daily series (test fixtures, not product data). Endpoints run
against a Flask app registering only the analytics blueprint.
"""

import os
from datetime import date, timedelta

import pytest

# Isolate the cache DB for the whole test module.
os.environ["HYDRASHIELD_CACHE_DB"] = "/tmp/hydrashield_test_compound_cache.sqlite3"
if os.path.exists(os.environ["HYDRASHIELD_CACHE_DB"]):
    os.remove(os.environ["HYDRASHIELD_CACHE_DB"])

from flask import Flask  # noqa: E402

from src.climate import compound as compound_module  # noqa: E402
from src.climate import cascading as cascading_module  # noqa: E402
from src.climate import economic_impact as econ_impact_module  # noqa: E402
from src.climate import registry  # noqa: E402
from src.climate.api_analytics import analytics_bp  # noqa: E402
from src.climate.hazards.base import HazardAnalysis, HazardLevel  # noqa: E402
from src.dashboard import real_data  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_registry():
    registry.reset_for_tests()
    yield
    registry.reset_for_tests()


# ---------------------------------------------------------------------------
# Synthetic signal fixtures (compound detector inputs)
# ---------------------------------------------------------------------------


def _sig(hazard, elevated=False, values=None, spells=None, spell_kind=None,
         level_label="Low", ongoing=False):
    return {
        "hazard": hazard,
        "status": "ok",
        "level": {"label": level_label, "score": None, "score_max": None,
                  "basis": "synthetic fixture", "validated": False},
        "elevated": elevated,
        "elevated_basis": f"synthetic {hazard} breach" if elevated else None,
        "values": values or {},
        "spells": spells or [],
        "spell_kind": spell_kind,
        "spell_status": {"ongoing": ongoing},
        "evidence": [{"evidence_class": "OPEN_DATA_OFFICIAL",
                      "claim_status": "MODELLED", "temporal": "HISTORICAL",
                      "source": f"synthetic {hazard} source"}],
        "source": f"synthetic {hazard} source",
        "summary": f"synthetic {hazard} signal",
        "unavailable_reason": None,
    }


def _extracted(signals, unavailable=None, as_of="2026-08-12"):
    return {
        "location": {"lat": 10.0, "lon": 20.0},
        "generated_at": "2026-08-17T00:00:00Z",
        "as_of": as_of,
        "signals": signals,
        "hazards_unavailable": unavailable or [],
        "thresholds": dict(compound_module.ELEVATED_THRESHOLDS),
    }


def _assess(monkeypatch, extracted, lat=11.111, lon=22.222, **kw):
    monkeypatch.setattr(compound_module, "extract_light_signals",
                        lambda *a, **k: extracted)
    return compound_module.assess_compound.__wrapped__(lat, lon, **kw)


# ---------------------------------------------------------------------------
# Compound: multivariate detection
# ---------------------------------------------------------------------------


def test_compound_multivariate_detection(monkeypatch):
    signals = {
        "drought": _sig("drought", elevated=True, level_label="Moderate",
                        values={"min_standardized_anomaly": -1.4}),
        "heat": _sig("heat", elevated=True, level_label="High",
                     values={"percentile_vs_doy_climatology": 95.0,
                             "latest": {"date": "2026-08-11", "tmax_c": 38.5}}),
        "wildfire": _sig("wildfire", elevated=True, level_label="High",
                         values={"fwi_latest": 35.0,
                                 "fwi_latest_date": "2026-08-12"}),
        "wind": _sig("wind", elevated=False,
                     values={"percentile_vs_doy_climatology": 50.0}),
    }
    out = _assess(monkeypatch, _extracted(signals))
    assert out["status"] == "ok"
    multi = [s for s in out["compound_signals"] if s["type"] == "multivariate"]
    assert len(multi) == 1
    sig = multi[0]
    assert sig["hazards"] == ["drought", "heat", "wildfire"]
    # Real values are quoted, not filler.
    assert sig["values"]["drought"]["values"]["min_standardized_anomaly"] == -1.4
    assert sig["values"]["heat"]["values"]["percentile_vs_doy_climatology"] == 95.0
    assert sig["values"]["wildfire"]["values"]["fwi_latest"] == 35.0
    assert sig["claim_status"] == "MODELLED"
    assert sig["evidence"]
    assert "zscheischler2020typology" in sig["research"]
    assert "ipccar6wg2" in sig["research"]
    # A single elevated hazard must NOT trigger multivariate.
    out1 = _assess(monkeypatch, _extracted({"heat": signals["heat"]}),
                   lat=11.112, lon=22.223)
    assert [s for s in out1["compound_signals"]
            if s["type"] == "multivariate"] == []


def test_compound_temporal_sequence_detection(monkeypatch):
    dry_spell = {"start": "2026-05-20", "end": "2026-06-10",
                 "length_days": 22, "peak_value": 0.0, "peak_date": "2026-06-01"}
    heat_spell = {"start": "2026-06-15", "end": "2026-06-20",
                  "length_days": 6, "peak_value": 39.1, "peak_date": "2026-06-19"}
    signals = {
        "drought": _sig("drought", spells=[dry_spell], spell_kind="dry_spell",
                        values={"dry_spell_ongoing": False}),
        "heat": _sig("heat", spells=[heat_spell], spell_kind="heatwave",
                     values={"spell_ongoing": False}),
    }
    out = _assess(monkeypatch, _extracted(signals, as_of="2026-08-12"))
    temporal = [s for s in out["compound_signals"]
                if s["type"] == "temporally_compounding"]
    assert len(temporal) == 1
    sig = temporal[0]
    assert sig["hazards"] == ["drought", "heat"]
    seq = sig["sequences"][0]
    assert seq["preceding"]["spell"]["end"] == "2026-06-10"
    assert seq["following"]["spell"]["start"] == "2026-06-15"
    assert seq["gap_days"] == 5
    assert sig["window"]["days"] == 90
    assert sig["claim_status"] == "MODELLED"

    # A spell OUTSIDE the trailing 90-day window must not be reported.
    old_dry = {"start": "2026-01-01", "end": "2026-01-20",
               "length_days": 20, "peak_value": 0.0, "peak_date": "2026-01-10"}
    signals_old = {
        "drought": _sig("drought", spells=[old_dry], spell_kind="dry_spell"),
        "heat": _sig("heat", spells=[heat_spell], spell_kind="heatwave"),
    }
    out_old = _assess(monkeypatch, _extracted(signals_old, as_of="2026-08-12"),
                      lat=11.113, lon=22.224)
    assert [s for s in out_old["compound_signals"]
            if s["type"] == "temporally_compounding"] == []


def test_compound_preconditioned_is_inferred(monkeypatch):
    signals = {
        "drought": _sig("drought", values={
            "precipitation_90d": {
                "current_sum_mm": 12.0, "deficit_mm": 45.2,
                "standardized_anomaly": -1.3,
                "period": {"start": "2026-05-14", "end": "2026-08-11"}},
            "soil_moisture": {"anomaly_m3m3": -0.05,
                              "percentile_vs_climatology": 18.0,
                              "as_of": "2026-08-11"},
        }),
        "wildfire": _sig("wildfire", elevated=True,
                         values={"fwi_latest": 35.0,
                                 "fwi_latest_date": "2026-08-12"}),
        "heat": _sig("heat", ongoing=True,
                     values={"spell_ongoing": True,
                             "latest": {"date": "2026-08-11", "tmax_c": 38.5}}),
    }
    out = _assess(monkeypatch, _extracted(signals))
    pre = [s for s in out["compound_signals"] if s["type"] == "preconditioned"]
    assert len(pre) == 2
    by_hazard = {tuple(s["hazards"]): s for s in pre}
    fire_pre = by_hazard[("drought", "wildfire")]
    assert fire_pre["claim_status"] == "INFERRED"
    assert "plausibly amplifies" in fire_pre["mechanism"]
    assert fire_pre["values"]["precipitation_deficit_90d_mm"] == 45.2
    assert fire_pre["values"]["fwi_latest"] == 35.0
    heat_pre = by_hazard[("drought", "heat")]
    assert heat_pre["claim_status"] == "INFERRED"
    assert "evaporative cooling" in heat_pre["mechanism"]
    assert heat_pre["values"]["soil_moisture_anomaly_m3m3"] == -0.05


def test_compound_spatially_compounding_not_computable(monkeypatch):
    out = _assess(monkeypatch, _extracted({"heat": _sig("heat")}))
    sc = out["spatially_compounding"]
    assert sc["status"] == "not_computable"
    assert "single-point" in sc["reason"]


def test_compound_honest_empty_state_and_no_numeric_score(monkeypatch):
    signals = {
        "drought": _sig("drought", values={"min_standardized_anomaly": 0.2}),
        "heat": _sig("heat", values={"percentile_vs_doy_climatology": 40.0}),
    }
    out = _assess(monkeypatch, _extracted(signals))
    assert out["compound_signals"] == []
    assert out["no_compound_signal"]["status"] == "no_compound_signal"
    assert "absence of a signal" in out["no_compound_signal"]["statement"]
    # No invented metric anywhere.
    assert "score" not in out
    assert "compound_score" not in out
    for sig in out["compound_signals"]:
        assert "score" not in sig
    assert "No numeric compound score" in out["provenance"]["no_numeric_score"]


def test_compound_tolerates_unavailable_hazards(monkeypatch):
    signals = {"heat": _sig("heat", values={"percentile_vs_doy_climatology": 50.0})}
    unavailable = [{"hazard": "flood",
                    "reason": "No modelled river discharge at this location"}]
    out = _assess(monkeypatch, _extracted(signals, unavailable))
    assert out["status"] == "partial"
    assert out["hazards_unavailable"] == unavailable
    # Everything failing is honestly unavailable, never a crash.
    out_none = _assess(monkeypatch, _extracted({}, unavailable),
                       lat=11.114, lon=22.225)
    assert out_none["status"] == "unavailable"
    assert out_none["compound_signals"] == []


# ---------------------------------------------------------------------------
# Compound: wiring through the registry + ERA5 archive (all fetchers faked)
# ---------------------------------------------------------------------------


def _fake_analysis(hazard):
    loc = {"lat": 0.0, "lon": 0.0}
    if hazard == "drought":
        return HazardAnalysis(
            hazard="drought", location=loc, status="ok",
            summary="synthetic drought",
            level=HazardLevel(label="Moderate", score=-1.4, basis="synthetic"),
            blocks={
                "precipitation_deficit": {"status": "ok", "windows": {"90": {
                    "status": "ok", "current_sum_mm": 12.0, "deficit_mm": 45.2,
                    "standardized_anomaly": -1.3,
                    "current_period": {"start": "2026-05-14", "end": "2026-08-11"}}}},
                "soil_moisture": {"status": "ok", "anomaly_m3m3": -0.05,
                                  "percentile_vs_climatology": 18.0,
                                  "as_of": "2026-08-11"},
                "dry_spells": {"status": "ok", "spells_last_year": [{
                    "start": "2026-05-20", "end": "2026-06-10", "length_days": 22,
                    "peak_value": 0.0, "peak_date": "2026-06-01"}],
                    "count_last_year": 1, "ongoing": False},
            },
            evidence=[{"source": "synthetic ERA5 drought"}],
        )
    if hazard == "heat":
        return HazardAnalysis(
            hazard="heat", location=loc, status="ok", summary="synthetic heat",
            level=HazardLevel(label="High", score=95.0, basis="synthetic"),
            blocks={
                "current_vs_climatology": {"status": "ok",
                                           "latest": {"date": "2026-08-11",
                                                      "tmax_c": 38.5},
                                           "percentile_vs_doy_climatology": 95.0},
                "heatwave_spells": {"status": "ok", "spells": [{
                    "start": "2026-08-05", "end": "2026-08-11", "length_days": 7,
                    "peak_value": 39.1, "peak_date": "2026-08-10"}],
                    "count": 1, "ongoing": True},
            },
            evidence=[{"source": "synthetic ERA5 heat"}],
        )
    if hazard == "wind":
        return HazardAnalysis(
            hazard="wind", location=loc, status="ok", summary="synthetic wind",
            level=HazardLevel(label="Low", score=50.0, basis="synthetic"),
            blocks={
                "current_vs_climatology": {"status": "ok",
                                           "latest": {"date": "2026-08-11",
                                                      "gust_max_kmh": 40.0},
                                           "percentile_vs_doy_climatology": 50.0},
                "storm_spells": {"status": "ok", "spells": [], "count": 0,
                                 "ongoing": False},
            },
            evidence=[{"source": "synthetic ERA5 wind"}],
        )
    if hazard == "flood":
        return HazardAnalysis(
            hazard="flood", location=loc, status="unavailable",
            summary="Flood analysis unavailable for this location.",
            blocks={
                "river_discharge": {"status": "unavailable",
                                    "reason": "No modelled river at this location"},
                "extreme_precipitation": {"status": "unavailable",
                                          "reason": "synthetic"},
            },
            unavailable_reason="No modelled river discharge at this location",
        )
    raise AssertionError(hazard)


def _fake_fire_archive(lat, lon, start, end):
    end_d = date(2026, 8, 12)
    times = [(end_d - timedelta(days=119 - i)).isoformat() for i in range(120)]
    return {
        "time": times,
        "temperature_2m_max": [35.0] * 120,
        "temperature_2m_min": [20.0] * 120,
        "relative_humidity_2m_mean": [18.0] * 120,
        "wind_speed_10m_max": [25.0] * 120,
        "precipitation_sum": [0.0] * 120,
        "source": "Reanalysis (ERA5 via Open-Meteo archive)",
    }


def test_extract_light_signals_wiring(monkeypatch):
    class _FakeModule:
        def __init__(self, hid):
            self.id = hid

        def analyze(self, lat, lon, name=None, **kw):
            return _fake_analysis(self.id)

    monkeypatch.setattr(registry, "get",
                        lambda hid: _FakeModule(hid) if hid in
                        ("drought", "heat", "wind", "flood") else None)
    monkeypatch.setattr(real_data, "fetch_weather_archive", _fake_fire_archive)

    out = compound_module.extract_light_signals.__wrapped__(33.333, 44.444)
    signals = out["signals"]
    assert set(signals) == {"drought", "heat", "wind", "wildfire"}
    # Flood's honest no-river error is tolerated, never a crash.
    assert out["hazards_unavailable"] == [
        {"hazard": "flood",
         "reason": "No modelled river discharge at this location"}]

    assert signals["drought"]["elevated"] is True
    assert signals["drought"]["values"]["min_standardized_anomaly"] == -1.4
    assert signals["heat"]["elevated"] is True
    assert signals["heat"]["values"]["percentile_vs_doy_climatology"] == 95.0
    assert signals["wind"]["elevated"] is False
    fire = signals["wildfire"]
    assert fire["elevated"] is True
    assert fire["values"]["fwi_latest"] >= 30.0
    assert fire["values"]["fwi_latest_date"] == "2026-08-12"
    assert fire["spells"]  # high-FWI spell dates are real series dates
    assert fire["evidence"][0]["claim_status"] == "MODELLED"
    assert out["as_of"] == "2026-08-12"


def test_assess_compound_end_to_end_offline(monkeypatch):
    class _FakeModule:
        def __init__(self, hid):
            self.id = hid

        def analyze(self, lat, lon, name=None, **kw):
            return _fake_analysis(self.id)

    monkeypatch.setattr(registry, "get",
                        lambda hid: _FakeModule(hid) if hid in
                        ("drought", "heat", "wind", "flood") else None)
    monkeypatch.setattr(real_data, "fetch_weather_archive", _fake_fire_archive)

    out = compound_module.assess_compound.__wrapped__(33.334, 44.445)
    assert out["status"] == "partial"  # flood unavailable
    types = {s["type"] for s in out["compound_signals"]}
    # drought+heat+wildfire elevated -> multivariate
    assert "multivariate" in types
    # dry spell (ends 2026-06-10) -> heat spell (starts 2026-08-05) in window
    assert "temporally_compounding" in types
    # 90-day deficit 45.2 mm with FWI >= 30; soil deficit during heat spell
    assert "preconditioned" in types
    assert out["spatially_compounding"]["status"] == "not_computable"
    assert out["no_compound_signal"] is None
    assert "score" not in out
    assert out["hazards_unavailable"][0]["hazard"] == "flood"
    research_ids = {r["id"] for r in out["provenance"]["research"]}
    assert research_ids == {"zscheischler2020typology", "ipccar6wg2"}


# ---------------------------------------------------------------------------
# Cascading graph
# ---------------------------------------------------------------------------


def _synthetic_exposure():
    def _cat(count, desc):
        return {"status": "mapped", "count": count, "description": desc,
                "source": "OpenStreetMap via ohsome API (Heidelberg Institute)",
                "completeness_caveat": "OSM completeness varies by region.",
                "analysis_window": "current conditions"}

    return {
        "location": {"lat": 0.0, "lon": 0.0},
        "radius_km": 5.0,
        "analysis_window": "current conditions",
        "exposure": {
            "buildings": _cat(214, "buildings"),
            "critical_facilities": {
                "status": "mapped", "count": 8,
                "breakdown": {"hospitals": 2, "schools": 5, "fire_stations": 1},
                "source": "OSM", "completeness_caveat": "varies"},
            "transport": _cat(130, "roads"),
            "energy": _cat(3, "power"),
            "water": _cat(6, "water"),
            "tourism": _cat(7, "tourism"),
            "industry": _cat(3, "industry"),
            "agriculture": {"status": "mapped", "count": None,
                            "cropland_fraction": 0.38, "source": "ESA WorldCover",
                            "completeness_caveat": "10 m classification"},
            "ports_logistics": {"status": "not_mapped", "count": None,
                                "reason": "Foundation stage"},
        },
        "monetary_quantification": {"status": "not_quantified"},
        "provenance": {"evidence": [{"source": "synthetic exposure evidence"}]},
    }


def test_cascading_graph_config_loads_and_validates():
    graph = cascading_module.load_cascading_graph()
    assert graph["graph_id"] == "cascading_risk_graph_v1"
    problems = cascading_module.validate_cascading_graph(graph)
    assert problems == []
    systems = graph["nodes"]["systems"]
    for expected in ("power_grid", "water_supply", "roads", "rail", "ports",
                     "hospitals", "schools", "agriculture", "tourism",
                     "industry", "logistics", "telecom", "business_continuity"):
        assert expected in systems
    for edge in graph["edges"]:
        assert edge["quantified"] is False
        assert edge["evidence_class"] in ("SCIENTIFIC", "OPEN_DATA_OFFICIAL")
        assert edge["mechanism"]
    assert "NOT quantified" in graph["not_quantified_statement"]


def _patch_cascading(monkeypatch, signals, exposure):
    extracted = _extracted(signals)
    monkeypatch.setattr(cascading_module, "extract_light_signals",
                        lambda *a, **k: extracted)
    monkeypatch.setattr(cascading_module, "build_economic_exposure",
                        lambda *a, **k: exposure)


def test_cascading_path_relevance_from_synthetic_anchors(monkeypatch):
    signals = {
        "wildfire": _sig("wildfire", elevated=True, level_label="High",
                         values={"fwi_latest": 35.0}),
        "heat": _sig("heat", elevated=False,
                     values={"percentile_vs_doy_climatology": 50.0}),
    }
    _patch_cascading(monkeypatch, signals, _synthetic_exposure())
    out = cascading_module.assess_cascading.__wrapped__(55.555, 66.666)
    assert out["status"] == "ok"
    assert [h["hazard"] for h in out["active_hazards"]] == ["wildfire"]
    assert out["no_cascade_signal"] is None
    assert out["exposure_status"] == "ok"

    node_sets = [tuple(p["nodes"]) for p in out["cascade_paths"]]
    assert ("wildfire", "power_grid", "hospitals") in node_sets
    assert ("wildfire", "power_grid", "water_supply", "hospitals") in node_sets
    # Agriculture has a fraction anchor (0.38 > 0) — relevant.
    assert ("wildfire", "agriculture") in node_sets
    # Heat is not elevated -> no heat paths.
    assert all(p["hazard"] == "wildfire" for p in out["cascade_paths"])

    for path in out["cascade_paths"]:
        assert path["not_quantified_statement"] == (
            "Propagation likelihoods and losses are NOT quantified — this is a "
            "structural relevance graph, not a loss model.")
        assert all(e["quantified"] is False for e in path["edges"])
        assert all(e["mechanism"] for e in path["edges"])
    grid_path = next(p for p in out["cascade_paths"]
                     if p["nodes"] == ["wildfire", "power_grid", "hospitals"])
    assert grid_path["anchors"]["power_grid"]["value"] == 3
    assert grid_path["anchors"]["hospitals"]["value"] == 2
    # Downstream nodes without anchors are honest, never invented.
    telecom_path = next(p for p in out["cascade_paths"]
                        if p["nodes"] == ["wildfire", "power_grid", "telecom"])
    assert telecom_path["anchors"]["telecom"]["status"] == "no_anchor"
    assert telecom_path["anchors"]["telecom"]["value"] is None
    assert telecom_path["fully_anchored"] is False
    assert "NOT quantified" in out["not_quantified_statement"]
    research_ids = {r["id"] for r in out["provenance"]["research"]}
    assert "ipccar6wg2" in research_ids


def test_cascading_honest_empty_state(monkeypatch):
    signals = {"heat": _sig("heat", elevated=False)}
    _patch_cascading(monkeypatch, signals, _synthetic_exposure())
    out = cascading_module.assess_cascading.__wrapped__(55.556, 66.667)
    assert out["cascade_paths"] == []
    assert out["no_cascade_signal"]["status"] == "no_active_hazards"
    assert "No hazard is currently elevated" in (
        out["no_cascade_signal"]["statement"])


def test_cascading_insufficient_exposure(monkeypatch):
    signals = {"wildfire": _sig("wildfire", elevated=True)}
    _patch_cascading(monkeypatch, signals,
                     {"error": "OpenStreetMap context unavailable: down"})
    out = cascading_module.assess_cascading.__wrapped__(55.557, 66.668)
    assert out["exposure_status"] == "insufficient"
    assert out["cascade_paths"] == []
    assert out["no_cascade_signal"]["status"] == "insufficient_exposure"
    assert out["exposure_note"]


def test_cascading_caller_declared_hazards(monkeypatch):
    monkeypatch.setattr(cascading_module, "build_economic_exposure",
                        lambda *a, **k: _synthetic_exposure())
    out = cascading_module.assess_cascading.__wrapped__(
        55.558, 66.669, active_hazards=["coastal", "tornado"])
    assert [h["hazard"] for h in out["active_hazards"]] == ["coastal"]
    assert "caller-declared" in out["active_hazards_basis"]
    node_sets = [tuple(p["nodes"]) for p in out["cascade_paths"]]
    assert ("coastal", "tourism") in node_sets
    # ports_logistics is not_mapped in the synthetic exposure -> no port paths.
    assert ("coastal", "ports") not in node_sets
    assert any(u["hazard"] == "tornado" for u in out["hazards_unavailable"])


# ---------------------------------------------------------------------------
# Economic impact
# ---------------------------------------------------------------------------


def test_economic_impact_three_blocks_strictly_separated(monkeypatch):
    monkeypatch.setattr(econ_impact_module, "build_economic_exposure",
                        lambda *a, **k: _synthetic_exposure())
    out = econ_impact_module.assess_economic_impact.__wrapped__(66.666, 11.111)
    assert out["status"] == "ok"

    observed = out["observed_losses"]
    assert observed["status"] == "unavailable"
    assert observed["statement"] == "No documented loss figures in integrated sources."
    assert observed["research_candidates"]

    modelled = out["modelled_estimates"]
    assert modelled["status"] == "ok"
    assert modelled["monetary_quantification"]["status"] == "not_quantified"
    assert modelled["monetary_quantification"]["statement"] == (
        "Economic exposure cannot currently be quantified from available data.")
    # Exposure-bounded: real categories + counts + caveats, nothing more.
    assert modelled["exposure_profile"]["buildings"]["count"] == 214
    assert modelled["caveats"]
    assert "losses" not in modelled
    assert "estimate_eur" not in modelled

    projections = out["projections"]
    assert projections["status"] == "not_available"
    assert projections["statement"] == (
        "Economic projections require scenario-labelled datasets not yet integrated.")

    # The Talaix loss screening estimate: the engine's own ESTIMATED block,
    # computed from the SAME real building count (fallback benchmarks here —
    # the synthetic point matches no country bbox).
    estimate = out["loss_screening_estimate"]
    assert estimate["status"] == "ok"
    assert estimate["claim_status"] == "ESTIMATED"
    ev = estimate["estimate"]["exposed_value_eur"]
    assert ev["low"] == 214 * 80 * 900
    assert ev["central"] == 214 * 120 * 1400
    assert ev["high"] == 214 * 200 * 2200
    assert estimate["expected_loss"]["status"] == "not_available"
    assert "fallback" in estimate["inputs"]["country_benchmark"]["name"]
    assert estimate["inputs"]["buildings_count"]["value"] == 214
    assert "never merged with DOCUMENTED" in estimate["separation_note"]

    assert out["confidence"] == "low"
    assert observed["confidence"] == "low"
    assert modelled["confidence"] == "low"
    assert projections["confidence"] == "low"
    assert out["evidence"]
    # Money strings may live ONLY inside the ESTIMATED block — every other
    # block stays money-free (no-fake-money rule).
    import json as _json
    clean = {k: v for k, v in out.items() if k != "loss_screening_estimate"}
    blob = _json.dumps(clean).lower()
    assert "€" not in blob and "eur " not in blob and "$" not in blob


def test_economic_impact_exposure_failure_is_honest(monkeypatch):
    monkeypatch.setattr(
        econ_impact_module, "build_economic_exposure",
        lambda *a, **k: {"error": "Coordinates out of range"})

    out = econ_impact_module.assess_economic_impact.__wrapped__(66.667, 11.112)
    assert out["status"] == "partial"
    assert out["modelled_estimates"]["status"] == "unavailable"
    assert out["modelled_estimates"]["monetary_quantification"]["status"] == (
        "not_quantified")
    assert out["observed_losses"]["status"] == "unavailable"
    assert out["loss_screening_estimate"]["status"] == "unavailable"
    assert out["projections"]["status"] == "not_available"
    assert out["confidence"] == "low"


# ---------------------------------------------------------------------------
# /api/v2 analytics endpoints
# ---------------------------------------------------------------------------


@pytest.fixture()
def client():
    app = Flask("test_analytics")
    app.config["TESTING"] = True
    app.register_blueprint(analytics_bp)
    with app.test_client() as c:
        yield c


def test_analytics_endpoints_require_coordinates(client):
    for path in ("/api/v2/compound", "/api/v2/cascading", "/api/v2/economic-impact"):
        assert client.get(path).status_code == 400
        assert client.get(f"{path}?lat=999&lon=0").status_code == 400


def test_compound_endpoint_with_mocked_engine(client, monkeypatch):
    import src.climate.compound as eng

    monkeypatch.setattr(eng, "assess_compound", lambda lat, lon: {
        "status": "ok", "location": {"lat": lat, "lon": lon},
        "hazards_analysed": ["heat"], "compound_signals": [],
        "spatially_compounding": {"status": "not_computable"},
    })
    resp = client.get("/api/v2/compound?lat=37.6&lon=-6.5")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "ok"
    env = data["uncertainty_envelope"]
    for key in ("source", "timestamp", "method", "confidence", "coverage",
                    "block_status"):
        assert key in env
    assert env["block_status"]["spatially_compounding"] == "not_computable"


def test_cascading_endpoint_with_mocked_engine(client, monkeypatch):
    import src.climate.cascading as eng

    monkeypatch.setattr(eng, "assess_cascading", lambda lat, lon: {
        "status": "ok", "location": {"lat": lat, "lon": lon},
        "cascade_paths": [], "no_cascade_signal": {"status": "no_active_hazards"},
    })
    resp = client.get("/api/v2/cascading?lat=37.6&lon=-6.5")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["cascade_paths"] == []
    assert data["uncertainty_envelope"]["block_status"]["exposure_anchors"] == (
        "observed")


def test_economic_impact_endpoint_with_mocked_engine(client, monkeypatch):
    import src.climate.economic_impact as eng

    monkeypatch.setattr(eng, "assess_economic_impact", lambda lat, lon: {
        "status": "ok", "location": {"lat": lat, "lon": lon},
        "observed_losses": {"status": "unavailable"},
        "modelled_estimates": {"status": "ok"},
        "projections": {"status": "not_available"},
    })
    resp = client.get("/api/v2/economic-impact?lat=37.6&lon=-6.5")
    assert resp.status_code == 200
    data = resp.get_json()
    env = data["uncertainty_envelope"]
    assert env["confidence"] == "low"
    assert env["block_status"] == {
        "observed_losses": "unavailable",
        "modelled_estimates": "modelled",
        "loss_screening_estimate": "unavailable",
        "projections": "unavailable",
    }
