"""Tests for the smoke-intelligence layer and the learning store.

All network-free: wind profiles, fire evidence, corridor overlays and the
Overpass call are monkeypatched. Wind-profile step times are generated
relative to ``datetime.utcnow()`` so the "from now" slicing always applies.
"""

import inspect
import os
from datetime import datetime, timedelta

import pytest

os.environ["HYDRASHIELD_CACHE_DB"] = "/tmp/hydrashield_test_smoke_cache.sqlite3"
if os.path.exists(os.environ["HYDRASHIELD_CACHE_DB"]):
    os.remove(os.environ["HYDRASHIELD_CACHE_DB"])

from src.dashboard import smoke as smoke_module  # noqa: E402
from src.dashboard import population as population_module  # noqa: E402
from src.dashboard import ignition as ignition_module  # noqa: E402
from src.dashboard.learning import LearningStore  # noqa: E402
from src.dashboard.api import create_app  # noqa: E402


# --------------------------------------------------------------------------
# Helpers: synthetic (caller-side) wind profiles anchored "from now" (UTC)
# --------------------------------------------------------------------------

def _steps(n, speed=20.0, dir_deg=270.0):
    now = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
    return [{"time": (now + timedelta(hours=i)).isoformat(),
             "transport_speed_kmh": speed, "transport_dir_deg": dir_deg}
            for i in range(n)]


def _wind_profile(hours, speed=20.0, dir_deg=270.0):
    now = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
    steps = []
    for i in range(hours + 2):  # margin so the from-now slice always has >= hours
        t = (now + timedelta(hours=i)).isoformat()
        steps.append({"time": t,
                      "wind_10m_kmh": speed, "wind_10m_dir_deg": dir_deg,
                      "wind_850hPa_kmh": speed, "wind_850hPa_dir_deg": dir_deg,
                      "transport_speed_kmh": speed, "transport_dir_deg": dir_deg,
                      "transport_level": "850 hPa"})
    return {"steps": steps, "hours": len(steps), "transport_level": "850 hPa",
            "level_note": ("Transport uses the 850 hPa wind (~1.5 km), "
                           "a standard smoke-transport level."),
            "units": {}, "source": "Weather model hourly profile (Open-Meteo)"}


def _patch_wind(monkeypatch, speed=20.0, dir_deg=270.0):
    monkeypatch.setattr("src.dashboard.real_data.fetch_wind_profile",
                        lambda lat, lon, hours=24: _wind_profile(hours, speed, dir_deg))


def _patch_overlays(monkeypatch):
    monkeypatch.setattr(smoke_module, "_corridor_overlays", lambda polygon: {
        "population": {"available": True, "estimated_population_in_corridor": 321,
                       "estimate_note": ("Estimated population within the modelled area "
                                         "based on WorldPop, reference year 2025 "
                                         "(gridded estimates, not an exact count)."),
                       "source": "WorldPop Global 2 (R2025A) constrained 100 m, reference year 2025"},
        "facilities": {"available": False, "reason": "no OSM"},
    })


# --------------------------------------------------------------------------
# compute_transport (pure)
# --------------------------------------------------------------------------

def test_transport_wind_from_west_blows_to_east():
    out = smoke_module.compute_transport(_steps(6, 20.0, 270.0), 37.6, -6.5)
    # Wind FROM 270° moves air TO 90° (East).
    assert out["dominant_transport_direction"] == "E"
    assert out["dominant_transport_heading_deg"] == 90.0
    last = out["trajectory"][-1]
    assert last["lon"] > -6.5
    assert abs(last["lat"] - 37.6) < 0.05  # straight eastward drift


def test_transport_distances_and_trajectory_length():
    out = smoke_module.compute_transport(_steps(6, 20.0, 270.0), 37.6, -6.5)
    assert out["hours"] == 6
    assert len(out["trajectory"]) == 7  # origin + one point per hour
    assert out["trajectory"][0]["distance_from_origin_km"] == 0.0
    assert out["path_length_km"] == 120.0  # 20 km/h * 6 h
    assert out["displacement_km"] == pytest.approx(120.0, rel=0.02)
    assert out["mean_transport_speed_kmh"] == 20.0


