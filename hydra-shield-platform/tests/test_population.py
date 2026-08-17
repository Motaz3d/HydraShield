"""Tests for the population-exposure layer (WorldPop) — all network-free.

The real download path (_ensure_raster) and the Nominatim country lookup are
always monkeypatched; raster reads are served by an in-memory fake dataset.
"""

import math
import os
from types import SimpleNamespace

import numpy as np
import pytest
import rasterio.crs
from affine import Affine

os.environ["HYDRASHIELD_CACHE_DB"] = "/tmp/hydrashield_test_population_cache.sqlite3"
if os.path.exists(os.environ["HYDRASHIELD_CACHE_DB"]):
    os.remove(os.environ["HYDRASHIELD_CACHE_DB"])

from src.dashboard import population as pop_module  # noqa: E402
from src.dashboard.api import create_app  # noqa: E402


# --------------------------------------------------------------------------
# In-memory WorldPop raster stand-in
# --------------------------------------------------------------------------

class _FakeRaster:
    """Minimal rasterio-like dataset: a constant-population EPSG:4326 raster
    centred on (lat0, lon0). No file, no network."""

    def __init__(self, lat0, lon0, res=0.001, size=1000, value=5.0):
        self._north = lat0 + (size / 2 + 0.5) * res
        self._west = lon0 - (size / 2 + 0.5) * res
        self._res = res
        self._value = value
        self.width = self.height = size
        self.res = (res, res)
        self.crs = rasterio.crs.CRS.from_epsg(4326)

    def index(self, x, y):
        return int((self._north - y) / self._res), int((x - self._west) / self._res)

    def read(self, band, window=None, masked=True):
        h, w = int(round(window.height)), int(round(window.width))
        return np.ma.masked_array(np.full((h, w), self._value, dtype=np.float64))

    def window_transform(self, window):
        return Affine(self._res, 0.0, self._west + window.col_off * self._res,
                      0.0, -self._res, self._north - window.row_off * self._res)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


_META = {
    "url": "https://data.worldpop.org/GIS/Population/fake/esp_pop_2025.tif",
    "product": "WorldPop Global 2 (R2025A) constrained 100 m",
    "reference_year": 2025,
    "variant": "constrained (population allocated to built-up/settled cells)",
}


def _patch_lookup_and_raster(monkeypatch, lat0, lon0, value=5.0):
    """Patch country lookup + raster download + raster open (no network)."""
    monkeypatch.setattr(pop_module, "country_code_for",
                        lambda lat, lon: {"country_code": "es", "country": "Spain",
                                          "source": "Nominatim (OpenStreetMap) reverse geocoding"})
    monkeypatch.setattr(pop_module, "_ensure_raster",
                        lambda iso3: {"path": "/tmp/fake_worldpop.tif", "meta": dict(_META)})
    raster = _FakeRaster(lat0, lon0, value=value)
    monkeypatch.setattr(pop_module, "rasterio", SimpleNamespace(open=lambda path: raster))
    return raster


# --------------------------------------------------------------------------
# country_code_for / fetch_population honest error paths
# --------------------------------------------------------------------------

def test_country_code_for_rejects_out_of_range():
    out = pop_module.country_code_for.__wrapped__(95.0, 0.0)
    assert "error" in out  # never reaches the network for invalid points


def test_fetch_population_country_lookup_error(monkeypatch):
    called = {"raster": 0}

    def no_raster(iso3):
        called["raster"] += 1
        return {"path": "unused", "meta": dict(_META)}

    monkeypatch.setattr(pop_module, "country_code_for",
                        lambda lat, lon: {"error": "Reverse geocoding failed: timeout"})
    monkeypatch.setattr(pop_module, "_ensure_raster", no_raster)
    out = pop_module.fetch_population.__wrapped__(37.6, -6.5, 3.0)
    assert "error" in out
    assert out["stage"] == "country_lookup"
    assert "Reverse geocoding failed" in out["error"]
    assert called["raster"] == 0  # no download attempted after a lookup failure


