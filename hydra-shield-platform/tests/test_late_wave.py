"""
Offline tests for the 2026-09 late-night wave: IBTrACS cyclone archive,
USGS gauge daily history, CAMS dust pipeline (key-gated).

No network: transports and file reads are faked/mocked throughout.
"""

import csv
import io
import json

import pytest

from src.dashboard import real_data
from src.climate import cams, ibtracs
from src.climate.hazards.cyclone import CycloneModule
from src.climate.hazards.dust import DustModule
from src.climate.hazards.flood import FloodModule


# ---------------------------------------------------------------------------
# IBTrACS loader + cyclone wiring
# ---------------------------------------------------------------------------

_IBTRACS_CSV = """SID,SEASON,NUMBER,BASIN,SUBBASIN,NAME,ISO_TIME,NATURE,LAT,LON,WMO_WIND,WMO_PRES,WMO_AGENCY,TRACK_TYPE,DIST2LAND,LANDFALL,IFLAG,USA_AGENCY,USA_ATCF_ID,USA_LAT,USA_LON,USA_RECORD,USA_STATUS,USA_WIND,USA_PRES,USA_SSHS
 ,Year, , , , , , ,degrees_north,degrees_east,kts,mb, , ,km,km, , , ,degrees_north,degrees_east, , ,kts,mb,1
2023005S18142,2025,1,NI,,TESTSTORM,2025-01-04 18:00:00,DS,25.0,55.0, , , ,main,0,0,O______________,jtwc_sh,SH072025,25.0,55.0, ,TS,35,1002,0
2023005S18142,2025,1,NI,,TESTSTORM,2025-01-05 00:00:00,DS,25.3,55.4, , , ,main,0,0,P______________, ,SH072025,25.3,55.4, ,TS,55,990,1
2023005S18142,2025,1,NI,,TESTSTORM,2025-01-05 06:00:00,HU,25.8,55.9, , , ,main,0,0,P______________, ,SH072025,25.8,55.9, ,HU,80,970,2
2024999S99999,2024,2,WP,,FARSTORM,2024-06-01 00:00:00,TS,10.0,140.0, , , ,main,0,0,O______________,jtwc_sh,WP012024,10.0,140.0, ,TS,40,1000,0
"""


def _mount_ibtracs(monkeypatch, tmp_path):
    csv_path = tmp_path / "ibtracs.test.csv"
    csv_path.write_text(_IBTRACS_CSV, encoding="utf-8")
    monkeypatch.setattr(ibtracs, "_LOCAL_FILE", str(csv_path))
    ibtracs.reset_for_tests()


def test_ibtracs_parse_and_storms_near(monkeypatch, tmp_path):
    _mount_ibtracs(monkeypatch, tmp_path)
    out = ibtracs.storms_near(25.2, 55.2, year=2025, radius_km=500)
    assert "error" not in out
    assert out["total_matching"] == 1
    storm = out["storms"][0]
    assert storm["name"] == "TESTSTORM"
    assert storm["season"] == 2025
    assert storm["max_wind_kt"] == 80.0
    assert storm["min_pres_mb"] == 970.0
    assert storm["peak_sshs"] == 2.0
    assert storm["closest_approach_km"] < 80.0
    assert 2023 not in out["coverage"]["seasons"] or 2025 in out["coverage"]["seasons"]

    # FARSTORM is far away → not returned
    out = ibtracs.storms_near(25.2, 55.2, year=2024, radius_km=500)
    assert out["total_matching"] == 0

    # season outside the file → honest coverage error
    out = ibtracs.storms_near(25.2, 55.2, year=1999, radius_km=500)
    assert "error" in out and "1999" in out["error"]


def test_ibtracs_decimate_keeps_endpoints():
    points = [{"t": i} for i in range(100)]
    dec = ibtracs._decimate(points, max_points=10)
    assert len(dec) == 10
    assert dec[0] == points[0] and dec[-1] == points[-1]


def test_cyclone_events_year_uses_ibtracs(monkeypatch, tmp_path):
    _mount_ibtracs(monkeypatch, tmp_path)
    out = CycloneModule().events(25.2, 55.2, radius_km=500, year=2025)
    assert out["status"] == "ok"
    assert out["year"] == 2025
    assert out["events"][0]["name"] == "TESTSTORM"
    assert "never a seasonal forecast" in out["note"]
    layers = {l["layer_id"]: l for l in CycloneModule().map_layers()}
    assert layers["cyclone.ibtracs_tracks"]["status"] == "available"


