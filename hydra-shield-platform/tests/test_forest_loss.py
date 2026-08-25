"""Tests for the Hansen/UMD Global Forest Change layer.

Fully offline: ``_read_layer`` is monkeypatched with synthetic arrays.
"""

import os

import numpy as np
import pytest

os.environ["HYDRASHIELD_CACHE_DB"] = "/tmp/hydrashield_test_forest_loss_cache.sqlite3"
if os.path.exists(os.environ["HYDRASHIELD_CACHE_DB"]):
    os.remove(os.environ["HYDRASHIELD_CACHE_DB"])

from src.gis_mapping import forest_loss  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_cache(tmp_path, monkeypatch):
    """Give every test an isolated cache so synthetic reads do not collide."""
    db = tmp_path / "forest_loss_cache.sqlite3"
    monkeypatch.setenv("HYDRASHIELD_CACHE_DB", str(db))
    import src.dashboard.cache as cache_mod

    monkeypatch.setattr(cache_mod, "_default_cache", None)


# -----------------------------------------------------------------------------
# Tile-tag geometry
# -----------------------------------------------------------------------------


@pytest.mark.parametrize("lat,lon,expected", [
    (-12.3, -55.4, "10S_060W"),
    (49.75, 6.64, "50N_000E"),
    (0.0, 0.0, "10N_000E"),
    (-9.9, -0.1, "00N_010W"),
    (34.0, -118.5, "40N_120W"),
])
def test_tile_tag(lat, lon, expected):
    assert forest_loss._tile_tag(lat, lon) == expected


# -----------------------------------------------------------------------------
# Synthetic fetch tests
# -----------------------------------------------------------------------------


def _make_reader(treecover, lossyear):
    """Return a fake _read_layer that ignores args and returns the given arrays."""
    def _read(lat, lon, layer, half_px):
        if layer == "treecover2000":
            return np.array(treecover, dtype=np.uint8)
        if layer == "lossyear":
            return np.array(lossyear, dtype=np.uint8)
        raise ValueError(f"unexpected layer {layer}")
    return _read


def test_no_loss_detected(monkeypatch):
    monkeypatch.setattr(
        forest_loss, "_read_layer",
        _make_reader([30, 40, 20, 10], [0, 0, 0, 0]),
    )
    result = forest_loss.fetch_forest_loss(0.0, 0.0, window_m=60.0)
    assert "error" not in result
    assert result["tree_cover_2000_mean_pct"] == 25.0
    assert result["forested_fraction_2000"] == 0.5  # >=30%: 30 and 40
    assert result["loss_detected"] is False
    assert result["loss_years"] == {}
    assert result["latest_loss_year"] is None
    assert result["loss_after_2020"] is False
    assert result["loss_pixel_fraction"] == 0.0


def test_pre_cutoff_loss_only(monkeypatch):
    monkeypatch.setattr(
        forest_loss, "_read_layer",
        _make_reader([50, 50, 50, 50], [0, 19, 0, 0]),
    )
    result = forest_loss.fetch_forest_loss(0.0, 0.0, window_m=60.0)
    assert result["loss_detected"] is True
    assert result["loss_years"] == {2019: 1}
    assert result["latest_loss_year"] == 2019
    assert result["loss_after_2020"] is False
    assert result["loss_pixel_fraction"] == 0.25
    assert result["loss_after_2020_pixel_fraction"] == 0.0


def test_post_cutoff_loss(monkeypatch):
    monkeypatch.setattr(
        forest_loss, "_read_layer",
        _make_reader([80, 80, 80, 80, 80], [0, 21, 22, 0, 21]),
    )
    result = forest_loss.fetch_forest_loss(0.0, 0.0, window_m=90.0)
    assert result["loss_detected"] is True
    assert result["loss_years"] == {2021: 2, 2022: 1}
    assert result["latest_loss_year"] == 2022
    assert result["loss_after_2020"] is True
    assert result["loss_after_2020_pixel_fraction"] == 0.6


def test_read_error_returns_honest_error(monkeypatch):
    def _broken(lat, lon, layer, half_px):
        raise RuntimeError("network timeout")

    monkeypatch.setattr(forest_loss, "_read_layer", _broken)
    result = forest_loss.fetch_forest_loss(0.0, 0.0)
    assert "error" in result
    assert "treecover2000" in result["error"]
    assert result["source"] == forest_loss._PRODUCT


def test_empty_window_returns_error(monkeypatch):
    monkeypatch.setattr(
        forest_loss, "_read_layer",
        _make_reader([], []),
    )
    result = forest_loss.fetch_forest_loss(0.0, 0.0, window_m=60.0)
    assert "error" in result
    assert "no data" in result["error"].lower()
