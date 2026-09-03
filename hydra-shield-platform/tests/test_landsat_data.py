"""
Offline tests for the Landsat Collection 2 Level-2 adapter
(src/gis_mapping/landsat_data.py) and its fallback wiring into
src/dashboard/real_data.fetch_satellite_data.

No network: STAC searches, SAS signing, windowed band reads and the cache
are all replaced with fakes — the tests pin the band mapping, the QA_PIXEL
cloud mask, the Landsat scale/offset guard and the Sentinel-2 → Landsat
fallback contract. Nothing here touches real services.
"""

from datetime import datetime
from types import SimpleNamespace

import numpy as np
import pytest

from src.gis_mapping import copernicus_data, landsat_data
from src.gis_mapping.landsat_data import LandsatDataAccess
from src.dashboard import real_data


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

def _fake_product(item):
    return {
        "id": "LC09_L2SP_196026_20260811_02_T1",
        "title": "LC09_L2SP_196026_20260811_02_T1",
        "date": "2026-08-11",
        "cloud_cover": 4.2,
        "link": "https://example.test/item",
        "constellation": "landsat-9",
        "_item": item,
    }


def _fake_item(asset_keys=("red", "nir08", "green", "swir16", "qa_pixel")):
    assets = {
        k: SimpleNamespace(href=f"https://blob.test/{k}.tif", extra_fields={})
        for k in asset_keys
    }
    return SimpleNamespace(id="LC09_L2SP_196026_20260811_02_T1", assets=assets)


def _meta(scale, offset, nodata=0):
    return {
        "scale": scale, "offset": offset, "nodata": nodata,
        "resolution_m": 30.0,
        "bounds": {"lat_min": 49.0, "lat_max": 50.0,
                   "lon_min": 5.0, "lon_max": 6.0},
    }


def _patch_reads(monkeypatch, scale=2.75e-05, offset=-0.2, qa_values=None):
    """Replace windowed COG reads with synthetic 4x4 arrays."""
    arr = np.full((4, 4), 8000.0)          # raw DN
    qa = np.zeros((4, 4)) if qa_values is None else np.asarray(qa_values)
    by_asset = {
        "red": arr, "nir08": arr * 1.2, "green": arr * 0.9,
        "swir16": arr * 0.8, "qa_pixel": qa,
    }

    def fake_read(self, asset, lon, lat, window_m):
        for key, value in by_asset.items():
            if key in asset.href:
                return value.copy(), _meta(scale, offset)
        raise KeyError(asset.href)

    monkeypatch.setattr(
        copernicus_data.CopernicusDataAccess, "_read_window", fake_read)
    monkeypatch.setattr(
        LandsatDataAccess, "_sign_item_assets", lambda self, item: None)
    monkeypatch.setattr(landsat_data, "_HAS_STAC", True)


def _patch_search(monkeypatch, products):
    monkeypatch.setattr(
        LandsatDataAccess, "search_sentinel2_products",
        lambda self, lat, lon, s, e, m: products)


# ---------------------------------------------------------------------------
# Band mapping + QA mask
# ---------------------------------------------------------------------------

def test_fetch_landsat_bands_maps_assets_and_applies_scale(monkeypatch):
    item = _fake_item()
    _patch_search(monkeypatch, [_fake_product(item)])
    _patch_reads(monkeypatch)

    bands = LandsatDataAccess().fetch_landsat_bands(
        49.6, 6.1, ("2026-08-01", "2026-09-01"))

    assert set(bands) >= {"B04", "B08", "B03", "B11", "SCL", "metadata"}
    # Reflectance = DN * 2.75e-05 - 0.2
    assert bands["B04"][0, 0] == pytest.approx(8000.0 * 2.75e-05 - 0.2)
    assert bands["metadata"]["resolution_m"] == 30.0
    assert "Landsat Collection 2 Level-2" in bands["metadata"]["source"]
    assert bands["metadata"]["product_id"].startswith("LC09_")


def test_qa_pixel_bits_mask_invalid_pixels(monkeypatch):
    item = _fake_item()
    _patch_search(monkeypatch, [_fake_product(item)])
    # fill(1) | dilated cloud(2) | cirrus(4) | cloud(8) | shadow(16) |
    # snow(32) are invalid; water(64) and clear(0) stay valid.
    qa = np.zeros((4, 4))
    qa[0, 0], qa[0, 1], qa[0, 2] = 1, 8, 16
    qa[1, 0], qa[1, 1], qa[1, 2] = 2, 4, 32
    qa[2, 0] = 64  # water — kept, same treatment as Sentinel-2 SCL
    _patch_reads(monkeypatch, qa_values=qa)

    bands = LandsatDataAccess().fetch_landsat_bands(
        49.6, 6.1, ("2026-08-01", "2026-09-01"))
    scl_like = bands["SCL"]

    assert scl_like[0, 0] == 8 and scl_like[0, 1] == 8 and scl_like[0, 2] == 8
    assert scl_like[1, 0] == 8 and scl_like[1, 1] == 8 and scl_like[1, 2] == 8
    assert scl_like[2, 0] == 4          # water stays usable
    assert scl_like[3, 3] == 4          # clear pixel

    indices = LandsatDataAccess().compute_indices_from_bands(bands)
    assert np.isnan(indices["ndmi"][0, 1])      # clouded pixel excluded
    assert not np.isnan(indices["ndmi"][3, 3])  # clear pixel used


