"""Tests for the site-context image generator.

The tests are fully offline: rasterio reads are monkeypatched with synthetic
arrays. If rasterio or Pillow is not installed the module returns None and the
tests skip the rendering path.
"""

import io

import numpy as np
import pytest

from src.dashboard import site_image


def test_site_context_caption():
    caption = site_image.site_context_caption()
    assert "WorldCover" in caption
    assert "GFC" in caption
    assert "post-2020" in caption


def test_build_site_context_png_returns_none_on_fetch_failure(monkeypatch):
    """A broken rasterio open should yield None, not an exception."""

    def broken_open(url):
        raise RuntimeError("network timeout")

    monkeypatch.setattr(site_image.rasterio, "open", broken_open)
    result = site_image.build_site_context_png(50.0, 6.0)
    assert result is None


def test_build_site_context_png_with_synthetic_arrays(monkeypatch):
    """With monkeypatched synthetic arrays the function must return PNG bytes."""
    if site_image._HAS_RASTERIO is False or site_image._HAS_PIL is False:
        pytest.skip("rasterio or Pillow not installed")

    # Small synthetic landcover (10 m) and lossyear (30 m) arrays.
    landcover = np.array([
        [10, 10, 20, 20],
        [10, 10, 20, 80],
        [40, 40, 80, 80],
        [40, 40, 80, 80],
    ], dtype=np.uint8)

    lossyear = np.array([
        [0, 21, 0, 19],
        [21, 22, 0, 0],
        [0, 0, 0, 0],
        [0, 0, 0, 0],
    ], dtype=np.uint8)

    class FakeBand:
        def __init__(self, data):
            self._data = data
            self.width = data.shape[1]
            self.height = data.shape[0]

        def read(self, _band, window=None):
            if window is None:
                return self._data
            row_off = int(window.row_off)
            col_off = int(window.col_off)
            row_stop = row_off + int(window.height)
            col_stop = col_off + int(window.width)
            return self._data[row_off:row_stop, col_off:col_stop]

    class FakeDataset:
        def __init__(self, data):
            self._data = data
            self._band = FakeBand(data)
            self.width = data.shape[1]
            self.height = data.shape[0]
            self.crs = "EPSG:4326"

        def index(self, lon, lat):
            # Centre of the synthetic arrays.
            return self._data.shape[0] // 2, self._data.shape[1] // 2

        def read(self, band, window=None):
            return self._band.read(band, window=window)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    # Patch both rasterio opens so the first call serves landcover and the
    # second serves lossyear.
    calls = []

    def fake_open(url):
        calls.append(url)
        if "ESA_WorldCover" in url:
            return FakeDataset(landcover)
        return FakeDataset(lossyear)

    monkeypatch.setattr(site_image.rasterio, "open", fake_open)

    result = site_image.build_site_context_png(50.0, 6.0)
    assert result is not None
    assert isinstance(result, bytes)
    assert result[:8] == b"\x89PNG\r\n\x1a\n"

    # Sanity: both URLs were requested.
    assert any("ESA_WorldCover" in u for u in calls)
    assert any("lossyear" in u for u in calls)
