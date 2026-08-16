"""Tests for the intelligence layers: explanation, change, recommendations,
automation action plans, history — all network-free."""

import os

import pytest

os.environ["HYDRASHIELD_CACHE_DB"] = "/tmp/hydrashield_test_intel_cache.sqlite3"
if os.path.exists(os.environ["HYDRASHIELD_CACHE_DB"]):
    os.remove(os.environ["HYDRASHIELD_CACHE_DB"])

from src.dashboard import explain as explain_module  # noqa: E402
from src.dashboard import change as change_module  # noqa: E402
from src.dashboard import recommendations as recs_module  # noqa: E402
from src.dashboard import history as history_module  # noqa: E402
from src.dashboard.api import create_app  # noqa: E402


# --------------------------------------------------------------------------
# Risk explanation
# --------------------------------------------------------------------------

def test_explanation_levels_follow_inputs_not_hardcoded():
    hot = explain_module.build_risk_explanation(
        fwi=45.0, fmc=10.0, slope=18.0, wind_kmh=35.0, landcover_label="Tree cover",
        burnable=True, score=70.0, risk_class="Extreme", fmc_source="x")
    mild = explain_module.build_risk_explanation(
        fwi=5.0, fmc=35.0, slope=2.0, wind_kmh=8.0, landcover_label="Built-up",
        burnable=False, score=12.0, risk_class="Low", fmc_source="x")

    def levels(ex):
        return {f["key"]: f["level"] for f in ex["factors"]}

    assert levels(hot)["fire_weather"] == "Extreme"
    assert levels(mild)["fire_weather"] == "Low"
    assert levels(hot)["fuel_dryness"] == "Very dry"
    assert levels(mild)["fuel_dryness"] == "Moist"
    assert levels(hot)["terrain"] == "Steep"
    assert levels(mild)["terrain"] == "Flat"
    assert levels(mild)["vegetation"] == "Non-burnable"


def test_explanation_contributions_match_score_formula():
    ex = explain_module.build_risk_explanation(
        fwi=25.0, fmc=10.0, slope=22.5, wind_kmh=10.0, landcover_label="Shrubland",
        burnable=True, score=60.0, risk_class="High", fmc_source="x")
    factors = {f["key"]: f for f in ex["factors"]}
    # base = 100*25/(25+25) = 50; slope = 22.5/45*8 = 4; fmc<12 -> +6
    assert factors["fire_weather"]["contribution"] == 50.0
    assert factors["terrain"]["contribution"] == 4.0
    assert factors["fuel_dryness"]["contribution"] == 6.0
    # wind is context, not a score input when FWI is present
    assert factors["wind"]["affects_score"] is False


def test_explanation_unavailable_fwi_is_honest():
    ex = explain_module.build_risk_explanation(
        fwi=None, fmc=None, slope=5.0, wind_kmh=10.0, landcover_label=None,
        burnable=True, score=None, risk_class=None, fmc_source=None)
    factors = {f["key"]: f for f in ex["factors"]}
    assert factors["fire_weather"]["level"] is None
    assert factors["fire_weather"]["provenance_kind"] == "unavailable"
    assert "not a probability" in ex["disclaimer"]


def test_compact_factors():
    ex = explain_module.build_risk_explanation(
        fwi=30.0, fmc=15.0, slope=5.0, wind_kmh=10.0, landcover_label="Tree cover",
        burnable=True, score=55.0, risk_class="High", fmc_source="x")
    compact = explain_module.compact_factors(ex)
    assert all(set(f.keys()) == {"key", "label", "value", "unit", "level", "level_rank"}
               for f in compact)
    assert compact[0]["key"] == "fire_weather"


# --------------------------------------------------------------------------
# What changed?
# --------------------------------------------------------------------------

def _daily(days):
    return {"days": days}


def _fwi_block(series):
    return {"available": True, "series": series}


def _series(base_fwi, step, n=10):
    days, fwis = [], []
    for i in range(n):
        d = f"2026-08-{i + 1:02d}"
        days.append({"date": d, "temp_max_c": 25.0 + i * step,
                     "rh_min_pct": 40.0, "wind_mean_kmh": 15.0,
                     "precipitation_mm": 0.0})
        fwis.append({"date": d, "fwi": base_fwi + i * step})
    return _daily(days), _fwi_block(fwis)


