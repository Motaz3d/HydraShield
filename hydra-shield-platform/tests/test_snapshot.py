"""Tests for the public risk-snapshot backend (network-free)."""

import json
import os

import pytest

os.environ["HYDRASHIELD_CACHE_DB"] = "/tmp/hydrashield_test_snapshot_cache.sqlite3"
if os.path.exists(os.environ["HYDRASHIELD_CACHE_DB"]):
    os.remove(os.environ["HYDRASHIELD_CACHE_DB"])

from src.dashboard import snapshot as snapshot_module  # noqa: E402
from src.dashboard.api import create_app  # noqa: E402
from src.dashboard.cache import default_cache  # noqa: E402


# --------------------------------------------------------------------------
# Helpers: canned analysis results (mocks of the analysis engine output)
# --------------------------------------------------------------------------

def _prov(kind, source, quality="ok"):
    return {
        "kind": kind, "source": source, "acquired": None, "resolution": None,
        "temporal": None, "retrieved_at": "2026-08-16T00:00:00Z",
        "quality": quality, "limitations": None,
    }


def _analysis(risk, risk_class, fwi=30.0, trend="rising", fires_available=False,
              satellite_ok=True):
    return {
        "location": {"name": "X", "latitude": 1.0, "longitude": 2.0},
        "generated_at": "2026-08-16T00:00:00Z",
        "satellite": ({"observation_date": "2026-08-14T10:20:00", "ndmi": 0.2}
                      if satellite_ok else {"error": "no scene"}),
        "active_fires": ({"available": True, "count": 2, "days": 5, "fires": [1, 2]}
                         if fires_available else
                         {"available": False, "error": "no key", "fires": []}),
        "fire_danger": {"available": True, "fwi": fwi, "class": "High", "date": "2026-08-15"},
        "fire_danger_trend": {"trend": trend, "slope_per_day": 1.2},
        "analysis": {"risk": {"baseline": risk, "class": risk_class}},
        "provenance": {
            "terrain": _prov("observed", "DEM"),
            "weather": _prov("modeled", "Open-Meteo"),
            "fire_danger": _prov("derived", "FWI"),
            "satellite": (_prov("observed", "Sentinel-2") if satellite_ok
                          else _prov("unavailable", "Sentinel-2", quality="missing")),
            "landcover": _prov("observed", "ESA WorldCover"),
            "active_fires": (_prov("observed", "NASA FIRMS") if fires_available
                             else _prov("unavailable", "NASA FIRMS", quality="missing")),
            "risk_score": _prov("derived", "composite"),
        },
    }


def _write_config(tmp_path, areas, top_k=5, scope="Test scope"):
    cfg = {"scope": scope, "top_k": top_k, "areas": areas}
    path = tmp_path / "areas.json"
    path.write_text(json.dumps(cfg))
    return str(path)


# --------------------------------------------------------------------------
# Config loading
# --------------------------------------------------------------------------

def test_default_config_loads():
    cfg = snapshot_module.load_monitored_areas()
    assert len(cfg.areas) >= 3
    assert cfg.scope
    for a in cfg.areas:
        assert -90 <= a["lat"] <= 90 and -180 <= a["lon"] <= 180
        assert a["name"]


def test_config_skips_invalid_areas(tmp_path):
    path = _write_config(tmp_path, [
        {"name": "Good", "lat": 40.0, "lon": -3.0},
        {"name": "Bad lat", "lat": 95.0, "lon": 0.0},
        {"name": "", "lat": 40.0, "lon": 0.0},
        {"name": "Missing coord", "lat": 40.0},
    ])
    cfg = snapshot_module.load_monitored_areas(path)
    assert [a["name"] for a in cfg.areas] == ["Good"]


def test_config_requires_one_valid_area(tmp_path):
    path = _write_config(tmp_path, [{"name": "Bad", "lat": 200.0, "lon": 0.0}])
    with pytest.raises(ValueError):
        snapshot_module.load_monitored_areas(path)


# --------------------------------------------------------------------------
# Entry extraction
# --------------------------------------------------------------------------

def test_entry_from_analysis_full():
    area = {"name": "Testville", "lat": 40.0, "lon": -3.0}
    entry = snapshot_module._entry_from_analysis(
        area, _analysis(71.5, "Extreme", fwi=48.8, fires_available=True)
    )
    assert entry["risk"] == 71.5
    assert entry["risk_class"] == "Extreme"
    assert entry["fwi"] == 48.8
    assert entry["trend"] == "rising"
    assert entry["active_fires"]["count"] == 2
    assert entry["satellite_date"] == "2026-08-14"
    assert entry["provenance"]["fire_danger"]["kind"] == "derived"


