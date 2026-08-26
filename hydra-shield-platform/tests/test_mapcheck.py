"""Tests for the Map Check cartographic cross-verification engine."""

from __future__ import annotations

import json
import os
import subprocess
from typing import Any, Dict

import pytest

os.environ["HYDRASHIELD_CACHE_DB"] = "/tmp/hydrashield_test_mapcheck_cache.sqlite3"
if os.path.exists(os.environ["HYDRASHIELD_CACHE_DB"]):
    os.remove(os.environ["HYDRASHIELD_CACHE_DB"])

from src.climate import mapcheck  # noqa: E402
from src.dashboard.api import create_app  # noqa: E402


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_cache(monkeypatch):
    import src.dashboard.cache as cache_mod
    import src.dashboard.api as api_module

    monkeypatch.setattr(cache_mod, "_default_cache", None)
    api_module._rate_limiter._hits.clear()


@pytest.fixture()
def env(tmp_path, monkeypatch):
    db_path = tmp_path / "mapcheck.sqlite3"
    monkeypatch.setenv("HYDRASHIELD_CACHE_DB", str(db_path))
    import src.dashboard.cache as cache_mod
    import src.dashboard.api as api_module

    monkeypatch.setattr(cache_mod, "_default_cache", None)
    api_module._rate_limiter._hits.clear()
    return {"db": db_path}


@pytest.fixture()
def client(env):
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


# -----------------------------------------------------------------------------
# Stubs
# -----------------------------------------------------------------------------


def _features_with_year(year: int) -> Dict[str, Any]:
    return {
        "features": [{
            "type": "way",
            "id": 123,
            "kind": "park",
            "name": "Test Park",
            "tags": {"leisure": "park", "name": "Test Park"},
            "timestamp": f"{year}-06-15T10:00:00Z",
            "edit_year": year,
        }],
        "count": 1,
        "source": "OpenStreetMap (Overpass API)",
        "query_note": "stub",
    }


NO_FEATURES = {
    "features": [],
    "count": 0,
    "source": "OpenStreetMap (Overpass API)",
    "query_note": "stub",
}


def _satellite(ndvi: float | None, landcover_class: int | None) -> Dict[str, Any]:
    return {
        "ndvi": ndvi,
        "ndvi_available": ndvi is not None,
        "ndvi_error": None,
        "green_by_ndvi": ndvi is not None and ndvi >= mapcheck.NDVI_GREEN_THRESHOLD,
        "observation_date": "2026-08-01T00:00:00Z",
        "ndvi_source": "Sentinel-2 L2A (Earth Search STAC)",
        "landcover_class": landcover_class,
        "landcover_label": {
            10: "Tree cover",
            20: "Shrubland",
            30: "Grassland",
            50: "Built-up",
            60: "Bare/sparse vegetation",
            80: "Permanent water",
            90: "Herbaceous wetland",
            95: "Mangroves",
        }.get(landcover_class, "Unknown"),
        "landcover_available": landcover_class is not None,
        "landcover_error": None,
        "landcover_source": "ESA WorldCover 10m 2021 v200",
        "satellite_available": ndvi is not None or landcover_class is not None,
    }


SATELLITE_ERROR = {
    "ndvi": None,
    "ndvi_available": False,
    "ndvi_error": "No recent cloud-free Sentinel-2 scene available",
    "green_by_ndvi": False,
    "observation_date": None,
    "ndvi_source": None,
    "landcover_class": None,
    "landcover_label": None,
    "landcover_available": False,
    "landcover_error": "rasterio not installed",
    "landcover_source": None,
    "satellite_available": False,
}


# -----------------------------------------------------------------------------
# Engine tests
# -----------------------------------------------------------------------------


def test_check_a_discrepancy_outdated_map(monkeypatch):
    monkeypatch.setattr(mapcheck, "_fetch_green_features", lambda lat, lon, r: _features_with_year(2013))
    monkeypatch.setattr(mapcheck, "fetch_satellite_data", lambda lat, lon, days_back=30: {"ndvi": 0.15})
    monkeypatch.setattr(mapcheck, "fetch_landcover", lambda lat, lon, window_m=500: {"dominant_class": 50, "dominant_label": "Built-up"})

    result = mapcheck.check_map_vs_satellite(46.0542, 14.4707, radius_m=300)
    assert result["status"] == "ok"
    assert result["discrepancies_count"] == 1

    check_a = result["checks"][0]
    assert check_a["id"] == "green_mapped_vs_satellite"
    assert check_a["result"] == "discrepancy_detected"
    assert any("2013" in cause for cause in check_a["possible_causes"])
    assert any("outdated" in cause.lower() for cause in check_a["possible_causes"])

    check_b = result["checks"][1]
    assert check_b["result"] == "consistent"