def test_transport_corridor_is_closed_ring():
    out = smoke_module.compute_transport(_steps(6, 20.0, 270.0), 37.6, -6.5)
    poly = out["corridor_polygon"]
    assert len(poly) > 4
    assert poly[0] == poly[-1]  # closed ring
    assert out["corridor_model"]["initial_half_width_km"] == smoke_module.CORRIDOR_W0_KM
    assert out["corridor_model"]["growth_km_per_hour"] == smoke_module.CORRIDOR_GROWTH_KM_H
    assert "not a deterministic path" in out["corridor_model"]["type"]


def test_transport_is_deterministic():
    steps = _steps(8, 17.5, 243.0)
    first = smoke_module.compute_transport(steps, 37.6, -6.5)
    second = smoke_module.compute_transport(steps, 37.6, -6.5)
    assert first == second  # identical inputs -> identical output, no randomness


def test_transport_empty_steps_error():
    assert "error" in smoke_module.compute_transport([], 37.6, -6.5)


def test_transport_calm_winds_low_confidence():
    out = smoke_module.compute_transport(_steps(6, 2.0, 270.0), 37.6, -6.5)
    assert out["confidence"] == "low"
    assert "light" in out["confidence_note"]


def test_transport_variable_directions_low_confidence():
    dirs = [0.0, 180.0, 0.0, 180.0, 0.0, 180.0]
    steps = _steps(6, 20.0, 270.0)
    for s, d in zip(steps, dirs):
        s["transport_dir_deg"] = d
    out = smoke_module.compute_transport(steps, 37.6, -6.5)
    assert out["direction_variability"] > smoke_module._VARIABILITY_LOW_CONF
    assert out["confidence"] == "low"
    assert "varies strongly" in out["confidence_note"]


def test_transport_moderate_variability_moderate_confidence():
    dirs = [270.0, 0.0, 270.0, 0.0, 270.0, 0.0]
    steps = _steps(6, 20.0, 270.0)
    for s, d in zip(steps, dirs):
        s["transport_dir_deg"] = d
    out = smoke_module.compute_transport(steps, 37.6, -6.5)
    assert smoke_module._VARIABILITY_MODERATE < out["direction_variability"] \
        <= smoke_module._VARIABILITY_LOW_CONF
    assert out["confidence"] == "moderate"
    assert "Some directional variability" in out["confidence_note"]


def test_transport_steady_winds_moderate_confidence_is_the_maximum():
    out = smoke_module.compute_transport(_steps(6, 20.0, 270.0), 37.6, -6.5)
    assert out["direction_variability"] == 0.0
    assert out["confidence"] == "moderate"
    assert "highest confidence" in out["confidence_note"]


def test_transport_confidence_is_never_high():
    for speed, dir_deg in ((2.0, 270.0), (20.0, 270.0), (45.0, 90.0), (12.0, 0.0)):
        out = smoke_module.compute_transport(_steps(6, speed, dir_deg), 37.6, -6.5)
        assert out["confidence"] in ("low", "moderate")


# --------------------------------------------------------------------------
# smoke_scenario (SCENARIO / MODELLED — never an observation)
# --------------------------------------------------------------------------

def test_smoke_scenario_ok(monkeypatch):
    _patch_wind(monkeypatch, speed=20.0, dir_deg=270.0)
    _patch_overlays(monkeypatch)
    out = smoke_module.smoke_scenario.__wrapped__(37.6, -6.5, hours=12)
    assert out["status"] == "ok"
    assert out["mode"] == "scenario"
    assert out["mode_label"].startswith("SCENARIO / MODELLED")
    assert out["scenario"].startswith("If a fire were to occur")
    # timestamps: ISO generated_at + declared UTC window
    assert out["generated_at"].endswith("Z")
    datetime.fromisoformat(out["generated_at"].replace("Z", "+00:00"))
    assert out["window"]["hours"] == 12
    assert out["window"]["timezone"] == "UTC"
    assert out["window"]["from"] and out["window"]["to"]
    assert out["transport"]["hours"] == 12
    # provenance + honesty constants
    assert out["provenance"]["kind"] == "modeled"
    assert out["provenance"]["source"]
    assert out["provenance"]["resolution"]
    assert out["disclaimer"] == smoke_module.TRANSPORT_DISCLAIMER
    assert out["safety"]["not_medical_advice"] is True
    assert out["overlays"]["population"]["estimated_population_in_corridor"] == 321