def test_entry_dropped_without_real_score():
    area = {"name": "Nowhere", "lat": 1.0, "lon": 1.0}
    assert snapshot_module._entry_from_analysis(area, {"error": "boom"}) is None
    no_risk = _analysis(None, None)
    no_risk["analysis"]["risk"]["baseline"] = None
    assert snapshot_module._entry_from_analysis(area, no_risk) is None


# --------------------------------------------------------------------------
# Snapshot computation (fake analysis function — no network)
# --------------------------------------------------------------------------

def test_compute_snapshot_ranks_and_truncates(tmp_path):
    areas = [{"name": f"A{i}", "lat": 40.0 + i * 0.1, "lon": -3.0} for i in range(6)]
    path = _write_config(tmp_path, areas, top_k=3)
    scores = {"A0": 10.0, "A1": 90.0, "A2": 50.0, "A3": 70.0, "A4": 30.0, "A5": 60.0}

    def fake_analyse(lat, lon, name):
        return _analysis(scores[name], "High")

    snap = snapshot_module.compute_snapshot(path, analyse_fn=fake_analyse)
    assert snap["status"] == "ok"
    assert [e["name"] for e in snap["entries"]] == ["A1", "A3", "A5"]
    assert [e["rank"] for e in snap["entries"]] == [1, 2, 3]
    assert snap["areas_considered"] == 6
    assert snap["areas_with_data"] == 6
    assert snap["scope"] == "Test scope"


def test_compute_snapshot_drops_failed_areas(tmp_path):
    areas = [{"name": "Ok", "lat": 40.0, "lon": -3.0},
             {"name": "Fail", "lat": 41.0, "lon": -3.0},
             {"name": "Boom", "lat": 42.0, "lon": -3.0}]
    path = _write_config(tmp_path, areas)

    def fake_analyse(lat, lon, name):
        if name == "Fail":
            return {"error": "upstream down"}
        if name == "Boom":
            raise RuntimeError("crash")
        return _analysis(55.0, "High")

    snap = snapshot_module.compute_snapshot(path, analyse_fn=fake_analyse)
    assert snap["status"] == "ok"
    assert [e["name"] for e in snap["entries"]] == ["Ok"]
    assert snap["areas_with_data"] == 1


def test_compute_snapshot_unavailable_when_nothing_computable(tmp_path):
    path = _write_config(tmp_path, [{"name": "Fail", "lat": 40.0, "lon": -3.0}])
    snap = snapshot_module.compute_snapshot(path, analyse_fn=lambda *a: {"error": "x"})
    assert snap["status"] == "unavailable"
    assert snap["entries"] == []
    assert "message" in snap


def test_compute_snapshot_config_problem_is_unavailable(tmp_path):
    bad = tmp_path / "missing.json"
    snap = snapshot_module.compute_snapshot(str(bad))
    assert snap["status"] == "unavailable"


def test_snapshot_sources_reflect_contributing_components(tmp_path):
    areas = [{"name": "A", "lat": 40.0, "lon": -3.0}]
    path = _write_config(tmp_path, areas)
    snap = snapshot_module.compute_snapshot(
        path, analyse_fn=lambda *a: _analysis(50.0, "Moderate", satellite_ok=False)
    )
    keys = [s["key"] for s in snap["sources"]]
    assert "fire_danger" in keys and "terrain" in keys
    assert "satellite" not in keys      # unavailable -> did not contribute
    assert "active_fires" not in keys   # FIRMS unavailable -> not listed
    for s in snap["sources"]:
        assert s["name"] and s["url"].startswith("https://")


def test_snapshot_never_touches_geocoder(tmp_path, monkeypatch):
    """Snapshot areas come with coordinates; Nominatim must not be called."""
    from src.dashboard import real_data

    def boom(query):
        raise AssertionError("geocoder must not be used by the snapshot")

    monkeypatch.setattr(real_data, "geocode_location", boom)
    monkeypatch.setattr(
        snapshot_module.TalaixRealAnalyser, "analyse_point",
        lambda self, lat, lon, name=None: _analysis(42.0, "Moderate"),
    )
    path = _write_config(tmp_path, [{"name": "Unique Place ZZ", "lat": 12.3456, "lon": 45.6789}])
    snap = snapshot_module.compute_snapshot(path)  # default analyse_fn -> cached_analysis
    assert snap["status"] == "ok"
    assert snap["entries"][0]["risk"] == 42.0