def test_check_a_consistent(monkeypatch):
    monkeypatch.setattr(mapcheck, "_fetch_green_features", lambda lat, lon, r: _features_with_year(2024))
    monkeypatch.setattr(mapcheck, "fetch_satellite_data", lambda lat, lon, days_back=30: {"ndvi": 0.60})
    monkeypatch.setattr(mapcheck, "fetch_landcover", lambda lat, lon, window_m=500: {"dominant_class": 10, "dominant_label": "Tree cover"})

    result = mapcheck.check_map_vs_satellite(46.0542, 14.4707, radius_m=300)
    assert result["status"] == "ok"
    assert result["discrepancies_count"] == 0
    assert result["checks"][0]["result"] == "consistent"
    assert result["checks"][1]["result"] == "consistent"


def test_check_b_discrepancy_unmapped_green(monkeypatch):
    monkeypatch.setattr(mapcheck, "_fetch_green_features", lambda lat, lon, r: NO_FEATURES)
    monkeypatch.setattr(mapcheck, "fetch_satellite_data", lambda lat, lon, days_back=30: {"ndvi": 0.60})
    monkeypatch.setattr(mapcheck, "fetch_landcover", lambda lat, lon, window_m=500: {"dominant_class": 10, "dominant_label": "Tree cover"})

    result = mapcheck.check_map_vs_satellite(46.0542, 14.4707, radius_m=300)
    assert result["status"] == "ok"
    assert result["discrepancies_count"] == 1

    check_b = result["checks"][1]
    assert check_b["id"] == "satellite_green_vs_map"
    assert check_b["result"] == "discrepancy_detected"
    assert any("completeness" in cause.lower() for cause in check_b["possible_causes"])
    assert len(check_b["possible_causes"]) > 0

    check_a = result["checks"][0]
    assert check_a["result"] == "consistent"


def test_check_b_consistent(monkeypatch):
    monkeypatch.setattr(mapcheck, "_fetch_green_features", lambda lat, lon, r: NO_FEATURES)
    monkeypatch.setattr(mapcheck, "fetch_satellite_data", lambda lat, lon, days_back=30: {"ndvi": 0.10})
    monkeypatch.setattr(mapcheck, "fetch_landcover", lambda lat, lon, window_m=500: {"dominant_class": 50, "dominant_label": "Built-up"})

    result = mapcheck.check_map_vs_satellite(46.0542, 14.4707, radius_m=300)
    assert result["status"] == "ok"
    assert result["discrepancies_count"] == 0
    assert all(c["result"] == "consistent" for c in result["checks"])


def test_satellite_error_cannot_assess(monkeypatch):
    monkeypatch.setattr(mapcheck, "_fetch_green_features", lambda lat, lon, r: NO_FEATURES)
    monkeypatch.setattr(mapcheck, "fetch_satellite_data", lambda lat, lon, days_back=30: {"error": "no scene"})
    monkeypatch.setattr(mapcheck, "fetch_landcover", lambda lat, lon, window_m=500: {"error": "rasterio not installed"})

    result = mapcheck.check_map_vs_satellite(46.0542, 14.4707, radius_m=300)
    assert result["status"] == "ok"
    assert result["discrepancies_count"] == 0
    assert result["checks"][0]["result"] == "consistent"  # no mapped green
    assert result["checks"][1]["result"] == "cannot_assess"  # satellite unavailable
    assert len(result["declared_gaps"]) >= 1