def test_smoke_scenario_wind_profile_error(monkeypatch):
    monkeypatch.setattr("src.dashboard.real_data.fetch_wind_profile",
                        lambda lat, lon, hours=24: {"error": "Wind profile service unavailable: boom"})
    out = smoke_module.smoke_scenario.__wrapped__(37.6, -6.5, hours=12)
    assert out["mode"] == "scenario"
    assert "Wind profile service unavailable" in out["error"]


def test_smoke_scenario_insufficient_steps(monkeypatch):
    # All steps in the past -> the from-now slice finds nothing usable.
    monkeypatch.setattr("src.dashboard.real_data.fetch_wind_profile",
                        lambda lat, lon, hours=24: {
                            "steps": [{"time": "2020-01-01T00:00:00",
                                       "transport_speed_kmh": 20.0,
                                       "transport_dir_deg": 270.0}],
                            "transport_level": "850 hPa",
                            "source": "Weather model hourly profile (Open-Meteo)"})
    out = smoke_module.smoke_scenario.__wrapped__(37.6, -6.5, hours=12)
    assert out["mode"] == "scenario"
    assert "Insufficient forecast wind steps" in out["error"]


def test_smoke_scenario_rejects_out_of_range():
    out = smoke_module.smoke_scenario.__wrapped__(95.0, 0.0, hours=12)
    assert out["error"] == "Coordinates out of range"


# --------------------------------------------------------------------------
# smoke_observed (OBSERVED FIRE + modelled transport)
# --------------------------------------------------------------------------

def _evidence_unavailable():
    return {"status": "unavailable",
            "provenance": {"kind": "unavailable",
                           "limitations": "NASA FIRMS API key not configured"}}


def _evidence_with_detection():
    return {
        "status": "ok",
        "entries": [{
            "status": "ok",
            "source_label": "NASA FIRMS VIIRS S-NPP (375 m)",
            "detections": [{
                "lat": 37.65, "lon": -6.55, "sensor": "VIIRS S-NPP",
                "acq_date": datetime.utcnow().date().isoformat(),
                "acq_time_utc": "0000", "frp_mw": 12.0, "confidence": "high",
            }],
        }],
        "provenance": {"kind": "observed"},
    }


def test_smoke_observed_unavailable_without_firms_key(monkeypatch):
    monkeypatch.setattr("src.dashboard.fire_evidence.build_fire_evidence",
                        lambda lat, lon, radius_km=50.0, days=3: _evidence_unavailable())
    out = smoke_module.smoke_observed.__wrapped__(37.6, -6.5)
    assert out["status"] == "unavailable"
    assert out["mode"] == "observed"
    assert "FIRMS" in out["reason"]
    assert "firms.modaps.eosdis.nasa.gov" in out["signup"]
    assert "scenario" in out["note"].lower()
    assert out["provenance"]["kind"] == "unavailable"


def test_smoke_observed_no_detections(monkeypatch):
    monkeypatch.setattr("src.dashboard.fire_evidence.build_fire_evidence",
                        lambda lat, lon, radius_km=50.0, days=3: {
                            "status": "ok", "entries": [], "provenance": {"kind": "observed"}})
    out = smoke_module.smoke_observed.__wrapped__(37.6, -6.5)
    assert out["status"] == "ok"
    assert out["count"] == 0
    assert out["fires"] == []
    assert "No active-fire detections" in out["note"]