def test_fetch_population_raster_unavailable(monkeypatch):
    monkeypatch.setattr(pop_module, "country_code_for",
                        lambda lat, lon: {"country_code": "es"})
    monkeypatch.setattr(pop_module, "_ensure_raster",
                        lambda iso3: {"error": "WorldPop raster unavailable for this country: boom"})
    out = pop_module.fetch_population.__wrapped__(37.6, -6.5, 3.0)
    assert "error" in out
    assert out["stage"] == "raster_download"
    assert out["iso3"] == "ESP"


def test_fetch_population_unknown_country_mapping(monkeypatch):
    monkeypatch.setattr(pop_module, "country_code_for",
                        lambda lat, lon: {"country_code": "xx"})
    out = pop_module.fetch_population.__wrapped__(37.6, -6.5, 3.0)
    assert "error" in out
    assert "xx" in out["error"]


def test_fetch_population_rejects_out_of_range():
    out = pop_module.fetch_population.__wrapped__(0.0, 200.0, 3.0)
    assert out["error"] == "Coordinates out of range"


# --------------------------------------------------------------------------
# fetch_population happy path (fake raster): totals, density, honesty labels
# --------------------------------------------------------------------------

def test_fetch_population_density_and_labels(monkeypatch):
    _patch_lookup_and_raster(monkeypatch, 37.6, -6.5, value=5.0)
    out = pop_module.fetch_population.__wrapped__(37.6, -6.5, 3.0)
    assert out["status"] == "ok"
    assert out["iso3"] == "ESP"
    assert out["estimated_population"] > 0
    assert out["area_km2"] == round(math.pi * 3.0 ** 2, 2)
    # density = total / area (declared formula)
    assert out["mean_density_per_km2"] == pytest.approx(
        out["estimated_population"] / out["area_km2"], rel=0.01)
    # resolution / reference-year honesty
    assert out["resolution"] == "100 m (grid cells)"
    assert out["reference_year"] == 2025
    assert "CC-BY" in out["license"]
    assert "WorldPop" in out["source"]
    assert out["provenance"]["kind"] == "modeled"
    assert out["provenance"]["resolution"] == "100 m"
    assert "reference year 2025" in out["provenance"]["temporal"]
    # wording: an estimate with a reference year, never an exact count
    assert "Estimated" in out["estimate_note"]
    assert "reference year" in out["estimate_note"]
    assert "exactly" not in out["estimate_note"]
    assert "not an exact count" in out["estimate_note"]
    # downsampled grid for the map layer
    cells = out["grid"]["cells"]
    assert cells
    for cell in cells:
        assert cell["population"] >= 0.5
        assert cell["south"] <= cell["north"] and cell["west"] <= cell["east"]
    assert sum(c["population"] for c in cells) <= out["estimated_population"] + len(cells)


def test_fetch_population_second_call_served_from_cache(monkeypatch):
    calls = {"lookup": 0, "raster": 0}

    def counting_lookup(lat, lon):
        calls["lookup"] += 1
        return {"country_code": "es"}

    def counting_raster(iso3):
        calls["raster"] += 1
        return {"path": "/tmp/fake_worldpop_cache.tif", "meta": dict(_META)}

    monkeypatch.setattr(pop_module, "country_code_for", counting_lookup)
    monkeypatch.setattr(pop_module, "_ensure_raster", counting_raster)
    raster = _FakeRaster(12.3, 45.7, value=2.0)
    monkeypatch.setattr(pop_module, "rasterio", SimpleNamespace(open=lambda path: raster))

    # Call through the @cached wrapper (not __wrapped__): first call computes,
    # second must be served from the TTL cache without re-downloading.
    first = pop_module.fetch_population(12.345, 45.678, 2.5)
    second = pop_module.fetch_population(12.345, 45.678, 2.5)
    assert first["status"] == "ok"
    assert calls["lookup"] == 1
    assert calls["raster"] == 1
    assert second["estimated_population"] == first["estimated_population"]
    assert second["mean_density_per_km2"] == first["mean_density_per_km2"]