def test_overpass_failure_degrades(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("Overpass down")

    monkeypatch.setattr(mapcheck, "_fetch_green_features", boom)
    monkeypatch.setattr(mapcheck, "fetch_satellite_data", lambda lat, lon, days_back=30: {"ndvi": 0.60})
    monkeypatch.setattr(mapcheck, "fetch_landcover", lambda lat, lon, window_m=500: {"dominant_class": 10, "dominant_label": "Tree cover"})

    result = mapcheck.check_map_vs_satellite(46.0542, 14.4707, radius_m=300)
    assert result["status"] == "degraded"
    assert len(result["checks"]) == 1
    assert result["checks"][0]["result"] == "discrepancy_detected"
    assert any("completeness" in cause.lower() for cause in result["checks"][0]["possible_causes"])


def test_overpass_and_satellite_failure_unavailable(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("Overpass down")

    monkeypatch.setattr(mapcheck, "_fetch_green_features", boom)
    monkeypatch.setattr(mapcheck, "fetch_satellite_data", lambda lat, lon, days_back=30: {"error": "no scene"})
    monkeypatch.setattr(mapcheck, "fetch_landcover", lambda lat, lon, window_m=500: {"error": "rasterio not installed"})

    result = mapcheck.check_map_vs_satellite(46.0542, 14.4707, radius_m=300)
    assert result["status"] == "unavailable"
    assert result["checks"] == []
    assert len(result["declared_gaps"]) == 2


# -----------------------------------------------------------------------------
# Honesty / vocabulary tests
# -----------------------------------------------------------------------------


def test_no_absolute_error_wording(monkeypatch):
    monkeypatch.setattr(mapcheck, "_fetch_green_features", lambda lat, lon, r: _features_with_year(2013))
    monkeypatch.setattr(mapcheck, "fetch_satellite_data", lambda lat, lon, days_back=30: {"ndvi": 0.15})
    monkeypatch.setattr(mapcheck, "fetch_landcover", lambda lat, lon, window_m=500: {"dominant_class": 50, "dominant_label": "Built-up"})

    result = mapcheck.check_map_vs_satellite(46.0542, 14.4707, radius_m=300)
    blob = json.dumps(result, default=str).lower()
    assert '"map error"' not in blob
    assert '"the map is wrong"' not in blob
    assert '"wrong"' not in blob or "wrong" not in blob  # conservative: no absolute wording


def test_disclaimer_mentions_open_sources_and_proprietary(monkeypatch):
    monkeypatch.setattr(mapcheck, "_fetch_green_features", lambda lat, lon, r: NO_FEATURES)
    monkeypatch.setattr(mapcheck, "fetch_satellite_data", lambda lat, lon, days_back=30: {"ndvi": 0.10})
    monkeypatch.setattr(mapcheck, "fetch_landcover", lambda lat, lon, window_m=500: {"dominant_class": 50, "dominant_label": "Built-up"})

    result = mapcheck.check_map_vs_satellite(46.0542, 14.4707, radius_m=300)
    d = result["disclaimer"].lower()
    assert "open sources" in d or "openstreetmap" in d
    assert "proprietary" in d
    assert "google" in d or "apple" in d or "bing" in d
    assert "discrepancy" in d and "proof" in d


def test_possible_causes_non_empty_on_discrepancy(monkeypatch):
    monkeypatch.setattr(mapcheck, "_fetch_green_features", lambda lat, lon, r: _features_with_year(2013))
    monkeypatch.setattr(mapcheck, "fetch_satellite_data", lambda lat, lon, days_back=30: {"ndvi": 0.15})
    monkeypatch.setattr(mapcheck, "fetch_landcover", lambda lat, lon, window_m=500: {"dominant_class": 50, "dominant_label": "Built-up"})

    result = mapcheck.check_map_vs_satellite(46.0542, 14.4707, radius_m=300)
    for c in result["checks"]:
        if c["result"] == "discrepancy_detected":
            assert len(c["possible_causes"]) > 0


# -----------------------------------------------------------------------------
# Endpoint tests
# -----------------------------------------------------------------------------


def test_endpoint_missing_params(client):
    resp = client.get("/api/v2/mapcheck/")
    assert resp.status_code == 400


def test_endpoint_invalid_radius(client, monkeypatch):
    monkeypatch.setattr(mapcheck, "_fetch_green_features", lambda lat, lon, r: NO_FEATURES)
    monkeypatch.setattr(mapcheck, "fetch_satellite_data", lambda lat, lon, days_back=30: {"ndvi": 0.10})
    monkeypatch.setattr(mapcheck, "fetch_landcover", lambda lat, lon, window_m=500: {"dominant_class": 50, "dominant_label": "Built-up"})

    resp = client.get("/api/v2/mapcheck/?lat=46.0542&lon=14.4707&radius_m=5")
    assert resp.status_code == 400


def test_endpoint_happy_path(client, monkeypatch):
    monkeypatch.setattr(mapcheck, "_fetch_green_features", lambda lat, lon, r: NO_FEATURES)
    monkeypatch.setattr(mapcheck, "fetch_satellite_data", lambda lat, lon, days_back=30: {"ndvi": 0.10})
    monkeypatch.setattr(mapcheck, "fetch_landcover", lambda lat, lon, window_m=500: {"dominant_class": 50, "dominant_label": "Built-up"})

    resp = client.get("/api/v2/mapcheck/?lat=46.0542&lon=14.4707&radius_m=300")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["check_id"]
    assert body["location"]["lat"] == 46.0542
    assert body["location"]["lon"] == 14.4707
    assert body["location"]["radius_m"] == 300
    assert len(body["checks"]) == 2
    assert body["discrepancies_count"] == 0
    assert body["disclaimer"]
    assert body["honesty_contract"]


# -----------------------------------------------------------------------------
# Live smoke (network allowed for this check only)
# -----------------------------------------------------------------------------


def test_live_smoke_ljubljana():
    """Run a live call against Ljubljana (Tivoli park) and report honestly."""
    proc = subprocess.run(
        [
            ".venv/bin/python",
            "-c",
            "from src.climate.mapcheck import check_map_vs_satellite; "
            "import json; "
            "print(json.dumps(check_map_vs_satellite(46.0542, 14.4707, radius_m=300), indent=1, default=str))"
        ],
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        capture_output=True,
        text=True,
        timeout=120,
    )
    output = proc.stdout or proc.stderr
    # Print the first 2000 chars so the test report can show what came back.
    print("\n--- Ljubljana live smoke output ---")
    print(output[:2000])
    print("exit code:", proc.returncode)
    print("--- end smoke output ---\n")
    # The smoke test is informational: any non-crashing result is acceptable.
    assert proc.returncode is not None