def test_smoke_observed_with_detection(monkeypatch):
    monkeypatch.setattr("src.dashboard.fire_evidence.build_fire_evidence",
                        lambda lat, lon, radius_km=50.0, days=3: _evidence_with_detection())
    _patch_wind(monkeypatch)
    _patch_overlays(monkeypatch)
    out = smoke_module.smoke_observed.__wrapped__(37.6, -6.5, hours=12)
    assert out["status"] == "ok"
    assert out["mode"] == "observed"
    assert out["mode_label"] == ("OBSERVED FIRE (satellite detection) + "
                                 "MODELLED ATMOSPHERIC TRANSPORT")
    assert out["count"] == 1
    fire = out["fires"][0]
    assert fire["detection"]["sensor"] == "VIIRS S-NPP"
    today = datetime.utcnow().date().isoformat()
    expected_age = (datetime.utcnow()
                    - datetime.fromisoformat(f"{today}T00:00:00")).total_seconds() / 3600.0
    assert fire["detection"]["age_hours"] == pytest.approx(expected_age, abs=0.2)
    assert fire["detection"]["age_hours"] >= 0
    assert "not a fire perimeter" in fire["detection"]["note"]
    assert fire["transport"]["available"] is True
    assert "observed fire location" in fire["transport"]["anchored_at"]
    assert fire["transport"]["hours"] == 12
    assert fire["overlays"]["population"]["estimated_population_in_corridor"] == 321
    assert out["provenance"]["kind"] == "observed+modeled"
    assert out["generated_at"].endswith("Z")
    assert "does not reconstruct" in out["model_time_note"]


def test_smoke_observed_detection_wind_failure_is_honest(monkeypatch):
    monkeypatch.setattr("src.dashboard.fire_evidence.build_fire_evidence",
                        lambda lat, lon, radius_km=50.0, days=3: _evidence_with_detection())
    monkeypatch.setattr("src.dashboard.real_data.fetch_wind_profile",
                        lambda lat, lon, hours=24: {"error": "wind down"})
    out = smoke_module.smoke_observed.__wrapped__(37.6, -6.5)
    fire = out["fires"][0]
    assert fire["transport"] == {"available": False, "reason": "wind down"}
    assert "overlays" not in fire


def test_detection_age_hours_parsing():
    assert smoke_module._detection_age_hours(None, "1200") is None
    assert smoke_module._detection_age_hours("not-a-date", "1200") is None
    today = datetime.utcnow().date().isoformat()
    age = smoke_module._detection_age_hours(today, "0000")
    expected = (datetime.utcnow()
                - datetime.fromisoformat(f"{today}T00:00:00")).total_seconds() / 3600.0
    assert age == pytest.approx(expected, abs=0.2)
    # FIRMS times are HHMM without a colon and may be short-padded.
    age930 = smoke_module._detection_age_hours(today, "930")
    assert age930 == pytest.approx(age - 9.5, abs=0.2)


# --------------------------------------------------------------------------
# Corridor population overlay (WorldPop inside the corridor polygon)
# --------------------------------------------------------------------------

_POLY = [[37.5, -6.6], [37.5, -6.4], [37.7, -6.4], [37.7, -6.6], [37.5, -6.6]]


def test_corridor_population_ok(monkeypatch):
    monkeypatch.setattr(population_module, "country_code_for",
                        lambda lat, lon: {"country_code": "es", "country": "Spain"})
    monkeypatch.setattr(population_module, "population_in_polygon",
                        lambda iso3, poly: {
                            "estimated_population": 1234,
                            "estimate_note": ("Estimated population within the modelled area "
                                              "based on WorldPop, reference year 2025 "
                                              "(gridded estimates, not an exact count)."),
                            "source": "WorldPop Global 2 (R2025A) constrained 100 m, reference year 2025"})
    out = smoke_module._corridor_population(_POLY)
    assert out["available"] is True
    assert out["estimated_population_in_corridor"] == 1234
    assert "reference year" in out["estimate_note"]
    assert "WorldPop" in out["source"]


def test_corridor_population_failures_are_honest(monkeypatch):
    assert smoke_module._corridor_population([])["available"] is False

    monkeypatch.setattr(population_module, "country_code_for",
                        lambda lat, lon: {"error": "No country at this location"})
    out = smoke_module._corridor_population(_POLY)
    assert out["available"] is False
    assert "No country" in out["reason"]

    monkeypatch.setattr(population_module, "country_code_for",
                        lambda lat, lon: {"country_code": "xx"})
    out = smoke_module._corridor_population(_POLY)
    assert out["available"] is False
    assert "No WorldPop mapping" in out["reason"]

    monkeypatch.setattr(population_module, "country_code_for",
                        lambda lat, lon: {"country_code": "es"})
    monkeypatch.setattr(population_module, "population_in_polygon",
                        lambda iso3, poly: {"error": "raster missing"})
    out = smoke_module._corridor_population(_POLY)
    assert out["available"] is False
    assert "raster missing" in out["reason"]


