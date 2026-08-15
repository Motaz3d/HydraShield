"""Tests for real_data fetchers (network mocked) and the STAC module math."""

import json
import os

import numpy as np
import pytest

# Isolate the cache DB for the whole test module.
os.environ["HYDRASHIELD_CACHE_DB"] = "/tmp/hydrashield_test_cache.sqlite3"
if os.path.exists(os.environ["HYDRASHIELD_CACHE_DB"]):
    os.remove(os.environ["HYDRASHIELD_CACHE_DB"])

from src.dashboard import real_data  # noqa: E402
from src.dashboard.cache import default_cache  # noqa: E402
from src.gis_mapping import copernicus_data  # noqa: E402


class _FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def read(self):
        return json.dumps(self.payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


# --------------------------------------------------------------------------
# Geocoding
# --------------------------------------------------------------------------

def test_geocode_location(monkeypatch):
    payload = [{"display_name": "Clervaux, Luxembourg", "lat": "50.05", "lon": "6.03"}]
    monkeypatch.setattr(
        real_data.urllib.request, "urlopen", lambda req, timeout=0: _FakeResponse(payload)
    )
    default_cache().delete(default_cache().make_key("geocode", "Clervaux"))
    out = real_data.geocode_location("Clervaux")
    assert out["lat"] == 50.05
    assert out["lon"] == 6.03
    assert "OpenStreetMap" in out["source"]


def test_geocode_not_found(monkeypatch):
    monkeypatch.setattr(
        real_data.urllib.request, "urlopen", lambda req, timeout=0: _FakeResponse([])
    )
    out = real_data.geocode_location("NoSuchPlaceXYZ123")
    assert "error" in out


# --------------------------------------------------------------------------
# Terrain (OpenTopoData)
# --------------------------------------------------------------------------

def _otd_payload(elevations):
    return {
        "status": "OK",
        "results": [{"elevation": e} for e in elevations],
    }


def test_fetch_terrain_slope_flat(monkeypatch):
    monkeypatch.setattr(
        real_data.urllib.request, "urlopen",
        lambda req, timeout=0: _FakeResponse(_otd_payload([500.0] * 9)),
    )
    out = real_data.fetch_terrain(49.9, 6.03)
    assert out["elevation_m"] == 500.0
    assert out["slope_degrees"] == 0.0
    assert "OpenTopoData" in out["source"]


def test_fetch_terrain_slope_uphill_north(monkeypatch):
    # Elevation rises towards the north -> measurable slope.
    elevations = [520.0, 520.0, 520.0, 500.0, 500.0, 500.0, 480.0, 480.0, 480.0]
    monkeypatch.setattr(
        real_data.urllib.request, "urlopen",
        lambda req, timeout=0: _FakeResponse(_otd_payload(elevations)),
    )
    out = real_data.fetch_terrain(48.5, 6.5)  # distinct coords: fresh cache entry
    assert out["slope_degrees"] > 0.5


def test_fetch_terrain_unavailable(monkeypatch):
    def boom(req, timeout=0):
        raise OSError("connection refused")

    monkeypatch.setattr(real_data.urllib.request, "urlopen", boom)
    out = real_data.fetch_terrain(10.0, 10.0)
    assert "error" in out


def test_fetch_terrain_invalid_coords():
    assert "error" in real_data.fetch_terrain(95.0, 0.0)


# --------------------------------------------------------------------------
# Weather
# --------------------------------------------------------------------------

def test_fetch_weather_current(monkeypatch):
    payload = {
        "current": {
            "temperature_2m": 27.5,
            "relative_humidity_2m": 35,
            "wind_speed_10m": 18.0,
            "wind_direction_10m": 225,
            "precipitation": 0.0,
            "soil_moisture_0_to_7cm": 0.21,
            "time": "2026-08-15T12:00",
        },
        "current_units": {"temperature_2m": "°C"},
    }
    monkeypatch.setattr(
        real_data.urllib.request, "urlopen", lambda req, timeout=0: _FakeResponse(payload)
    )
    out = real_data.fetch_weather_current(49.9, 6.03)
    assert out["temperature_c"] == 27.5
    assert out["soil_moisture_m3m3"] == 0.21
    assert "Open-Meteo" in out["source"]


# --------------------------------------------------------------------------
# FIRMS (no key configured -> honest unavailability)
# --------------------------------------------------------------------------

def test_firms_without_key_is_unavailable(monkeypatch):
    monkeypatch.delenv("FIRMS_MAP_KEY", raising=False)
    out = real_data.fetch_active_fires(39.0, -8.0)
    assert out["available"] is False
    assert "FIRMS_MAP_KEY" in out["error"]
    assert out["fires"] == []


# --------------------------------------------------------------------------
# STAC module math (synthetic bands exercise the computation, not the data)
# --------------------------------------------------------------------------

def test_match_shapes_upsamples():
    a = np.ones((10, 10))
    b = np.ones((5, 5)) * 2
    ra, rb = copernicus_data.CopernicusDataAccess._match_shapes(a, b)
    assert ra.shape == (10, 10) and rb.shape == (10, 10)
    assert np.allclose(rb, 2.0)


def test_compute_indices_masks_clouds():
    # 10 m bands 4x4; 20 m SCL 2x2 with one cloudy quadrant.
    red = np.full((4, 4), 0.1)
    nir = np.full((4, 4), 0.5)
    green = np.full((4, 4), 0.2)
    swir = np.full((4, 4), 0.3)
    scl = np.array([[4, 8], [4, 4]])  # top-right quadrant = medium cloud
    bands = {"B04": red, "B08": nir, "B03": green, "B11": swir, "SCL": scl}
    out = copernicus_data.CopernicusDataAccess().compute_indices_from_bands(bands)
    assert out["ndvi"].shape == (4, 4)
    assert np.isnan(out["ndvi"][0, 2])  # cloudy quadrant masked
    assert not np.isnan(out["ndvi"][0, 0])
    # NDVI of nir=0.5, red=0.1 is (0.4)/(0.6) ~ 0.667
    assert abs(out["ndvi"][0, 0] - 2 / 3) < 0.01


def test_downsample_grid_shape():
    arr = np.arange(48 * 48, dtype=float).reshape(48, 48)
    grid = copernicus_data.CopernicusDataAccess._downsample_grid(arr, n=8)
    assert len(grid) == 8 and all(len(row) == 8 for row in grid)
    assert grid[0][0] == float(np.mean(arr[0:6, 0:6]))


def test_downsample_grid_nan_to_none():
    arr = np.full((4, 4), np.nan)
    grid = copernicus_data.CopernicusDataAccess._downsample_grid(arr, n=2)
    assert grid == [[None, None], [None, None]]


def test_fmc_from_ndmi_matches_fuel_model_calibration():
    """Single shared calibration: identical to FuelMoistureModel."""
    from src.prediction.fuel_moisture import FuelMoistureModel

    ndmi = np.array([0.0, 0.2, 0.5])
    shared = copernicus_data._estimate_fmc_from_ndmi(ndmi)
    direct = FuelMoistureModel().estimate_fmc_from_ndmi(ndmi)
    assert np.allclose(shared, direct)


def test_get_latest_observation_without_stac_returns_none(monkeypatch):
    monkeypatch.setattr(copernicus_data, "_HAS_STAC", False)
    obs = copernicus_data.CopernicusDataAccess().get_latest_observation(49.9, 6.03)
    assert obs is None