def test_cyclone_analyze_historical_block(monkeypatch, tmp_path):
    _mount_ibtracs(monkeypatch, tmp_path)
    monkeypatch.setattr(
        real_data, "fetch_active_cyclones",
        lambda: {"features": [],
                 "source": "GDACS — Global Disaster Alert and Coordination System (UN-OCHA / EU JRC)",
                 "request_url": "https://x"})
    result = CycloneModule().analyze(25.2, 55.2)
    assert result.status == "ok"
    hist = result.blocks["historical_tracks"]
    assert hist["status"] == "ok"
    assert hist["storms_within_region"] >= 1
    assert hist["storms"][0]["name"] == "TESTSTORM"
    assert "historical_tracks" in result.provenance


# ---------------------------------------------------------------------------
# USGS gauge daily history (dv)
# ---------------------------------------------------------------------------

_DV_PAYLOAD = {
    "value": {"timeSeries": [{
        "sourceInfo": {"siteName": "Stony Brook at Princeton NJ"},
        "values": [{"value": [
            {"value": "12.5", "qualifiers": ["P"], "dateTime": "2026-08-01T00:00:00.000"},
            {"value": "198", "qualifiers": ["A"], "dateTime": "2026-08-02T00:00:00.000"},
            {"value": "bad", "qualifiers": ["P"], "dateTime": "2026-08-03T00:00:00.000"},
        ]}],
    }]},
}


def test_usgs_gauge_history_parsing(monkeypatch):
    monkeypatch.setattr(real_data, "_get_json",
                        lambda url, timeout=15.0: _DV_PAYLOAD)
    out = real_data.fetch_usgs_gauge_history.__wrapped__(
        "01401000", "2026-08-01", "2026-08-03")
    assert "error" not in out
    assert out["time"] == ["2026-08-01", "2026-08-02", "2026-08-03"]
    assert out["discharge_m3s"][0] == pytest.approx(12.5 * 0.0283168466, abs=0.001)
    assert out["discharge_m3s"][2] is None          # bad value → honest None
    assert out["provisional_days"] == 2
    assert "never merged" in out["note"]


def test_usgs_gauge_history_error_paths(monkeypatch):
    assert "error" in real_data.fetch_usgs_gauge_history.__wrapped__(
        "", "2026-08-01", "2026-08-03")
    monkeypatch.setattr(real_data, "_get_json",
                        lambda url, timeout=15.0: {"value": {"timeSeries": []}})
    assert "error" in real_data.fetch_usgs_gauge_history.__wrapped__(
        "01401000", "2026-08-01", "2026-08-03")


def test_flood_gauge_history_block():
    hist = {
        "site_code": "01401000", "name": "Stony Brook",
        "time": ["2026-08-01", "2026-08-02", "2026-08-03"],
        "discharge_m3s": [1.0, 5.0, 3.0],
        "provisional_days": 1, "source": real_data.USGS_WATER_SOURCE,
        "note": "n",
    }
    block = FloodModule()._gauge_history_block(hist)
    assert block["status"] == "ok"
    assert block["claim_status"] == "OBSERVED"
    assert block["latest"]["discharge_m3s"] == 3.0
    assert block["year_max"]["discharge_m3s"] == 5.0
    assert block["latest"]["percentile_in_own_year"] is not None

    assert FloodModule()._gauge_history_block({"error": "down"})["status"] == "unavailable"


# ---------------------------------------------------------------------------
# CAMS dust pipeline (key-gated)
# ---------------------------------------------------------------------------

def test_cams_key_required_without_env(monkeypatch):
    monkeypatch.delenv("CAMS_ADS_KEY", raising=False)
    monkeypatch.delenv("CAMS_ADS_URL", raising=False)
    assert cams.credentials() is None
    out = cams.fetch_cams_dust_aod(25.0, 45.0)
    assert out.get("key_required") is True
    assert "CAMS" in out["error"]

    module = DustModule()
    available, reason = module.availability()
    assert available is False and "CAMS" in reason
    result = module.analyze(25.0, 45.0)
    assert result.status == "unavailable"


def test_cams_aod_bands():
    assert cams.aod_band(0.1) == "Low dust load"
    assert cams.aod_band(0.35) == "Moderate dust load"
    assert cams.aod_band(0.7) == "High dust load"
    assert cams.aod_band(1.5) == "Very high dust load"
    assert cams.aod_band(None) is None


def test_cams_find_asset_href():
    job = {"status": "successful",
           "results": {"asset": {"value": {"href": "https://download.test/x.nc"}}}}
    assert cams._find_asset_href(job["results"]) == "https://download.test/x.nc"
    assert cams._find_asset_href({"a": [{"b": {"href": "https://x/y.nc"}}]}) == "https://x/y.nc"
    assert cams._find_asset_href({"results": {}}) is None


