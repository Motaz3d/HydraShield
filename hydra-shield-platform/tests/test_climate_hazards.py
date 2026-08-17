"""
Offline tests for the Stage-4 hazard foundations (flood, drought, heat,
wind, coastal) and their real-data fetchers.

No network: ``urllib.request.urlopen`` is monkeypatched with fake payloads
(fetcher tests); hazard-module tests monkeypatch the fetchers themselves and
drive ``analyze()`` with synthetic daily series (test fixtures, not product
data). Percentile / spell-detection math is checked on synthetic series.
"""

import json
import os
from datetime import date, timedelta

import pytest

# Isolate the cache DB for the whole test module.
os.environ["HYDRASHIELD_CACHE_DB"] = "/tmp/hydrashield_test_climate_cache.sqlite3"
if os.path.exists(os.environ["HYDRASHIELD_CACHE_DB"]):
    os.remove(os.environ["HYDRASHIELD_CACHE_DB"])

from src.dashboard import real_data  # noqa: E402
from src.dashboard import exposure  # noqa: E402
from src.gis_mapping import landcover  # noqa: E402
from src.climate import registry  # noqa: E402
from src.climate.hazards import _series  # noqa: E402
from src.climate.hazards.flood import FloodModule  # noqa: E402
from src.climate.hazards.drought import DroughtModule  # noqa: E402
from src.climate.hazards.heat import HeatModule  # noqa: E402
from src.climate.hazards.wind import WindModule  # noqa: E402
from src.climate.hazards.coastal import CoastalModule  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_registry():
    registry.reset_for_tests()
    yield
    registry.reset_for_tests()