# --------------------------------------------------------------------------
# facilities_in_polygon (Overpass monkeypatched)
# --------------------------------------------------------------------------

def test_facilities_in_polygon_parsing(monkeypatch):
    payload = {"elements": [
        {"type": "node", "lat": 37.6, "lon": -6.5,
         "tags": {"amenity": "hospital", "name": "Hospital Real"}},
        {"type": "way", "center": {"lat": 37.61, "lon": -6.49},
         "tags": {"amenity": "school"}},
        {"type": "node", "lat": 37.62, "lon": -6.48,
         "tags": {"amenity": "cafe"}},  # not a critical facility -> skipped
        {"type": "node", "tags": {"amenity": "school"}},  # no coords -> skipped
    ]}
    monkeypatch.setattr(smoke_module, "_post_overpass", lambda q: payload)
    out = smoke_module.facilities_in_polygon.__wrapped__(_POLY)
    assert out["counts"] == {"hospitals": 1, "schools": 1}
    assert len(out["facilities"]) == 2
    assert out["facilities"][0]["name"] == "Hospital Real"
    assert "OpenStreetMap" in out["source"]


def test_facilities_in_polygon_failures(monkeypatch):
    out = smoke_module.facilities_in_polygon.__wrapped__([[1.0, 2.0], [3.0, 4.0]])
    assert out["error"] == "Polygon too small"

    def boom(query):
        raise OSError("overpass timeout")
    monkeypatch.setattr(smoke_module, "_post_overpass", boom)
    out = smoke_module.facilities_in_polygon.__wrapped__(_POLY)
    assert "unavailable" in out["error"]
    assert "overpass timeout" in out["error"]


# --------------------------------------------------------------------------
# Declared safety / disclaimer constants
# --------------------------------------------------------------------------

def test_safety_guidance_and_disclaimer():
    guidance = smoke_module.SAFETY_GUIDANCE
    assert guidance["not_medical_advice"] is True
    assert "public-health" in guidance["kind"]
    assert any("official" in p for p in guidance["points"])
    assert "not an observation" in guidance["distinction_note"] or \
        "neither an observation" in guidance["distinction_note"]
    assert "not certainty" in smoke_module.TRANSPORT_DISCLAIMER
    assert "not a predicted smoke path" in smoke_module.TRANSPORT_DISCLAIMER


# --------------------------------------------------------------------------
# No fabricated data / no randomness in the new modules
# --------------------------------------------------------------------------

def test_new_modules_use_no_randomness():
    import src.dashboard.learning as learning_module
    for mod in (smoke_module, population_module, ignition_module, learning_module):
        src = inspect.getsource(mod)
        assert "import random" not in src
        assert "random." not in src
        assert "np.random" not in src


# --------------------------------------------------------------------------
# Learning store (prediction-vs-observation records)
# --------------------------------------------------------------------------

def test_learning_store_roundtrip(tmp_path):
    store = LearningStore(str(tmp_path / "learn.sqlite3"))
    rec_id = store.record(
        kind="smoke", model_version="rili-1.0.0", location="Testville",
        prediction_time="2026-08-16T00:00:00Z", observation_time="2026-08-16T12:00:00Z",
        predicted={"corridor_direction": "E"}, observed={"smoke_observed_east": True},
        error=None, lesson="corridor matched the observed drift",
        confidence="moderate", sources=["NASA FIRMS", "Open-Meteo"])
    assert rec_id
    rows = store.list()
    assert len(rows) == 1
    rec = rows[0]
    assert rec["id"] == rec_id
    assert rec["kind"] == "smoke"
    assert rec["predicted"]["corridor_direction"] == "E"
    assert rec["observed"]["smoke_observed_east"] is True
    assert rec["sources"] == ["NASA FIRMS", "Open-Meteo"]
    assert rec["created_at"].endswith("Z")
    # kind filter
    assert len(store.list(kind="smoke")) == 1
    assert store.list(kind="ignition") == []