# --------------------------------------------------------------------------
# _density_level boundaries
# --------------------------------------------------------------------------

def test_density_level_boundaries():
    assert pop_module._density_level(None) is None
    assert pop_module._density_level(0.0) == "low"
    assert pop_module._density_level(24.9) == "low"
    assert pop_module._density_level(25.0) == "moderate"
    assert pop_module._density_level(99.9) == "moderate"
    assert pop_module._density_level(100.0) == "high"
    assert pop_module._density_level(499.9) == "high"
    assert pop_module._density_level(500.0) == "very high"


# --------------------------------------------------------------------------
# population_in_polygon (fake raster + honest failures)
# --------------------------------------------------------------------------

def test_population_in_polygon_too_small():
    out = pop_module.population_in_polygon("ESP", [(37.6, -6.5), (37.7, -6.4)])
    assert out["error"] == "Polygon too small"


def test_population_in_polygon_raster_unavailable(monkeypatch):
    monkeypatch.setattr(pop_module, "_ensure_raster",
                        lambda iso3: {"error": "WorldPop raster unavailable"})
    poly = [(37.5, -6.6), (37.5, -6.4), (37.7, -6.4), (37.7, -6.6)]
    out = pop_module.population_in_polygon("ESP", poly)
    assert "error" in out


def test_population_in_polygon_estimate(monkeypatch):
    monkeypatch.setattr(pop_module, "_ensure_raster",
                        lambda iso3: {"path": "/tmp/fake.tif", "meta": dict(_META)})
    raster = _FakeRaster(37.6, -6.5, value=10.0)
    monkeypatch.setattr(pop_module, "rasterio", SimpleNamespace(open=lambda path: raster))
    poly = [(37.585, -6.513), (37.585, -6.487), (37.615, -6.487), (37.615, -6.513)]
    out = pop_module.population_in_polygon("ESP", poly)
    assert "error" not in out
    assert 0 < out["estimated_population"] <= 10 * 1000 * 1000
    assert out["estimated_population"] % 10 == 0  # constant fake pixel value
    assert out["reference_year"] == 2025
    assert "Estimated" in out["estimate_note"]
    assert "reference year" in out["estimate_note"]
    assert "exactly" not in out["estimate_note"]


# --------------------------------------------------------------------------
# build_population_block (declared qualitative combination, never a probability)
# --------------------------------------------------------------------------

def _fake_pop(density, total=4200, radius_km=3.0):
    return {
        "status": "ok",
        "radius_km": radius_km,
        "estimated_population": total,
        "mean_density_per_km2": density,
        "estimate_note": ("Estimated population exposure based on WorldPop, "
                          "reference year 2025 (modelled gridded estimates at "
                          "~100 m) — not an exact count."),
        "reference_year": 2025,
        "product": _META["product"],
        "resolution": "100 m (grid cells)",
        "license": "CC-BY 4.0 (WorldPop, University of Southampton)",
        "provenance": {"kind": "modeled", "source": "WorldPop", "quality": "ok"},
    }


def _analysis(hazard="Very high", hazard_key="effis_class", with_exposure=True):
    a = {
        "location": {"latitude": 37.6, "longitude": -6.5},
        "fire_danger": {hazard_key: hazard},
    }
    if with_exposure:
        a["exposure"] = {
            "status": "ok",
            "vulnerable_assets": {"hospitals": 1, "schools": 2,
                                  "fire_stations": 0, "power_facilities": 0},
            "exposure": {"buildings_mapped": 120},
        }
    return a