class _FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def read(self):
        return json.dumps(self.payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _daily_dates(end: date, days: int):
    return [(end - timedelta(days=days - 1 - i)).isoformat() for i in range(days)]


# ---------------------------------------------------------------------------
# Fetchers (network mocked)
# ---------------------------------------------------------------------------


def test_fetch_flood_discharge_happy(monkeypatch):
    times = _daily_dates(date(2020, 1, 10), 5)
    payload = {
        "daily": {"time": times, "river_discharge": [12.0, 15.5, None, 9.0, 11.0]},
        "daily_units": {"river_discharge": "m³/s"},
    }
    monkeypatch.setattr(
        real_data.urllib.request, "urlopen", lambda req, timeout=0: _FakeResponse(payload)
    )
    out = real_data.fetch_flood_discharge(11.11, 22.22, "2020-01-06", "2020-01-10")
    assert "error" not in out
    assert out["time"] == times
    assert out["river_discharge"] == [12.0, 15.5, None, 9.0, 11.0]
    assert "GloFAS" in out["source"]


def test_fetch_flood_discharge_no_river_is_honest_error(monkeypatch):
    payload = {
        "daily": {
            "time": _daily_dates(date(2020, 1, 10), 3),
            "river_discharge": [None, None, None],
        },
        "daily_units": {"river_discharge": "m³/s"},
    }
    monkeypatch.setattr(
        real_data.urllib.request, "urlopen", lambda req, timeout=0: _FakeResponse(payload)
    )
    out = real_data.fetch_flood_discharge(33.33, 44.44, "2020-01-08", "2020-01-10")
    assert "error" in out
    assert "no GloFAS river" in out["error"].lower() or "No modelled river" in out["error"]


def test_fetch_flood_discharge_rejects_bad_inputs():
    assert "error" in real_data.fetch_flood_discharge(95.0, 0.0, "2020-01-01", "2020-01-02")
    assert "error" in real_data.fetch_flood_discharge(0.0, 0.0, "2020-01-10", "2020-01-01")


def test_fetch_daily_climate_happy(monkeypatch):
    times = _daily_dates(date(2019, 6, 5), 4)
    payload = {
        "daily": {
            "time": times,
            "precipitation_sum": [0.0, 2.4, 0.0, 5.1],
            "soil_moisture_0_to_7cm_mean": [0.31, 0.30, 0.29, 0.30],
        },
        "daily_units": {"precipitation_sum": "mm"},
    }
    monkeypatch.setattr(
        real_data.urllib.request, "urlopen", lambda req, timeout=0: _FakeResponse(payload)
    )
    out = real_data.fetch_daily_climate(
        55.55, 66.66, "2019-06-02", "2019-06-05",
        ["precipitation_sum", "soil_moisture_0_to_7cm_mean"],
    )
    assert "error" not in out
    assert out["precipitation_sum"] == [0.0, 2.4, 0.0, 5.1]
    assert out["soil_moisture_0_to_7cm_mean"][0] == 0.31
    assert "ERA5" in out["source"]


def test_fetch_daily_climate_flags_unavailable_variables(monkeypatch):
    times = _daily_dates(date(2018, 3, 5), 3)
    payload = {
        "daily": {
            "time": times,
            "precipitation_sum": [1.0, 2.0, 3.0],
            "soil_moisture_0_to_7cm_mean": [None, None, None],
        },
        "daily_units": {},
    }
    monkeypatch.setattr(
        real_data.urllib.request, "urlopen", lambda req, timeout=0: _FakeResponse(payload)
    )
    out = real_data.fetch_daily_climate(
        77.77, -33.33, "2018-03-03", "2018-03-05",
        ["precipitation_sum", "soil_moisture_0_to_7cm_mean"],
    )
    assert "error" not in out
    assert out["unavailable_variables"] == ["soil_moisture_0_to_7cm_mean"]


def test_fetch_daily_climate_rejects_unsupported_variable():
    out = real_data.fetch_daily_climate(0.0, 0.0, "2020-01-01", "2020-01-05", ["made_up_var"])
    assert "error" in out
    assert "Unsupported" in out["error"]


def test_fetch_marine_happy(monkeypatch):
    times = _daily_dates(date(2021, 4, 5), 4)
    payload = {
        "daily": {
            "time": times,
            "wave_height_max": [1.2, 1.8, 2.4, 1.1],
            "wave_period_max": [6.1, 7.0, 8.2, 5.9],
        },
        "daily_units": {"wave_height_max": "m"},
    }
    monkeypatch.setattr(
        real_data.urllib.request, "urlopen", lambda req, timeout=0: _FakeResponse(payload)
    )
    out = real_data.fetch_marine(-11.11, 130.0, "2021-04-02", "2021-04-05")
    assert "error" not in out
    assert out["wave_height_max"] == [1.2, 1.8, 2.4, 1.1]
    assert out["wave_period_max"][2] == 8.2
    assert "WAM" in out["source"]


def test_fetch_marine_land_point_is_honest_error(monkeypatch):
    payload = {
        "daily": {
            "time": _daily_dates(date(2021, 4, 5), 3),
            "wave_height_max": [None, None, None],
            "wave_period_max": [None, None, None],
        },
        "daily_units": {},
    }
    monkeypatch.setattr(
        real_data.urllib.request, "urlopen", lambda req, timeout=0: _FakeResponse(payload)
    )
    out = real_data.fetch_marine(48.0, 11.0, "2021-04-03", "2021-04-05")
    assert "error" in out
    assert "land" in out["error"].lower() or "No marine data" in out["error"]


# ---------------------------------------------------------------------------
# Series math (synthetic series)
# ---------------------------------------------------------------------------


def test_percentile_value_linear_interpolation():
    assert _series.percentile_value([1, 2, 3, 4], 50) == 2.5
    assert _series.percentile_value([1, 2, 3, 4], 0) == 1
    assert _series.percentile_value([1, 2, 3, 4], 100) == 4
    assert _series.percentile_value([10], 90) == 10
    assert _series.percentile_value([], 50) is None
    assert _series.percentile_value([None, 5, None], 50) == 5


def test_percentile_rank():
    assert _series.percentile_rank([10, 20, 30, 40], 25) == 50.0
    assert _series.percentile_rank([10, 20, 30, 40], 40) == 100.0
    assert _series.percentile_rank([10, 20, 30, 40], 5) == 0.0
    assert _series.percentile_rank([], 5) is None
    assert _series.percentile_rank([1, 2], None) is None


def test_detect_spells_min_length_and_peak():
    dates = _daily_dates(date(2024, 1, 10), 10)
    values = [1, 1, 5, 5, 5, 1, 1, 7, 7, 1]
    spells = _series.detect_spells(dates, values, 3, min_len=3, above=True)
    assert len(spells) == 1
    assert spells[0]["start"] == "2024-01-03"
    assert spells[0]["end"] == "2024-01-05"
    assert spells[0]["length_days"] == 3
    assert spells[0]["peak_value"] == 5
    spells2 = _series.detect_spells(dates, values, 3, min_len=2, above=True)
    assert len(spells2) == 2
    assert spells2[1]["peak_value"] == 7  # the later, hotter spell


def test_detect_spells_breaks_on_calendar_gap():
    dates = ["2024-01-01", "2024-01-02", "2024-01-05", "2024-01-06"]  # gap in the middle
    values = [9, 9, 9, 9]
    spells = _series.detect_spells(dates, values, 3, min_len=2, above=True)
    assert len(spells) == 2  # the gap splits the run into two 2-day spells


def test_detect_spells_below_threshold_and_per_day_thresholds():
    dates = _daily_dates(date(2024, 6, 8), 8)
    values = [2, 2, 0, 0, 0, 2, 5, 5]
    dry = _series.detect_spells(dates, values, 1.0, min_len=3, above=False)
    assert len(dry) == 1 and dry[0]["length_days"] == 3
    # Per-day thresholds: only the last two days breach their own threshold.
    thr = [10, 10, 10, 10, 10, 10, 1.5, 1.5]
    spells = _series.detect_spells(dates, values, thr, min_len=2, above=True)
    assert len(spells) == 1 and spells[0]["start"] == "2024-06-07"


def test_doy_window_pool_excludes_target_year():
    # Two years of data; the pool for a 2000 target contains only 1999 values.
    dates1999 = _daily_dates(date(1999, 12, 31), 365)
    dates2000 = _daily_dates(date(2000, 12, 30), 366)
    dates = dates1999 + dates2000
    values = [1.0] * 365 + [99.0] * 366
    pool = _series.doy_window_pool(dates, values, "2000-07-15", window_days=7)
    assert pool and all(v == 1.0 for v in pool)
    assert len(pool) == 15  # ±7 days around the day-of-year


def test_window_sums_by_year_and_incomplete_exclusion():
    dates = _daily_dates(date(2024, 12, 31), 365 * 3)
    values = [1.0 + (i % 5) * 0.2 for i in range(len(dates))]
    yearly = _series.window_sums_by_year(dates, values, 30, years_back=5)
    assert [y["year"] for y in yearly] == [2024, 2023, 2022]
    expected = sum(values[-30:])
    assert yearly[0]["sum"] == pytest.approx(expected, rel=1e-9)


def test_standardized_anomaly_and_degenerate_baselines():
    z, mean, std = _series.standardized_anomaly(10.0, [12, 14, 16, 18, 20])
    assert mean == 16.0
    assert z == pytest.approx((10 - 16) / std, rel=1e-9)
    assert z < 0
    # Too few baseline years -> no honest z.
    z2, mean2, std2 = _series.standardized_anomaly(10.0, [12, 14])
    assert z2 is None and mean2 == 13.0 and std2 is None
    # Zero variance -> no honest z.
    z3, _m3, std3 = _series.standardized_anomaly(10.0, [5, 5, 5, 5, 5])
    assert z3 is None and std3 == 0.0


def test_antecedent_precipitation_index_decay():
    api = _series.antecedent_precipitation_index([10.0, 0.0, 0.0], decay=0.85)
    assert api[0] == 10.0
    assert api[1] == pytest.approx(8.5)
    assert api[2] == pytest.approx(7.225)
    # A missing day resets the recursion honestly.
    api2 = _series.antecedent_precipitation_index([10.0, None, 1.0], decay=0.85)
    assert api2[1] is None and api2[2] == 1.0


def test_rolling_sums_gap_handling():
    assert _series.rolling_sums([1, 2, 3, 4], 3) == [None, None, 6.0, 9.0]
    assert _series.rolling_sums([1, None, 3, 4], 2) == [None, None, None, 7.0]


# ---------------------------------------------------------------------------
# Module analyze() — happy paths (monkeypatched fetchers, synthetic series)
# ---------------------------------------------------------------------------


def _assert_provenance(result):
    """Provenance/evidence discipline required on every response."""
    d = result.to_dict()
    assert d["evidence"], "evidence list must not be empty"
    assert d["provenance"], "provenance must not be empty"
    for rec in d["evidence"]:
        for key in ("evidence_class", "claim_status", "temporal", "source"):
            assert rec.get(key), f"evidence record missing {key}"
    if result.level is not None:
        assert result.level.validated is False
        assert result.level.basis


def _fake_terrain(lat, lon):
    return {
        "elevation_m": 250.0,
        "slope_degrees": 4.2,
        "aspect_degrees": 180.0,
        "dataset": "eudem25m",
        "resolution": "25 m",
        "source": "DEM (OpenTopoData eudem25m, 25 m)",
    }


def _fake_osm(lat, lon, radius_m=2000):
    return {
        "counts": {
            "hospitals": 1, "schools": 2, "fire_stations": 0, "power_facilities": 1,
            "buildings": 42, "roads_all": 30, "roads_major": 2,
            "water_features": 3, "waterways": 5,
        },
        "radius_m": radius_m,
        "source": "OpenStreetMap via ohsome API (Heidelberg Institute)",
        "note": "Counts are mapped OSM features; OSM completeness varies by region.",
    }


def _fake_landcover(lat, lon, window_m=500.0):
    return {
        "dominant_class": 40,
        "dominant_label": "Cropland",
        "dominant_fraction": 0.6,
        "histogram": {
            40: {"label": "Cropland", "fraction": 0.6},
            50: {"label": "Built-up", "fraction": 0.3},
            10: {"label": "Tree cover", "fraction": 0.1},
        },
        "resolution": "10 m",
        "source": "ESA WorldCover 10m 2021 v200",
    }


def _mount_common(monkeypatch):
    monkeypatch.setattr(real_data, "fetch_terrain", _fake_terrain)
    monkeypatch.setattr(real_data, "fetch_elevation",
                        lambda lat, lon: {"elevation_m": 3.0,
                                          "source": "DEM (OpenTopoData eudem25m, 25 m)"})
    monkeypatch.setattr(exposure, "fetch_osm_context", _fake_osm)
    monkeypatch.setattr(landcover, "fetch_landcover", _fake_landcover)


# -- flood -------------------------------------------------------------------


def _flood_fakes(monkeypatch):
    today = date.today()
    days = 400
    times = _daily_dates(today, days)
    discharge = [10.0] * (days - 3) + [500.0, 500.0, 500.0]
    monkeypatch.setattr(
        real_data, "fetch_flood_discharge",
        lambda lat, lon, start, end: {
            "time": times, "river_discharge": discharge, "units": "m³/s",
            "source": "GloFAS river discharge (Copernicus EMS / EC JRC via Open-Meteo Flood API)",
            "request_url": "https://flood-api.open-meteo.com/v1/flood?fake=1",
            "note": "Hydrological model output (GloFAS), not gauge observations.",
        },
    )
    archive_end = today - timedelta(days=5)
    ptimes = _daily_dates(archive_end, days)
    precip = [2.0] * (days - 2) + [60.0, 1.0]
    monkeypatch.setattr(
        real_data, "fetch_daily_climate",
        lambda lat, lon, start, end, variables: {
            "time": ptimes, "precipitation_sum": precip, "units": {},
            "source": "Reanalysis (ERA5 / ERA5-Land via Open-Meteo archive)",
            "variables": list(variables),
            "request_url": "https://archive-api.open-meteo.com/v1/archive?fake=1",
        },
    )


def test_flood_analyze_happy(monkeypatch):
    _mount_common(monkeypatch)
    _flood_fakes(monkeypatch)
    result = FloodModule().analyze(49.75, 6.64, name="Trier")
    assert result.status == "ok"
    dis = result.blocks["river_discharge"]
    assert dis["status"] == "ok"
    assert dis["latest"]["discharge_m3s"] == 500.0
    assert dis["percentile_of_latest"] == 100.0
    assert len(dis["high_discharge_spells_last_year"]) == 1
    assert "percentile" in dis["threshold_method"]
    pr = result.blocks["extreme_precipitation"]
    assert pr["status"] == "ok"
    assert pr["max_daily_precip_mm"] == 60.0
    assert pr["antecedent_precipitation_index"]["decay"] == 0.85
    assert "NOT" in result.blocks["declared_limitations"] or "NO flood" in result.blocks["declared_limitations"]
    assert result.level is not None and result.level.label == "Very high"
    _assert_provenance(result)


def test_flood_analyze_unavailable(monkeypatch):
    _mount_common(monkeypatch)
    monkeypatch.setattr(real_data, "fetch_flood_discharge",
                        lambda *a, **k: {"error": "No modelled river discharge for this coordinate"})
    monkeypatch.setattr(real_data, "fetch_daily_climate",
                        lambda *a, **k: {"error": "Reanalysis service unavailable: boom"})
    result = FloodModule().analyze(0.0, 0.0)
    assert result.status == "unavailable"
    assert result.unavailable_reason
    assert any(r["claim_status"] == "UNKNOWN" for r in result.to_dict()["evidence"])
    _assert_provenance(result)


# -- drought -----------------------------------------------------------------


def _drought_climate_fake(monkeypatch, variables_check=None):
    today = date.today()
    archive_end = today - timedelta(days=5)
    days = 365 * 6
    times = _daily_dates(archive_end, days)
    precip = [1.0 + (i % 11) * 0.3 for i in range(days)]
    for i in range(days - 180, days):  # current half-year: very dry
        precip[i] = 0.2
    soil = [0.30 + (i % 5) * 0.01 for i in range(days)]
    for i in range(days - 7, days):
        soil[i] = 0.10
    et0 = [3.0] * days

    def fake(lat, lon, start, end, variables):
        out = {
            "time": times, "units": {},
            "source": "Reanalysis (ERA5 / ERA5-Land via Open-Meteo archive)",
            "variables": list(variables),
            "request_url": "https://archive-api.open-meteo.com/v1/archive?fake=1",
            "precipitation_sum": precip,
            "soil_moisture_0_to_7cm_mean": soil,
            "et0_fao_evapotranspiration": et0,
        }
        return out

    monkeypatch.setattr(real_data, "fetch_daily_climate", fake)


def test_drought_analyze_happy(monkeypatch):
    _mount_common(monkeypatch)
    _drought_climate_fake(monkeypatch)
    result = DroughtModule().analyze(39.0, -8.0, name="Alentejo")
    assert result.status == "ok"
    deficit = result.blocks["precipitation_deficit"]
    assert deficit["status"] == "ok"
    assert "NOT a full SPEI" in deficit["method"]
    w90 = deficit["windows"]["90"]
    assert w90["standardized_anomaly"] is not None
    assert w90["standardized_anomaly"] < -2  # current window is far below baseline
    assert w90["deficit_mm"] > 0
    sm = result.blocks["soil_moisture"]
    assert sm["status"] == "ok"
    assert sm["anomaly_m3m3"] < 0
    bal = result.blocks["water_balance"]
    assert bal["status"] == "ok"
    assert bal["balance_mm"] < 0  # ET0 far exceeds the dry-window precipitation
    assert result.blocks["dry_spells"]["status"] == "ok"
    assert result.blocks["agricultural_exposure"]["cropland_fraction"] == 0.6
    assert result.level is not None and result.level.label in ("Extreme", "Severe")
    _assert_provenance(result)


def test_drought_analyze_unavailable(monkeypatch):
    _mount_common(monkeypatch)
    monkeypatch.setattr(real_data, "fetch_daily_climate",
                        lambda *a, **k: {"error": "Reanalysis service unavailable: boom"})
    result = DroughtModule().analyze(39.0, -8.0)
    assert result.status == "unavailable"
    assert result.unavailable_reason
    assert any(r["claim_status"] == "UNKNOWN" for r in result.to_dict()["evidence"])
    _assert_provenance(result)


# -- heat / wind shared fake --------------------------------------------------


def _climate_two_window_fake(var, base_fn, recent_values):
    """Fake fetch_daily_climate distinguishing the 1991–2020 baseline call
    from the recent-window call via the start date."""

    def fake(lat, lon, start, end, variables):
        if str(start).startswith("1991"):
            start_d, end_d = date(1991, 1, 1), date(2020, 12, 31)
            days = (end_d - start_d).days + 1
            times = _daily_dates(end_d, days)
            vals = [base_fn(i) for i in range(days)]
        else:
            end_d = date.today() - timedelta(days=5)
            times = _daily_dates(end_d, len(recent_values))
            vals = list(recent_values)
        return {
            "time": times, var: vals, "units": {},
            "source": "Reanalysis (ERA5 / ERA5-Land via Open-Meteo archive)",
            "variables": list(variables),
            "request_url": "https://archive-api.open-meteo.com/v1/archive?fake=1",
        }

    return fake


def test_heat_analyze_happy(monkeypatch):
    _mount_common(monkeypatch)
    # Baseline: mild daily Tmax 14–20; recent window: last 4 days a hot spike.
    recent = [18.0] * 88 + [38.0, 39.0, 40.0, 38.5]
    monkeypatch.setattr(
        real_data, "fetch_daily_climate",
        _climate_two_window_fake("temperature_2m_max", lambda i: 15.0 + (i % 7), recent),
    )
    result = HeatModule().analyze(37.4, -5.9, name="Sevilla")
    assert result.status == "ok"
    cur = result.blocks["current_vs_climatology"]
    assert cur["latest"]["tmax_c"] == 38.5
    assert cur["percentile_vs_doy_climatology"] == 100.0
    assert "1991" in cur["method"]
    spells = result.blocks["heatwave_spells"]
    assert spells["count"] == 1
    assert spells["spells"][0]["length_days"] == 4
    assert spells["ongoing"] is True
    assert "≥3" in spells["method"] or ">= 3" in spells["method"] or "≥" in spells["method"]
    extremes = result.blocks["historical_extremes"]
    assert len(extremes["hottest_days"]) == 5
    assert extremes["hottest_days"][0]["tmax_c"] >= extremes["hottest_days"][-1]["tmax_c"]
    assert result.blocks["exposure"]["built_up_fraction"] == 0.3
    assert result.level is not None and result.level.label == "Very high"
    _assert_provenance(result)


def test_heat_analyze_unavailable(monkeypatch):
    _mount_common(monkeypatch)
    monkeypatch.setattr(real_data, "fetch_daily_climate",
                        lambda *a, **k: {"error": "Reanalysis service unavailable: boom"})
    result = HeatModule().analyze(37.4, -5.9)
    assert result.status == "unavailable"
    assert result.unavailable_reason
    assert any(r["claim_status"] == "UNKNOWN" for r in result.to_dict()["evidence"])
    _assert_provenance(result)


def test_wind_analyze_happy(monkeypatch):
    _mount_common(monkeypatch)
    # Baseline: gusts 25–37; recent window: last 3 days a storm spike.
    recent = [30.0] * 89 + [95.0, 100.0, 92.0]
    monkeypatch.setattr(
        real_data, "fetch_daily_climate",
        _climate_two_window_fake("wind_gusts_10m_max", lambda i: 25.0 + (i % 13), recent),
    )
    result = WindModule().analyze(53.6, -9.0, name="Belmullet")
    assert result.status == "ok"
    cur = result.blocks["current_vs_climatology"]
    assert cur["latest"]["gust_max_kmh"] == 92.0
    assert cur["percentile_vs_doy_climatology"] == 100.0
    spells = result.blocks["storm_spells"]
    assert spells["count"] == 1
    assert spells["ongoing"] is True
    extremes = result.blocks["historical_extremes"]
    assert len(extremes["windiest_days"]) == 5
    assert result.blocks["exposure"]["power_facilities_mapped"] == 1
    assert result.level is not None and result.level.label == "Very high"
    _assert_provenance(result)


def test_wind_analyze_unavailable(monkeypatch):
    _mount_common(monkeypatch)
    monkeypatch.setattr(real_data, "fetch_daily_climate",
                        lambda *a, **k: {"error": "Reanalysis service unavailable: boom"})
    result = WindModule().analyze(53.6, -9.0)
    assert result.status == "unavailable"
    assert result.unavailable_reason
    _assert_provenance(result)


# -- coastal -------------------------------------------------------------------


def _coastal_fakes(monkeypatch):
    today = date.today()
    days = 365 + 8  # one year of nowcast + 7 forecast days
    times = _daily_dates(today + timedelta(days=7), days)
    heights = [1.0 + (i % 9) * 0.1 for i in range(days)]
    heights[365] = 4.2  # the last nowcast day (today, index 365) is rough
    periods = [6.0] * days
    monkeypatch.setattr(
        real_data, "fetch_marine",
        lambda lat, lon, start, end: {
            "time": times, "wave_height_max": heights, "wave_period_max": periods,
            "units": {"wave_height_max": "m"},
            "source": "Ocean wave analysis/forecast (ECMWF WAM via Open-Meteo Marine API)",
            "request_url": "https://marine-api.open-meteo.com/v1/marine?fake=1",
            "note": "Wave-model output; later dates are a forecast.",
        },
    )


def test_coastal_analyze_happy(monkeypatch):
    _mount_common(monkeypatch)
    _coastal_fakes(monkeypatch)
    result = CoastalModule().analyze(43.3, -8.4, name="A Coruña")
    assert result.status == "ok"
    waves = result.blocks["waves"]
    assert waves["status"] == "ok"
    assert waves["latest"]["wave_height_max_m"] == 4.2
    assert waves["latest"]["temporal"] == "OBSERVED"
    assert waves["percentile_of_latest_vs_year"] == 100.0
    assert waves["forecast"], "forecast days must be present"
    assert all(f["temporal"] == "FORECAST" for f in waves["forecast"])
    elev = result.blocks["elevation_screening"]
    assert elev["elevation_m"] == 3.0
    assert elev["screening_band"] == "low-lying"
    assert "SCREENING ONLY" in elev["method"]
    slr = result.blocks["sea_level_rise"]
    assert slr["temporal"] == "PROJECTED"
    assert all(s["temporal"] == "SCENARIO" for s in slr["scenarios"])
    names = [s["scenario"] for s in slr["scenarios"]]
    assert names == ["SSP1-2.6", "SSP2-4.5", "SSP5-8.5"]
    assert slr["scenarios"][0]["likely_range_2100_m"] == [0.28, 0.55]
    assert slr["scenarios"][2]["likely_range_2100_m"] == [0.63, 1.01]
    assert "IPCC AR6" in slr["source"]
    # SLR never leaks into observational blocks.
    assert "sea_level" not in json.dumps(result.blocks["waves"])
    assert result.level is not None and result.level.label == "High"
    _assert_provenance(result)


def test_coastal_analyze_unavailable(monkeypatch):
    monkeypatch.setattr(real_data, "fetch_marine",
                        lambda *a, **k: {"error": "No marine data for this coordinate (likely over land)"})
    monkeypatch.setattr(real_data, "fetch_elevation",
                        lambda *a, **k: {"error": "No elevation data available for this location"})
    monkeypatch.setattr(exposure, "fetch_osm_context",
                        lambda *a, **k: {"error": "OpenStreetMap context unavailable: boom"})
    result = CoastalModule().analyze(48.0, 11.0)
    assert result.status == "unavailable"
    assert result.unavailable_reason
    _assert_provenance(result)


# ---------------------------------------------------------------------------
# Registry + /api/v2
# ---------------------------------------------------------------------------


def test_registry_lists_all_six_hazards():
    ids = registry.ids()
    assert set(ids) == {"wildfire", "flood", "drought", "heat", "wind", "coastal"}
    for module in registry.all_modules():
        d = module.descriptor()
        assert d["temporal_coverage"], module.id


def test_new_hazard_map_layers_carry_source_resolution_status():
    for hazard_id in ("flood", "drought", "heat", "wind", "coastal"):
        layers = registry.get(hazard_id).map_layers()
        assert layers, hazard_id
        for layer in layers:
            assert layer["source"], layer["layer_id"]
            assert layer["resolution"], layer["layer_id"]
            assert layer["status"] in {"available", "key_required", "unavailable"}
            assert layer["temporal"]
    # The sea-level-rise layer must be temporally separated from observations.
    slr = next(l for l in registry.get("coastal").map_layers()
               if l["layer_id"] == "coastal.slr")
    assert slr["temporal"] == "PROJECTED"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("HYDRASHIELD_CACHE_DB", str(tmp_path / "api.sqlite3"))
    from src.dashboard.api import create_app

    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def test_v2_hazards_lists_all_six(client):
    resp = client.get("/api/v2/hazards")
    assert resp.status_code == 200
    ids = [h["id"] for h in resp.get_json()["hazards"]]
    assert set(ids) == {"wildfire", "flood", "drought", "heat", "wind", "coastal"}


def test_v2_analyze_flood_with_mocked_fetchers(client, monkeypatch):
    _mount_common(monkeypatch)
    _flood_fakes(monkeypatch)
    resp = client.get("/api/v2/analyze?hazard=flood&lat=49.75&lon=6.64&name=Trier")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["hazard"] == "flood"
    assert data["status"] == "ok"
    assert data["blocks"]["river_discharge"]["status"] == "ok"
    assert data["evidence"] and data["provenance"]
    assert data["level"]["validated"] is False


def test_v2_analyze_flood_unavailable_path(client, monkeypatch):
    monkeypatch.setattr(real_data, "fetch_flood_discharge",
                        lambda *a, **k: {"error": "No modelled river discharge"})
    monkeypatch.setattr(real_data, "fetch_daily_climate",
                        lambda *a, **k: {"error": "Archive down"})
    monkeypatch.setattr(real_data, "fetch_terrain", _fake_terrain)
    monkeypatch.setattr(exposure, "fetch_osm_context", _fake_osm)
    resp = client.get("/api/v2/analyze?hazard=flood&lat=1.0&lon=1.0")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "unavailable"
    assert data["unavailable_reason"]
    assert data["evidence"], "even unavailable responses carry evidence records"


def test_v2_analyze_heat_validates_input(client):
    assert client.get("/api/v2/analyze?hazard=heat").status_code == 400
    assert client.get("/api/v2/analyze?hazard=heat&lat=999&lon=0").status_code == 400