def test_cams_job_choreography(monkeypatch, tmp_path):
    """Full ADS round-trip with mocked HTTP + a real raster file standing
    in for the NetCDF (the extraction logic is format-agnostic)."""
    monkeypatch.setenv("CAMS_ADS_KEY", "test-key")
    calls = []

    def fake_request(url, key, payload=None):
        calls.append(url)
        if "execution" in url:
            assert payload["inputs"]["variable"] == [cams.CAMS_VARIABLE]
            assert payload["inputs"]["leadtime_hour"] == ["0", "24"]
            return {"jobID": "job-1"}
        return {"status": "successful",
                "results": {"asset": {"value": {"href": "https://download.test/dust.nc"}}}}

    monkeypatch.setattr(cams, "_request", fake_request)
    monkeypatch.setattr(cams, "_download", lambda href, key: b"fake-nc-bytes")

    # Stand-in raster (GeoTIFF — rasterio can write it; the NetCDF driver
    # is read-only in this build, but the extraction logic is identical).
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin
    tif = tmp_path / "dust.tif"
    with rasterio.open(
            str(tif), "w", driver="GTiff", width=8, height=8, count=2,
            dtype="float32", crs="EPSG:4326",
            transform=from_origin(43.0, 27.0, 0.5, 0.5)) as dst:
        dst.write(np.full((8, 8), 0.42, dtype="float32"), 1)
        dst.write(np.full((8, 8), 0.61, dtype="float32"), 2)

    def fake_extract(nc_bytes, lat, lon):
        with rasterio.open(str(tif)) as src:
            from pyproj import Transformer
            t = Transformer.from_crs("EPSG:4326", src.crs, always_xy=True)
            cx, cy = t.transform(lon, lat)
            col, row = src.index(cx, cy)
            return {"values": [{"band": 1, "description": None,
                                "aod": round(float(src.read(1)[row, col]), 4)},
                               {"band": 2, "description": None,
                                "aod": round(float(src.read(2)[row, col]), 4)}],
                    "grid": {"crs": str(src.crs), "resolution": src.res}}

    monkeypatch.setattr(cams, "extract_aod_series", fake_extract)
    out = cams.fetch_cams_dust_aod(25.5, 45.5, day="2026-09-03")
    assert out["status"] == "ok"
    assert out["aod_analysis"] == pytest.approx(0.42, abs=0.001)
    assert out["aod_lead24"] == pytest.approx(0.61, abs=0.001)
    assert out["band_analysis"] == "Moderate dust load"
    assert out["band_lead24"] == "High dust load"
    assert any("execution" in u for u in calls) and any("jobs/job-1" in u for u in calls)


def test_dust_analyze_with_cams(monkeypatch):
    monkeypatch.setenv("CAMS_ADS_KEY", "test-key")
    monkeypatch.setattr(cams, "fetch_cams_dust_aod", lambda lat, lon, day=None: {
        "status": "ok", "claim_status": "MODELLED",
        "dataset": cams.CAMS_DATASET, "variable": cams.CAMS_VARIABLE,
        "date": "2026-09-03",
        "leadtimes": [{"band": 1, "aod": 0.55}, {"band": 2, "aod": 0.8}],
        "aod_analysis": 0.55, "aod_lead24": 0.8,
        "band_analysis": "High dust load", "band_lead24": "High dust load",
        "grid": {"crs": "EPSG:4326", "resolution": (0.4, 0.4)},
        "source": cams.CAMS_SOURCE, "note": "n",
    })
    module = DustModule()
    available, _ = module.availability()
    assert available is True
    result = module.analyze(25.0, 45.0)
    assert result.status == "ok"
    block = result.blocks["dust_aod"]
    assert block["aod_analysis"] == 0.55
    assert block["band_analysis"] == "High dust load"
    assert "MODELLED" == block["claim_status"]
    assert "declared_limitations" in result.blocks
    assert result.evidence
    # Layer now reports key_required→available with credentials present.
    layers = {l["layer_id"]: l for l in module.map_layers()}
    assert layers["dust.forecast"]["status"] == "available"


def test_dust_analyze_cams_failure_is_honest(monkeypatch):
    monkeypatch.setenv("CAMS_ADS_KEY", "test-key")
    monkeypatch.setattr(cams, "fetch_cams_dust_aod",
                        lambda lat, lon, day=None: {"error": "ADS job failed"})
    result = DustModule().analyze(25.0, 45.0)
    assert result.status == "unavailable"
    assert "ADS job failed" in result.unavailable_reason