def test_change_block_deltas_and_explanation():
    daily, fwi_block = _series(20.0, 3.0)  # FWI rising 20 -> 47
    ch = change_module.build_change_block(daily, fwi_block, slope=5.0, satellite={"error": "x"})
    assert ch["available"] is True
    assert ch["risk"]["d7d_ago"] < ch["risk"]["today"]
    assert ch["risk"]["delta_7d"] > 0
    fwi_driver = next(d for d in ch["drivers_7d"] if d["key"] == "fwi")
    assert fwi_driver["significant"] is True
    assert fwi_driver["direction"] == "up"
    assert "strengthened" in ch["explanation"]
    assert "Risk increased" in ch["explanation"]
    assert ch["ndmi_change"]["available"] is False  # honestly unavailable


def test_change_block_stable_conditions():
    daily, fwi_block = _series(20.0, 0.1)
    ch = change_module.build_change_block(daily, fwi_block, slope=5.0, satellite=None)
    assert ch["available"] is True
    assert "stable" in ch["explanation"].lower()


def test_change_block_unavailable_without_series():
    ch = change_module.build_change_block({"days": []}, {"available": False}, slope=0.0)
    assert ch["available"] is False
    assert "reason" in ch


# --------------------------------------------------------------------------
# Proactive recommendations
# --------------------------------------------------------------------------

def _analysis_for_recs(fwi=None, fmc=None, wind=None, slope=None, risk=None,
                       trend=None, fires=None):
    return {
        "fire_danger": ({"available": True, "fwi": fwi, "class": "High"}
                        if fwi is not None else {"available": False}),
        "analysis": {"fuel_moisture_baseline_pct": fmc,
                     "risk": {"baseline": risk}},
        "weather": {"wind_speed_kmh": wind},
        "terrain": {"slope_degrees": slope},
        "landcover": {"burnable": True, "dominant_label": "Tree cover"},
        "active_fires": fires or {"available": False},
        "fire_danger_trend": ({"trend": trend, "slope_per_day": 1.4}
                              if trend else {"trend": "steady", "slope_per_day": 0.1}),
    }


def test_no_recommendations_without_conditions():
    recs = recs_module.build_recommendations(
        _analysis_for_recs(fwi=5.0, fmc=30.0, wind=5.0, slope=2.0, risk=10.0))
    assert recs == []


def test_recommendations_fire_on_real_conditions_with_evidence():
    recs = recs_module.build_recommendations(
        _analysis_for_recs(fwi=45.0, fmc=10.0, wind=30.0, slope=15.0,
                           risk=70.0, trend="rising"))
    ids = [r["id"] for r in recs]
    assert "fwi-high" in ids and "fuel-very-dry" in ids
    assert "wind-dry" in ids and "terrain-steep" in ids
    assert "trend-rising" in ids and "risk-high" in ids
    for r in recs:
        assert r["what"] and r["why"] and r["expected_effect"]
        assert r["evidence"]["value"] is not None  # quotes the real value
        assert r["data_sources"]
    # critical/high first
    assert recs[0]["priority"] in ("critical", "high")


def test_recommendation_values_appear_in_reason():
    recs = recs_module.build_recommendations(_analysis_for_recs(fmc=11.3))
    assert len(recs) == 1
    assert "11.3" in recs[0]["why"]


# --------------------------------------------------------------------------
# Automation action plan
# --------------------------------------------------------------------------

def test_action_plan_requires_config_for_external_actions():
    analysis = _analysis_for_recs(fwi=45.0, fmc=10.0, wind=30.0, risk=82.0)
    analysis["analysis"]["risk"]["class"] = "Extreme"
    plan = recs_module.build_action_plan(analysis, [], ops_config={"enabled": False, "contacts": {}})
    assert plan["level"] == "escalate"
    assert plan["automation_enabled"] is False
    external = [a for a in plan["actions"] if a["type"] == "recommended"]
    assert external  # escalate level generates external actions
    for a in external:
        assert a["status"] == "requires_operational_configuration"
        assert a["outcome"] is None  # never claimed
    for a in plan["actions"]:
        if a["type"] == "automated":
            assert a["status"] == "available_not_armed"