def test_learning_store_requires_real_observation(tmp_path):
    store = LearningStore(str(tmp_path / "l.sqlite3"))
    with pytest.raises(ValueError):
        store.record(kind="smoke", model_version="rili-1.0.0", location="X",
                     prediction_time=None, observation_time=None,
                     predicted={"a": 1}, observed={})
    with pytest.raises(ValueError):
        store.record(kind="nonsense", model_version="rili-1.0.0", location="X",
                     prediction_time=None, observation_time=None,
                     predicted={"a": 1}, observed={"b": 2})


# --------------------------------------------------------------------------
# /api/smoke and /api/smoke-scenario
# --------------------------------------------------------------------------

@pytest.fixture()
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_smoke_endpoint_requires_input(client):
    assert client.get("/api/smoke").status_code == 400


def test_smoke_endpoint_rejects_bad_params(client):
    resp = client.get("/api/smoke?lat=37.6&lon=-6.5&radius_km=abc")
    assert resp.status_code == 400
    resp = client.get("/api/smoke?lat=37.6&lon=-6.5&days=abc")
    assert resp.status_code == 400


def test_smoke_endpoint_503_when_unavailable(client, monkeypatch):
    monkeypatch.setattr("src.dashboard.smoke.smoke_observed",
                        lambda lat, lon, radius_km=50.0, days=3, hours=24: {
                            "status": "unavailable", "mode": "observed",
                            "reason": "NASA FIRMS API key not configured",
                            "signup": "https://firms.modaps.eosdis.nasa.gov/api/area/"})
    resp = client.get("/api/smoke?lat=37.6&lon=-6.5")
    assert resp.status_code == 503
    body = resp.get_json()
    assert body["status"] == "unavailable"
    assert "FIRMS" in body["reason"]


def test_smoke_endpoint_502_on_error(client, monkeypatch):
    monkeypatch.setattr("src.dashboard.smoke.smoke_observed",
                        lambda lat, lon, radius_km=50.0, days=3, hours=24:
                            {"error": "Coordinates out of range"})
    resp = client.get("/api/smoke?lat=37.6&lon=-6.5")
    assert resp.status_code == 502


def test_smoke_endpoint_ok(client, monkeypatch):
    monkeypatch.setattr("src.dashboard.smoke.smoke_observed",
                        lambda lat, lon, radius_km=50.0, days=3, hours=24: {
                            "status": "ok", "mode": "observed",
                            "mode_label": ("OBSERVED FIRE (satellite detection) + "
                                           "MODELLED ATMOSPHERIC TRANSPORT"),
                            "fires": [], "count": 0})
    resp = client.get("/api/smoke?lat=37.6&lon=-6.5")
    assert resp.status_code == 200
    assert resp.get_json()["mode"] == "observed"


def test_smoke_scenario_endpoint_requires_input(client):
    assert client.get("/api/smoke-scenario").status_code == 400


def test_smoke_scenario_endpoint_rejects_bad_params(client):
    resp = client.get("/api/smoke-scenario?lat=37.6&lon=-6.5&hours=abc")
    assert resp.status_code == 400


def test_smoke_scenario_endpoint_502_on_error(client, monkeypatch):
    monkeypatch.setattr("src.dashboard.smoke.smoke_scenario",
                        lambda lat, lon, hours=24: {"error": "Wind profile service unavailable: boom",
                                                    "mode": "scenario"})
    resp = client.get("/api/smoke-scenario?lat=37.6&lon=-6.5")
    assert resp.status_code == 502
    assert "Wind profile service unavailable" in resp.get_json()["error"]


def test_smoke_scenario_endpoint_ok(client, monkeypatch):
    monkeypatch.setattr("src.dashboard.smoke.smoke_scenario",
                        lambda lat, lon, hours=24: {
                            "status": "ok", "mode": "scenario",
                            "mode_label": ("SCENARIO / MODELLED — no fire is observed "
                                           "at this location"),
                            "scenario": ("If a fire were to occur near this location "
                                         "under current atmospheric conditions, this is "
                                         "where the smoke could move."),
                            "provenance": {"kind": "modeled"}})
    resp = client.get("/api/smoke-scenario?lat=37.6&lon=-6.5&hours=12")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["mode"] == "scenario"
    assert body["mode_label"].startswith("SCENARIO / MODELLED")
    assert body["scenario"].startswith("If a fire were to occur")