def test_scale_offset_guard_replaces_sentinel2_fallback(monkeypatch):
    """When an asset lacks raster:bands, _read_window falls back to the
    Sentinel-2 scale/offset — the Landsat adapter must substitute the
    Landsat C2 L2 conversion (2.75e-05 / -0.2), never the Sentinel-2 one."""
    item = _fake_item()
    _patch_search(monkeypatch, [_fake_product(item)])
    _patch_reads(monkeypatch,
                 scale=copernicus_data._FALLBACK_SCALE,
                 offset=copernicus_data._FALLBACK_OFFSET)

    bands = LandsatDataAccess().fetch_landsat_bands(
        49.6, 6.1, ("2026-08-01", "2026-09-01"))
    assert bands["B04"][0, 0] == pytest.approx(8000.0 * 2.75e-05 - 0.2)


def test_fetch_landsat_bands_empty_without_stac(monkeypatch):
    monkeypatch.setattr(landsat_data, "_HAS_STAC", False)
    assert LandsatDataAccess().fetch_landsat_bands(
        49.6, 6.1, ("2026-08-01", "2026-09-01")) == {}


def test_fetch_landsat_bands_empty_when_no_scenes(monkeypatch):
    _patch_search(monkeypatch, [])
    monkeypatch.setattr(landsat_data, "_HAS_STAC", True)
    assert LandsatDataAccess().fetch_landsat_bands(
        49.6, 6.1, ("2026-08-01", "2026-09-01")) == {}


# ---------------------------------------------------------------------------
# SAS signing
# ---------------------------------------------------------------------------

def test_sign_item_assets_rewrites_all_required_hrefs(monkeypatch):
    access = LandsatDataAccess()
    monkeypatch.setattr(
        access, "_sign_href", lambda href: href + "?sig=fake")
    item = _fake_item()
    access._sign_item_assets(item)
    for key in ("red", "nir08", "green", "swir16", "qa_pixel"):
        assert item.assets[key].href.endswith("?sig=fake"), key


def test_sign_item_assets_raises_on_missing_asset(monkeypatch):
    access = LandsatDataAccess()
    monkeypatch.setattr(access, "_sign_href", lambda href: href)
    item = _fake_item(asset_keys=("red", "nir08"))  # incomplete scene
    with pytest.raises(KeyError):
        access._sign_item_assets(item)


def test_sign_item_assets_raises_when_signing_fails(monkeypatch):
    access = LandsatDataAccess()
    monkeypatch.setattr(access, "_sign_href", lambda href: None)
    with pytest.raises(RuntimeError):
        access._sign_item_assets(_fake_item())


# ---------------------------------------------------------------------------
# Observation payload + cache namespace
# ---------------------------------------------------------------------------

class _FakeCache:
    def __init__(self):
        self.store = {}
        self.keys = []

    def make_key(self, namespace, *args):
        return (namespace, args)

    def get(self, key):
        self.keys.append(key)
        return self.store.get(key)

    def set(self, key, payload, ttl):
        self.store[key] = payload


def _ok_payload():
    return {
        "ok": True, "timestamp": "2026-08-11",
        "ndvi": 0.52, "ndmi": 0.31, "ndwi": 0.12,
        "cloud_cover_pct": 4.2, "valid_pixel_fraction": 0.9,
        "product_id": "LC09_L2SP_196026_20260811_02_T1",
        "resolution_m": 30.0,
        "source": "Landsat Collection 2 Level-2 (Planetary Computer STAC, real)",
        "ndvi_grid": [[0.5]], "ndmi_grid": [[0.3]],
        "grid_bounds": {"lat_min": 49.0, "lat_max": 50.0,
                        "lon_min": 5.0, "lon_max": 6.0},
    }