def test_action_plan_configured_contacts():
    cfg = {"enabled": True, "contacts": {"municipality": {"name": "CP Unit"}}}
    analysis = _analysis_for_recs(fwi=45.0, fmc=10.0, risk=70.0)
    analysis["analysis"]["risk"]["class"] = "High"
    plan = recs_module.build_action_plan(analysis, [], ops_config=cfg)
    muni = next(a for a in plan["actions"] if a["id"] == "notify-municipality")
    assert muni["status"] == "configured"
    assert muni["responsible"] == {"name": "CP Unit"}
    auto = [a for a in plan["actions"] if a["type"] == "automated"]
    assert all(a["status"] == "armed" for a in auto)


def test_action_plan_low_risk_is_routine():
    analysis = _analysis_for_recs(fwi=3.0, risk=5.0)
    analysis["analysis"]["risk"]["class"] = "Low"
    plan = recs_module.build_action_plan(analysis, [], ops_config={})
    assert plan["level"] == "routine"
    assert all(a["type"] == "automated" for a in plan["actions"]) or not plan["actions"]


def test_operations_config_default_disabled():
    cfg = recs_module.load_operations_config("/nonexistent/path.json")
    assert cfg["enabled"] is False
    assert cfg["contacts"] == {}


# --------------------------------------------------------------------------
# History / lessons
# --------------------------------------------------------------------------

def _archive(n=30):
    return {
        "time": [f"2026-07-{i + 1:02d}" for i in range(n)],
        "temperature_2m_max": [30.0] * n,
        "relative_humidity_2m_mean": [25.0] * n,
        "wind_speed_10m_max": [20.0] * n,
        "precipitation_sum": [0.0] * n,
        "source": "Reanalysis (ERA5 via Open-Meteo archive)",
    }


def test_fwi_series_from_archive():
    series = history_module._fwi_series_from_archive(_archive())
    assert len(series) == 30
    assert all("fwi" in d and "date" in d for d in series)
    # hot, dry, windy -> meaningful FWI
    assert series[-1]["fwi"] > 5.0


def test_high_risk_periods_detection():
    series = [{"date": f"2026-07-{i + 1:02d}", "fwi": fwi, "temp_max_c": 30.0,
               "wind_kmh": 15.0, "rain_mm": 0.0}
              for i, fwi in enumerate([5, 5, 45, 48, 50, 5, 5])]
    periods = history_module._high_risk_periods(series, slope=5.0, threshold=65.0)
    assert len(periods) == 1
    assert periods[0]["start"] == "2026-07-03"
    assert periods[0]["end"] == "2026-07-05"
    assert periods[0]["days"] == 3
    assert periods[0]["max_fwi"] == 50


def test_fires_unavailable_without_key(monkeypatch):
    monkeypatch.delenv("FIRMS_MAP_KEY", raising=False)
    fires = history_module._observed_fires(37.6, -6.5, "2026-07-01", "2026-07-31")
    assert fires["available"] is False
    assert "FIRMS_MAP_KEY" in fires["reason"]


def test_lesson_labels_and_no_invented_interventions():
    period = {"start": "2026-07-03", "end": "2026-07-05", "days": 3,
              "max_risk": 72.0, "peak_date": "2026-07-05", "max_fwi": 50.0,
              "mean_wind_kmh": 18.0, "total_rain_mm": 0.0}
    lesson = history_module._lesson_for_period(period, {"available": False})
    assert lesson["conditions"]["label"] == "MODELLED"
    assert lesson["hydrashield_score"]["label"] == "MODELLED"
    assert lesson["observed_fire"]["label"] == "UNKNOWN"
    assert lesson["interventions_recorded"]["label"] == "UNKNOWN"
    assert "unknown" in lesson["interventions_recorded"]["status"]
    for r in lesson["would_recommend"]:
        assert r["label"] == "RECOMMENDED"


