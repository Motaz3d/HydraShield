"""
Unit tests for src/climate/losses.py.

Offline: parsing, normalisation and honesty labels are tested with small
fixture samples of the real NOAA ArcGIS JSON feature format. Network calls
are monkeypatched out.
"""

import copy
import os
from pathlib import Path

import pytest

os.environ["HYDRASHIELD_CACHE_DB"] = "/tmp/hydrashield_test_losses_cache.sqlite3"
if os.path.exists(os.environ["HYDRASHIELD_CACHE_DB"]):
    os.remove(os.environ["HYDRASHIELD_CACHE_DB"])

from src.climate import losses as losses_module  # noqa: E402


_NOAA_FEATURES = [
    {"attributes": {
        "STATE_NAME": "A-State", "STATE_ABBR": "AS",
        "drought": 10.0, "DroughtEvents": 1,
        "flooding": 20.0, "FloodingEvents": 2,
        "freeze": 0.0, "FreezeEvents": 0,
        "severe_storm": 30.0, "SevereStormEvents": 3,
        "tropical_cyclone": 40.0, "TropicalCycloneEvents": 4,
        "wildfire": 50.0, "WildfireEvents": 5,
        "winter_storm": 60.0, "WinterStormEvents": 6,
    }},
    {"attributes": {
        "STATE_NAME": "B-State", "STATE_ABBR": "BS",
        "drought": 0.5, "DroughtEvents": 0,
        "flooding": 1.5, "FloodingEvents": 1,
        "freeze": 2.5, "FreezeEvents": 2,
        "severe_storm": 3.5, "SevereStormEvents": 3,
        "tropical_cyclone": 4.5, "TropicalCycloneEvents": 4,
        "wildfire": 5.5, "WildfireEvents": 5,
        "winter_storm": 6.5, "WinterStormEvents": 6,
    }},
]


def test_parse_noaa_cost_features_aggregates_correctly():
    totals = losses_module._parse_noaa_cost_features(_NOAA_FEATURES)
    # Sum across the two states (values in $Millions).
    assert totals["all"]["cost_millions"] == pytest.approx(234.5)
    assert totals["all"]["events"] == 42
    assert totals["wildfire"]["cost_millions"] == pytest.approx(55.5)
    assert totals["wildfire"]["events"] == 10
    assert totals["drought"]["cost_millions"] == pytest.approx(10.5)


def test_parse_noaa_cost_features_ignores_missing_and_non_numeric():
    broken = copy.deepcopy(_NOAA_FEATURES)
    broken[0]["attributes"]["wildfire"] = None
    broken[1]["attributes"]["wildfire"] = "not-a-number"
    totals = losses_module._parse_noaa_cost_features(broken)
    assert totals["wildfire"]["cost_millions"] == pytest.approx(0.0)
    assert totals["wildfire"]["events"] == 10


def test_noaa_billions_figures_tagged_honestly(monkeypatch):
    monkeypatch.setattr(
        losses_module, "_fetch_noaa_billions_state_costs",
        lambda: {"features": _NOAA_FEATURES})
    figs, reason = losses_module._noaa_billions_figures()
    assert reason is None
    assert len(figs) == 4
    for fig in figs:
        assert fig["claim_status"] == "DOCUMENTED"
        assert fig["source"] == "noaa_billions"
        assert fig["reference_period"] == "1980-2021"
        assert fig["geographic_scope"] == "United States"
        assert "US government public data" in fig["licence_note"]
        assert "ArcGIS" in fig["method"]
        assert "limitations" in fig

    labels = {f["label"]: f for f in figs}
    assert labels["Total US billion-dollar disaster costs"]["value"] == 0.23  # rounded to 2 d.p.
    assert labels["Total US billion-dollar disaster costs"]["unit"] == "billion USD (CPI-adjusted)"
    assert labels["Total US billion-dollar disaster events"]["value"] == 42
    assert labels["US billion-dollar wildfire costs"]["value"] == 0.06  # rounded to 2 d.p.


def test_noaa_billions_figures_returns_reason_on_fetch_error(monkeypatch):
    monkeypatch.setattr(
        losses_module, "_fetch_noaa_billions_state_costs",
        lambda: {"error": "HTTP 503"})
    figs, reason = losses_module._noaa_billions_figures()
    assert figs == []
    assert "HTTP 503" in reason


def test_documented_loss_figures_for_us_point(monkeypatch):
    monkeypatch.setattr(
        losses_module, "_fetch_noaa_billions_state_costs",
        lambda: {"features": _NOAA_FEATURES})
    out = losses_module.documented_loss_figures(for_lat=39.0, for_lon=-98.5)
    assert out["status"] == "ok"
    assert out["figure_count"] == 4
    assert "noaa_billions" in out["sources"]


def test_documented_loss_figures_for_non_us_point():
    out = losses_module.documented_loss_figures(for_lat=48.8566, for_lon=2.3522)
    assert out["status"] == "unavailable"
    assert "outside United States" in out["reason"]


def test_load_staged_emdat_returns_figures(tmp_path, monkeypatch):
    csv_path = tmp_path / "emdat_export.csv"
    csv_path.write_text(
        "Disaster Number,Year,Country,Total Deaths\n"
        "2023-0001,2023,Fictitia,10\n"
        "2023-0002,2023,Fictitia,5\n"
    )
    monkeypatch.setattr(losses_module, "_EMDAT_EXPORT_PATH", str(csv_path))
    figs, reason = losses_module._load_staged_emdat()
    assert reason is None
    assert len(figs) == 1
    assert figs[0]["value"] == 15
    assert figs[0]["claim_status"] == "DOCUMENTED"
    assert figs[0]["source"] == "emdat"


def test_load_staged_emdat_missing_file():
    figs, reason = losses_module._load_staged_emdat()
    assert figs == []
    assert "not found" in reason


def test_load_staged_desinventar_returns_record_counts(tmp_path, monkeypatch):
    exports_dir = tmp_path / "desinventar_exports"
    exports_dir.mkdir()
    (exports_dir / "fictitia.csv").write_text(
        "event_id,date,location\nEV1,2023-01-01,PlaceA\nEV2,2023-02-01,PlaceB\n"
    )
    monkeypatch.setattr(losses_module, "_DESINVENTAR_DIR", str(exports_dir))
    figs, reason = losses_module._load_staged_desinventar()
    assert reason is None
    assert len(figs) == 1
    assert figs[0]["value"] == 2
    assert figs[0]["claim_status"] == "DOCUMENTED"
    assert figs[0]["source"] == "desinventar"


def test_load_staged_desinventar_missing_dir():
    figs, reason = losses_module._load_staged_desinventar()
    assert figs == []
    assert "not found" in reason


def test_loss_summary_items_contract(monkeypatch):
    monkeypatch.setattr(
        losses_module, "_fetch_noaa_billions_state_costs",
        lambda: {"features": _NOAA_FEATURES})
    payload = losses_module.loss_summary_items()
    assert payload["status"] == "ok"
    assert isinstance(payload["items"], list)
    assert payload["items"]
    for item in payload["items"]:
        assert set(item.keys()) == {"label", "value", "unit", "source", "reference_period"}
        assert isinstance(item["label"], str)
        assert isinstance(item["value"], str)
        assert isinstance(item["unit"], str)
        assert isinstance(item["source"], str)
        assert isinstance(item["reference_period"], str)
    assert isinstance(payload["disclaimer"], str)