def test_get_latest_observation_uses_landsat_cache_namespace(monkeypatch):
    cache = _FakeCache()
    monkeypatch.setattr("src.dashboard.cache.default_cache", lambda: cache)
    monkeypatch.setattr(
        LandsatDataAccess, "_fetch_observation",
        lambda self, lat, lon, days_back, mcc: _ok_payload())

    access = LandsatDataAccess()
    obs1 = access.get_latest_observation(49.6, 6.1)
    obs2 = access.get_latest_observation(49.6, 6.1)  # served from cache

    assert obs1 is not None and obs2 is not None
    assert cache.keys[0][0] == "satellite_obs_landsat"
    assert obs1.source.startswith("Landsat Collection 2 Level-2")
    assert obs1.resolution_m == 30.0
    assert obs1.timestamp == datetime(2026, 8, 11)


def test_get_latest_observation_none_when_payload_not_ok(monkeypatch):
    cache = _FakeCache()
    monkeypatch.setattr("src.dashboard.cache.default_cache", lambda: cache)
    monkeypatch.setattr(
        LandsatDataAccess, "_fetch_observation",
        lambda self, lat, lon, days_back, mcc: {"ok": False})
    assert LandsatDataAccess().get_latest_observation(49.6, 6.1) is None


# ---------------------------------------------------------------------------
# Sentinel-2 → Landsat fallback in fetch_satellite_data
# ---------------------------------------------------------------------------

def _landsat_observation():
    return copernicus_data.SatelliteObservation(
        latitude=49.6, longitude=6.1, timestamp=datetime(2026, 8, 11),
        ndvi=0.52, ndmi=0.31, ndwi=0.12, cloud_cover_pct=4.2,
        source="Landsat Collection 2 Level-2 (Planetary Computer STAC, real)",
        processing_level="Level-2",
        product_id="LC09_L2SP_196026_20260811_02_T1",
        resolution_m=30.0, valid_pixel_fraction=0.9,
    )


def test_fetch_satellite_data_falls_back_to_landsat(monkeypatch):
    monkeypatch.setattr(
        copernicus_data.CopernicusDataAccess, "get_latest_observation",
        lambda self, lat, lon, days_back=30, max_cloud_cover=40.0: None)
    monkeypatch.setattr(
        LandsatDataAccess, "get_latest_observation",
        lambda self, lat, lon, days_back=30, max_cloud_cover=40.0:
        _landsat_observation())

    out = real_data.fetch_satellite_data(49.6, 6.1)
    assert "error" not in out
    assert out["ndvi"] == pytest.approx(0.52)
    assert out["resolution_m"] == 30.0
    assert "Landsat" in out["source"]


def test_fetch_satellite_data_prefers_sentinel2_when_available(monkeypatch):
    s2 = copernicus_data.SatelliteObservation(
        latitude=49.6, longitude=6.1, timestamp=datetime(2026, 9, 1),
        ndvi=0.61, ndmi=0.4, ndwi=0.2, cloud_cover_pct=2.0,
        source="Sentinel-2 Level-2A (Earth Search STAC, real)",
        resolution_m=10.0,
    )
    monkeypatch.setattr(
        copernicus_data.CopernicusDataAccess, "get_latest_observation",
        lambda self, lat, lon, days_back=30, max_cloud_cover=40.0: s2)

    def _must_not_be_called(self, lat, lon, days_back=30, max_cloud_cover=40.0):
        raise AssertionError("Landsat must not be queried when Sentinel-2 succeeds")

    monkeypatch.setattr(
        LandsatDataAccess, "get_latest_observation", _must_not_be_called)
    out = real_data.fetch_satellite_data(49.6, 6.1)
    assert out["resolution_m"] == 10.0
    assert "Sentinel-2" in out["source"]


def test_fetch_satellite_data_error_names_both_sensors(monkeypatch):
    monkeypatch.setattr(
        copernicus_data.CopernicusDataAccess, "get_latest_observation",
        lambda self, lat, lon, days_back=30, max_cloud_cover=40.0: None)
    monkeypatch.setattr(
        LandsatDataAccess, "get_latest_observation",
        lambda self, lat, lon, days_back=30, max_cloud_cover=40.0: None)

    out = real_data.fetch_satellite_data(49.6, 6.1)
    assert "error" in out
    assert "Sentinel-2" in out["error"] and "Landsat" in out["error"]


# ---------------------------------------------------------------------------
# Registry ↔ code link (the integrated catalog record)
# ---------------------------------------------------------------------------

def test_registry_landsat_entry_integrated_and_points_at_module():
    from src.climate import data_registry

    entry = data_registry.get("landsat-c2-l2")
    assert entry is not None
    assert entry["status"] == "integrated"
    assert entry["access_method"] == "stac"
    assert entry["commercial_use"] == "allowed"
    assert "landsat_data.py" in entry["status_note"]
    assert "fetch_satellite_data" in entry["status_note"]
    profile = entry["data_quality_profile"]
    assert "Planetary Computer" in profile["provenance_note"]
    assert "2026-09-03" in profile["validation"]