def test_population_block_high_hazard_high_density(monkeypatch):
    monkeypatch.setattr(pop_module, "fetch_population", lambda lat, lon, r: _fake_pop(300.0))
    block = pop_module.build_population_block(_analysis("Very high"))
    assert block["status"] == "ok"
    assert block["human_exposure_priority"] == "high"
    assert block["density_level"] == "high"
    assert block["estimated_population_in_hazard_area"] == 4200
    assert "Very high" in block["human_exposure_note"]
    assert "high" in block["exposure_note"] or "Very high" in block["exposure_note"]
    # never folded into the risk score as a probability
    assert "never multiplied into a probability" in block["separate_from_score_note"]
    assert block["critical_facilities"]["hospitals"] == 1
    assert block["mapped_buildings"] == 120
    assert block["provenance"]["kind"] == "modeled"


def test_population_block_elevated_hazard_low_density(monkeypatch):
    monkeypatch.setattr(pop_module, "fetch_population", lambda lat, lon, r: _fake_pop(10.0))
    block = pop_module.build_population_block(_analysis("Extreme", hazard_key="class"))
    assert block["human_exposure_priority"] == "moderate"
    assert block["estimated_population_in_hazard_area"] == 4200  # still elevated


def test_population_block_low_hazard_high_density_is_watch(monkeypatch):
    monkeypatch.setattr(pop_module, "fetch_population", lambda lat, lon, r: _fake_pop(6000.0))
    block = pop_module.build_population_block(_analysis("Low"))
    assert block["human_exposure_priority"] == "watch"
    assert block["estimated_population_in_hazard_area"] is None
    assert "not elevated" in block["exposure_note"]


def test_population_block_low_hazard_low_density_is_routine(monkeypatch):
    monkeypatch.setattr(pop_module, "fetch_population", lambda lat, lon, r: _fake_pop(5.0))
    block = pop_module.build_population_block(_analysis("Low", with_exposure=False))
    assert block["human_exposure_priority"] == "routine"
    assert block["critical_facilities"] is None
    assert block["mapped_buildings"] is None


def test_population_block_unavailable_when_source_fails(monkeypatch):
    monkeypatch.setattr(pop_module, "fetch_population",
                        lambda lat, lon, r: {"error": "WorldPop raster unavailable",
                                             "stage": "raster_download"})
    block = pop_module.build_population_block(_analysis("High"))
    assert block["status"] == "unavailable"
    assert "WorldPop raster unavailable" in block["reason"]
    assert block["provenance"]["kind"] == "unavailable"
    assert block["provenance"]["quality"] == "missing"


def test_population_block_without_location_is_unavailable():
    block = pop_module.build_population_block({"fire_danger": {"class": "High"}})
    assert block["status"] == "unavailable"
    assert block["reason"] == "No analysis location"


# --------------------------------------------------------------------------
# population_exposure_overlay (risk grid + population grid intersected)
# --------------------------------------------------------------------------

def _fake_risk_grid(classes):
    return {
        "grid": {"n": 2, "cell_size_km": 4.7},
        "features": [{"properties": {"risk_class": c}} for c in classes],
    }


def _fake_pop_with_cells():
    return {
        "status": "ok",
        "estimated_population": 180,
        "mean_density_per_km2": 6.4,
        "reference_year": 2025,
        "product": _META["product"],
        "grid": {"max_cells": 24, "cells": [
            # bbox for (37.6, -6.5, 3 km): s=37.5729 n=37.6271 w=-6.5340 e=-6.4660
            {"south": 37.58, "north": 37.60, "west": -6.52, "east": -6.50,
             "population": 100},   # centre (37.59,-6.51) -> grid cell idx 0
            {"south": 37.60, "north": 37.62, "west": -6.50, "east": -6.48,
             "population": 50},    # centre (37.61,-6.49) -> grid cell idx 3
            {"south": 37.99, "north": 38.01, "west": -6.51, "east": -6.49,
             "population": 30},    # outside the bbox -> unclassified
        ]},
        "provenance": {"kind": "modeled", "source": "WorldPop"},
    }


