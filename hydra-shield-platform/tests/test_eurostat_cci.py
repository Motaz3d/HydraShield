"""
Offline tests for src/climate/eurostat_cci.py — Eurostat STS_COPI_A
construction-cost calibration. The network fetch is monkeypatched; the
TSV fixture mirrors the real SDMX 2.1 format (COST rows, flags, missing
":" cells).
"""

import os

import pytest

os.environ["HYDRASHIELD_CACHE_DB"] = "/tmp/hydrashield_test_cci_cache.sqlite3"
if os.path.exists(os.environ["HYDRASHIELD_CACHE_DB"]):
    os.remove(os.environ["HYDRASHIELD_CACHE_DB"])

from src.climate import eurostat_cci as cci  # noqa: E402


_TSV = (
    "freq,indic_bt,cpa2_1,s_adj,unit,geo\\TIME_PERIOD\t2019 \t2020 \t2021 \t2022 \t2023 \n"
    "A,COST,CPA_F41001_X_410014,NSA,I15,DE\t108.6 \t111.0 \t113.2 \t120.9 \t137.4 \n"
    "A,COST,CPA_F41001_X_410014,NSA,I15,BE\t100.0 \t101.0 \t102.0 \t110.0 \t: \n"
    "A,PRC_PRR,CPA_F41001_X_410014,NSA,I15,LU\t104.2 \t105.0 \t105.8 \t110.0 \t121.0 p\n"
    "A,PRC_PRR,CPA_F41001_X_410014,NSA,I21,LU\t90.0 \t91.0 \t100.0 \t104.0 \t114.0 \n"
    "A,PRIN,CPA_F41001_X_410014,NSA,I15,DE\t200.0 \t200.0 \t200.0 \t200.0 \t200.0 \n"
    "A,COST,CPA_F41001_X_410014,NSA,I15,FR\t: \t: \t: \t: \t: \n"
)


def _patch_fetch(monkeypatch, text=_TSV):
    monkeypatch.setattr(cci, "_fetch_cci_tsv", lambda: text)


def test_parse_cci_tsv_keeps_cost_rows_and_flags():
    table = cci.parse_cci_tsv(_TSV)
    assert set(table.keys()) == {"DE", "LU", "BE"}  # PRIN row skipped; FR all-missing skipped
    assert table["DE"][2023] == {"value": 137.4, "flag": "",
                                 "indic_bt": "COST", "unit": "I15"}
    # LU is served by its producer-price series (no COST series exists for
    # it — mirroring the real dataset), preferring the I15 index base.
    assert table["LU"][2023]["flag"] == "p"
    assert table["LU"][2023]["indic_bt"] == "PRC_PRR"
    assert table["LU"][2023]["unit"] == "I15"
    assert table["LU"][2019]["value"] == 104.2


def test_latest_cci_picks_max_year(monkeypatch):
    _patch_fetch(monkeypatch)
    latest = cci.latest_cci("LU")
    assert latest["year"] == 2023 and latest["value"] == 121.0
    assert latest["flag"] == "p" and latest["indic_bt"] == "PRC_PRR"
    assert cci.latest_cci("XX") is None


def test_calibration_factor_and_method(monkeypatch):
    _patch_fetch(monkeypatch)
    cal = cci.calibration("DE", basis_year=2021)
    assert cal["status"] == "ok"
    assert cal["factor"] == round(137.4 / 113.2, 4)
    assert cal["basis_year"] == 2021 and cal["basis_value"] == 113.2
    assert cal["latest_year"] == 2023 and cal["latest_value"] == 137.4
    assert cal["series"] == {"indic_bt": "COST", "unit": "I15"}
    assert "STS_COPI_A" in cal["source"]
    assert cal["url"].startswith("https://")
    assert "scaled" in cal["method"]
    # LU calibrates through its producer-price series.
    cal_lu = cci.calibration("LU", basis_year=2021)
    assert cal_lu["status"] == "ok"
    assert cal_lu["factor"] == round(121.0 / 105.8, 4)
    assert cal_lu["series"]["indic_bt"] == "PRC_PRR"


def test_calibration_uses_nearest_earlier_basis_when_missing(monkeypatch):
    """Publication lag (series stops at 2022): the nearest earlier official
    value is used as the basis — and the substitution is printed."""
    _patch_fetch(monkeypatch)
    cal = cci.calibration("BE", basis_year=2023)
    assert cal["status"] == "ok"
    assert cal["basis_year"] == 2023
    assert cal["basis_year_used"] == 2022
    assert cal["factor"] == 1.0  # latest == basis (series ends 2022)
    assert "nearest earlier official value" in cal["method"]


def test_calibration_unavailable_paths(monkeypatch):
    _patch_fetch(monkeypatch)
    assert cci.calibration(None)["status"] == "unavailable"
    assert cci.calibration("XX")["status"] == "unavailable"
    # Missing basis year value.
    cal = cci.calibration("DE", basis_year=1990)
    assert cal["status"] == "unavailable"
    assert "1990" in cal["reason"]
    # Fetch failure degrades honestly.
    monkeypatch.setattr(
        cci, "_fetch_cci_tsv",
        lambda: (_ for _ in ()).throw(RuntimeError("Eurostat down")))
    assert "Eurostat down" in cci.calibration("DE")["reason"]
