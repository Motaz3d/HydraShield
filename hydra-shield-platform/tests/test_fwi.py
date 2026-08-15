"""Tests for the Canadian FWI System implementation."""

import math

from src.prediction.fwi import (
    DEFAULT_SEED,
    compute_daily_fwi,
    compute_fwi_series,
    danger_class,
)


def _day(temp, rh, wind, rain, month=7, seed=None):
    seed = seed or DEFAULT_SEED
    return compute_daily_fwi(
        temp_c=temp, rh_pct=rh, wind_kmh=wind, rain_mm=rain, month=month,
        ffmc_prev=seed["ffmc"], dmc_prev=seed["dmc"], dc_prev=seed["dc"],
    )


def test_output_ranges():
    d = _day(25.0, 40.0, 15.0, 0.0)
    assert 0.0 <= d.ffmc <= 101.0
    assert d.dmc >= 0.0
    assert d.dc >= 0.0
    assert d.isi >= 0.0
    assert d.bui >= 0.0
    assert d.fwi >= 0.0
    assert d.dsr >= 0.0
    assert math.isfinite(d.fwi)


def test_rain_lowers_ffmc():
    dry = _day(25.0, 40.0, 15.0, 0.0)
    wet = _day(25.0, 40.0, 15.0, 10.0)
    assert wet.ffmc < dry.ffmc


def test_wind_raises_isi():
    calm = _day(25.0, 40.0, 2.0, 0.0)
    windy = _day(25.0, 40.0, 40.0, 0.0)
    assert windy.isi > calm.isi
    assert windy.fwi > calm.fwi


def test_hot_dry_spell_raises_fwi_over_time():
    days = [
        {"date": f"2026-07-{10 + i:02d}", "temp_c": 33.0, "rh_pct": 25.0,
         "wind_kmh": 20.0, "rain_mm": 0.0}
        for i in range(10)
    ]
    series = compute_fwi_series(days)
    assert series[-1].fwi > series[0].fwi
    assert series[-1].dc > series[0].dc


def test_state_carries_over():
    days = [
        {"date": "2026-07-10", "temp_c": 30.0, "rh_pct": 35.0, "wind_kmh": 15.0, "rain_mm": 0.0},
        {"date": "2026-07-11", "temp_c": 30.0, "rh_pct": 35.0, "wind_kmh": 15.0, "rain_mm": 0.0},
    ]
    series = compute_fwi_series(days)
    # Second day starts from the first day's codes: drought keeps accumulating.
    assert series[1].dc >= series[0].dc


def test_danger_class_thresholds():
    assert danger_class(2.0) == "Low"
    assert danger_class(15.0) == "Moderate"
    assert danger_class(30.0) == "High"
    assert danger_class(55.0) == "Extreme"
    assert danger_class(45.0, simple=False) == "Very high"


def test_dmc_stays_in_physical_range_over_long_dry_spell():
    # 30 hot dry days: DMC must accumulate to a plausible value (verified
    # against the cffdrs reference implementation: single points/day).
    days = [
        {"date": f"2026-07-{i + 1:02d}", "temp_c": 30.0, "rh_pct": 30.0,
         "wind_kmh": 15.0, "rain_mm": 0.0}
        for i in range(30)
    ]
    series = compute_fwi_series(days)
    assert 0.0 < series[-1].dmc < 300.0
    # Daily increment must be single-digit points for these conditions.
    increments = [series[i + 1].dmc - series[i].dmc for i in range(29)]
    assert max(increments) < 15.0


def test_series_length_matches_input():
    days = [
        {"date": f"2026-08-0{i}", "temp_c": 28.0, "rh_pct": 45.0, "wind_kmh": 10.0, "rain_mm": 0.0}
        for i in range(1, 6)
    ]
    assert len(compute_fwi_series(days)) == 5