def test_population_exposure_overlay_intersects_real_grids(monkeypatch):
    monkeypatch.setattr("src.dashboard.grid.compute_risk_grid",
                        lambda s, w, n, e, k: _fake_risk_grid(
                            ["High", "Low", "Low", "Very high"]))
    monkeypatch.setattr(pop_module, "fetch_population",
                        lambda lat, lon, r: _fake_pop_with_cells())
    out = pop_module.population_exposure_overlay.__wrapped__(37.6, -6.5, 3.0, 2)
    assert out["status"] == "ok"
    assert out["population_by_hazard_class"] == {"High": 100, "Very high": 50}
    assert out["population_unclassified"] == 30
    assert out["estimated_population"] == 180
    assert out["resolution"] == "population 100 m; hazard cells ~4.7 km"
    assert "Estimated" in out["estimate_note"]
    assert "reference year" in out["estimate_note"]
    assert out["provenance"]["population"]["kind"] == "modeled"
    assert "FWI" in out["provenance"]["hazard"]


def test_population_exposure_overlay_risk_grid_error(monkeypatch):
    monkeypatch.setattr("src.dashboard.grid.compute_risk_grid",
                        lambda s, w, n, e, k: {"error": "grid too big"})
    out = pop_module.population_exposure_overlay.__wrapped__(37.6, -6.5, 3.0, 2)
    assert "error" in out
    assert "Risk grid unavailable" in out["error"]


def test_population_exposure_overlay_population_error(monkeypatch):
    monkeypatch.setattr("src.dashboard.grid.compute_risk_grid",
                        lambda s, w, n, e, k: _fake_risk_grid(["Low"] * 4))
    monkeypatch.setattr(pop_module, "fetch_population",
                        lambda lat, lon, r: {"error": "no raster"})
    out = pop_module.population_exposure_overlay.__wrapped__(37.6, -6.5, 3.0, 2)
    assert out["error"] == "no raster"


# --------------------------------------------------------------------------
# /api/population-exposure
# --------------------------------------------------------------------------

@pytest.fixture()
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_population_exposure_endpoint_requires_input(client):
    assert client.get("/api/population-exposure").status_code == 400


def test_population_exposure_endpoint_rejects_bad_params(client):
    resp = client.get("/api/population-exposure?lat=abc&lon=-6.5")
    assert resp.status_code == 400
    resp = client.get("/api/population-exposure?lat=37.6&lon=-6.5&radius_km=abc")
    assert resp.status_code == 400


def test_population_exposure_endpoint_502_when_both_fail(client, monkeypatch):
    monkeypatch.setattr("src.dashboard.population.population_exposure_overlay",
                        lambda lat, lon, radius_km=3.0: {"error": "Risk grid unavailable: boom"})
    monkeypatch.setattr("src.dashboard.population.fetch_population",
                        lambda lat, lon, radius_km=3.0: {"error": "no raster"})
    resp = client.get("/api/population-exposure?lat=37.6&lon=-6.5")
    assert resp.status_code == 502
    assert "error" in resp.get_json()


def test_population_exposure_endpoint_falls_back_to_base(client, monkeypatch):
    monkeypatch.setattr("src.dashboard.population.population_exposure_overlay",
                        lambda lat, lon, radius_km=3.0: {"error": "Risk grid unavailable: boom"})
    monkeypatch.setattr("src.dashboard.population.fetch_population",
                        lambda lat, lon, radius_km=3.0: _fake_pop(120.0))
    resp = client.get("/api/population-exposure?lat=37.6&lon=-6.5")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["estimated_population"] == 4200
    assert "overlay_note" in body
    assert "Risk grid unavailable" in body["overlay_note"]


def test_population_exposure_endpoint_ok(client, monkeypatch):
    monkeypatch.setattr("src.dashboard.population.population_exposure_overlay",
                        lambda lat, lon, radius_km=3.0: {
                            "status": "ok",
                            "population_by_hazard_class": {"High": 100},
                            "reference_year": 2025})
    resp = client.get("/api/population-exposure?lat=37.6&lon=-6.5&radius_km=4")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["population_by_hazard_class"] == {"High": 100}
    assert body["reference_year"] == 2025