# --------------------------------------------------------------------------
# Caching behaviour
# --------------------------------------------------------------------------

def test_get_snapshot_caches_result(monkeypatch):
    cache = default_cache()
    cache.delete(snapshot_module._CACHE_KEY)
    calls = []

    def fake_compute(config_path=None, analyse_fn=None):
        calls.append(1)
        return {"status": "ok", "entries": [], "generated_at": "t", "scope": "s",
                "sources": [], "valid_for_seconds": 1800}

    monkeypatch.setattr(snapshot_module, "compute_snapshot", fake_compute)
    first = snapshot_module.get_snapshot(build=True)
    second = snapshot_module.get_snapshot()
    assert first == second
    assert len(calls) == 1


def test_get_snapshot_caches_unavailable_briefly(monkeypatch):
    cache = default_cache()
    cache.delete(snapshot_module._CACHE_KEY)
    calls = []

    def fake_compute(config_path=None, analyse_fn=None):
        calls.append(1)
        return {"status": "unavailable", "message": "m", "entries": []}

    monkeypatch.setattr(snapshot_module, "compute_snapshot", fake_compute)
    snap = snapshot_module.get_snapshot(build=True)
    assert snap["status"] == "unavailable"
    snapshot_module.get_snapshot()
    assert len(calls) == 1  # pinned for the short failure TTL, not recomputed


def test_request_path_never_builds_inline(monkeypatch):
    """The homepage/API path must never trigger the heavy rebuild — an
    honest warming state is returned instead (production OOM lesson)."""
    cache = default_cache()
    cache.delete(snapshot_module._CACHE_KEY)
    calls = []

    def fake_compute(config_path=None, analyse_fn=None):
        calls.append(1)
        return {"status": "ok", "entries": []}

    monkeypatch.setattr(snapshot_module, "compute_snapshot", fake_compute)
    snap = snapshot_module.get_snapshot()
    assert snap["status"] == "unavailable"
    assert "warming" in snap["message"]
    assert calls == []


# --------------------------------------------------------------------------
# HTTP endpoint
# --------------------------------------------------------------------------

@pytest.fixture()
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_risk_snapshot_endpoint_ok(client, monkeypatch):
    canned = {
        "status": "ok", "scope": "Test scope", "generated_at": "2026-08-16T00:00:00Z",
        "valid_for_seconds": 1800, "areas_considered": 2, "areas_with_data": 2,
        "entries": [
            {"rank": 1, "name": "A", "latitude": 1.0, "longitude": 2.0,
             "risk": 71.5, "risk_class": "Extreme", "fwi": 48.8, "fwi_class": "Very high",
             "fwi_date": "2026-08-15", "trend": "rising", "active_fires": None,
             "satellite_date": "2026-08-14", "provenance": {"fire_danger": _prov("derived", "FWI")}},
        ],
        "sources": [{"key": "fire_danger", "name": "Canadian FWI System",
                     "url": "https://cwfis.cfs.nrcan.gc.ca/background/summary/fwi"}],
        "model": {"risk_score": "x", "note": "y"}, "data_policy": "real data only",
    }
    monkeypatch.setattr(snapshot_module, "get_snapshot", lambda **kw: canned)
    resp = client.get("/api/risk-snapshot")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "ok"
    assert body["entries"][0]["risk"] == 71.5
    assert body["entries"][0]["provenance"]["fire_danger"]["kind"] == "derived"
    assert body["sources"][0]["url"].startswith("https://")


def test_risk_snapshot_endpoint_unavailable_is_503(client, monkeypatch):
    monkeypatch.setattr(
        snapshot_module, "get_snapshot",
        lambda **kw: {"status": "unavailable", "message": "no real data", "entries": []},
    )
    resp = client.get("/api/risk-snapshot")
    assert resp.status_code == 503
    body = resp.get_json()
    assert body["status"] == "unavailable"
    assert body["entries"] == []


def test_risk_snapshot_endpoint_error_is_honest(client, monkeypatch):
    def boom(**kw):
        raise RuntimeError("cache db gone")

    monkeypatch.setattr(snapshot_module, "get_snapshot", boom)
    resp = client.get("/api/risk-snapshot")
    assert resp.status_code == 503
    assert "error" in resp.get_json()