def test_lesson_with_observed_fires():
    period = {"start": "2026-07-03", "end": "2026-07-05", "days": 3,
              "max_risk": 72.0, "peak_date": "2026-07-05", "max_fwi": 50.0,
              "mean_wind_kmh": 18.0, "total_rain_mm": 0.0}
    fires = {"available": True, "source": "NASA FIRMS",
             "points": [{"date": "2026-07-04", "lat": 1.0, "lon": 2.0},
                        {"date": "2026-07-20", "lat": 1.0, "lon": 2.0}]}
    lesson = history_module._lesson_for_period(period, fires)
    assert lesson["observed_fire"]["label"] == "OBSERVED"
    assert "1 fire detection" in lesson["observed_fire"]["status"]


def test_compute_history_with_mocked_sources(monkeypatch):
    monkeypatch.setattr(history_module.real_data, "fetch_terrain",
                        lambda lat, lon: {"slope_degrees": 8.0, "source": "DEM"})
    monkeypatch.setattr(history_module.real_data, "fetch_weather_archive",
                        lambda lat, lon, s, e: _archive(30))
    monkeypatch.delenv("FIRMS_MAP_KEY", raising=False)
    out = history_module.compute_history.__wrapped__(37.6, -6.5, "Test", 30)
    assert "error" not in out
    assert out["window"]["days"] == 30
    assert out["fire_observations"]["available"] is False
    assert out["provenance"]["history"]["kind"] == "modeled"
    assert out["provenance"]["fire_observations"]["kind"] == "unavailable"


# --------------------------------------------------------------------------
# /api/history endpoint
# --------------------------------------------------------------------------

@pytest.fixture()
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_history_endpoint_requires_input(client):
    resp = client.get("/api/history")
    assert resp.status_code == 400


def test_history_endpoint_rejects_bad_days(client):
    resp = client.get("/api/history?lat=37&lon=-6&days=abc")
    assert resp.status_code == 400


def test_history_endpoint_ok(client, monkeypatch):
    monkeypatch.setattr(
        history_module, "compute_history",
        lambda lat, lon, name, days=90: {
            "location": {"name": name, "latitude": lat, "longitude": lon},
            "window": {"start": "2026-05-01", "end": "2026-07-30", "days": 90},
            "high_risk_periods": [], "lessons": [], "recent_fire_danger": [],
            "fire_observations": {"available": False},
            "provenance": {"history": {"kind": "modeled"}},
        })
    resp = client.get("/api/history?lat=37.6&lon=-6.5&days=90")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["window"]["days"] == 90


def test_history_endpoint_error_is_502(client, monkeypatch):
    monkeypatch.setattr(
        history_module, "compute_history",
        lambda *a, **k: {"error": "archive unavailable"})
    resp = client.get("/api/history?lat=37.6&lon=-6.5")
    assert resp.status_code == 502


# --------------------------------------------------------------------------
# Snapshot entries carry the explanation factors
# --------------------------------------------------------------------------

def test_snapshot_entry_includes_factors_and_disclaimer():
    from src.dashboard import snapshot as snapshot_module

    analysis = {
        "analysis": {"risk": {"baseline": 66.0, "class": "Extreme"}},
        "fire_danger": {"available": True, "fwi": 41.0, "class": "Extreme",
                        "date": "2026-08-15"},
        "fire_danger_trend": {"trend": "rising"},
        "active_fires": {"available": False},
        "satellite": {"error": "no scene"},
        "risk_explanation": explain_module.build_risk_explanation(
            fwi=41.0, fmc=11.0, slope=8.0, wind_kmh=20.0,
            landcover_label="Tree cover", burnable=True, score=66.0,
            risk_class="Extreme", fmc_source="x"),
        "recommendations": recs_module.build_recommendations(
            _analysis_for_recs(fwi=41.0, fmc=11.0, risk=66.0)),
        "provenance": {"fire_danger": {"kind": "derived", "quality": "ok"}},
    }
    entry = snapshot_module._entry_from_analysis(
        {"name": "X", "lat": 1.0, "lon": 2.0}, analysis)
    assert entry["factors"]
    assert entry["factors"][0]["key"] == "fire_weather"
    assert "not a probability" in entry["score_disclaimer"]
    assert entry["top_recommendation"]["what"]
