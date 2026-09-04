"""
Offline tests for src/climate/cadastre.py — real cadastral floor areas
(NL BAG via PDOK WFS). The WFS fetch is monkeypatched with a fixture that
mirrors the real JSON feature format.
"""

import io
import json
import os

import pytest

os.environ["HYDRASHIELD_CACHE_DB"] = "/tmp/hydrashield_test_cadastre_cache.sqlite3"
if os.path.exists(os.environ["HYDRASHIELD_CACHE_DB"]):
    os.remove(os.environ["HYDRASHIELD_CACHE_DB"])

from src.climate import cadastre  # noqa: E402


_BAG_JSON = {
    "type": "FeatureCollection",
    "features": [
        {"type": "Feature", "properties": {
            "identificatie": "X1", "bouwjaar": 1959,
            "oppervlakte_min": 100, "oppervlakte_max": 140}},
        {"type": "Feature", "properties": {
            "identificatie": "X2", "bouwjaar": 1925,
            "oppervlakte_min": 63, "oppervlakte_max": 112}},
        {"type": "Feature", "properties": {
            "identificatie": "X3"}},  # no areas — skipped honestly
    ],
}


def _patch_urlopen(monkeypatch, payload=_BAG_JSON):
    class _Resp:
        def read(self):
            return json.dumps(payload).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(
        cadastre.urllib.request, "urlopen", lambda req, timeout=0: _Resp())


def test_nl_bbox_membership():
    assert cadastre._in_netherlands(52.37, 4.90) is True   # Amsterdam
    assert cadastre._in_netherlands(50.05, 6.03) is False  # Clervaux (LU)
    assert cadastre._in_netherlands(48.85, 2.35) is False  # Paris


def test_rd_bbox_transform_is_sane():
    bbox = cadastre._rd_bbox(52.37, 4.90, 1000)
    x0, y0, x1, y1 = bbox
    # Amsterdam in RD New is roughly (121000, 487000).
    assert 115000 < (x0 + x1) / 2 < 127000
    assert 481000 < (y0 + y1) / 2 < 493000
    assert round(x1 - x0) == 2000 and round(y1 - y0) == 2000


def test_bag_sample_mean_area(monkeypatch):
    _patch_urlopen(monkeypatch)
    out = cadastre._fetch_bag_area_sample.__wrapped__(52.37, 4.90, 1000)
    assert "error" not in out
    assert out["building_count"] == 2
    # mean of (100+140)/2=120 and (63+112)/2=87.5 -> 103.75
    assert out["mean_area_m2"] == pytest.approx(103.8, abs=0.1)


def test_bag_sample_empty_is_honest_error(monkeypatch):
    _patch_urlopen(monkeypatch, {"type": "FeatureCollection", "features": []})
    out = cadastre._fetch_bag_area_sample.__wrapped__(52.37, 4.90, 1000)
    assert "error" in out


def test_real_floor_area_only_inside_nl(monkeypatch):
    assert cadastre.real_floor_area_m2(50.0548, 6.0276) is None  # Luxembourg
    monkeypatch.setattr(cadastre, "_fetch_bag_area_sample",
                        lambda lat, lon, r: {"building_count": 5,
                                             "mean_area_m2": 111.0})
    info = cadastre.real_floor_area_m2(52.37, 4.90)
    assert info["mean_area_m2"] == 111.0
    assert info["building_count"] == 5
    assert "Kadaster" in info["source"] or "BAG" in info["source"]
    assert info["licence_note"] and info["method"]
    # Fetch failure -> honest None (caller keeps the declared assumption).
    monkeypatch.setattr(cadastre, "_fetch_bag_area_sample",
                        lambda lat, lon, r: {"error": "down"})
    assert cadastre.real_floor_area_m2(52.37, 4.90) is None
