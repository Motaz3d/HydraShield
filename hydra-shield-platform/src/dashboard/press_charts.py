"""
Hand-drawn chart figures for the Press evidence pack.

Uses Pillow only. Returns PNG bytes on success, None when the underlying data
or the drawing dependency is unavailable — never invented pixels.
"""

from __future__ import annotations

import io
import math
from typing import List, Optional

try:
    from PIL import Image, ImageDraw

    _HAS_PIL = True
except ImportError:  # pragma: no cover
    _HAS_PIL = False

from .real_data import fetch_climate_series


def _ndvi_color(value: Optional[float]) -> tuple:
    """Map an NDVI value (-1 … 1) to an RGB colour."""
    if value is None or math.isnan(value):
        return (200, 200, 200)
    v = max(-1.0, min(1.0, float(value)))
    if v >= 0:
        # green scale
        intensity = int(55 + 200 * v)
        return (80, intensity, 80)
    # brown scale
    intensity = int(55 + 200 * (-v))
    return (intensity, 80, 40)


def build_ndvi_png(grid: List[List[Optional[float]]]) -> Optional[bytes]:
    """Render a 24×24 NDVI grid as a coloured PNG, or None if unavailable."""
    if not _HAS_PIL:
        return None
    if not grid or not isinstance(grid, list):
        return None
    n = len(grid)
    if n == 0 or any(len(row) != n for row in grid):
        return None

    cell = 20
    width = height = n * cell
    img = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    for i, row in enumerate(grid):
        for j, val in enumerate(row):
            draw.rectangle(
                [j * cell, i * cell, (j + 1) * cell, (i + 1) * cell],
                fill=_ndvi_color(val),
            )
    try:
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        return None


def _fmt(v: Optional[float], decimals: int = 1) -> str:
    if v is None:
        return "n/a"
    return f"{v:.{decimals}f}"


def _safe(text: str) -> str:
    """Normalise glyphs the PIL bitmap font cannot render (no mojibake)."""
    return (
        str(text)
        .replace("–", "-")
        .replace("—", "-")
        .replace("≥", ">=")
        .replace("≤", "<=")
        .replace("·", "|")
    )


def climate_series_png(lat: float, lon: float) -> Optional[bytes]:
    """
    Draw a combined annual temperature / precipitation context chart.

    Left y-axis: annual mean of daily maximum temperature (°C), with the
    1991–2020 baseline as a dashed horizontal line. Right y-axis: annual
    precipitation total as % of baseline (bars).
    """
    if not _HAS_PIL:
        return None

    series = fetch_climate_series(lat, lon)
    if "error" in series:
        return None
    annual = series.get("annual")
    baseline = series.get("baseline") or {}
    if not annual:
        return None

    width, height = 880, 420
    margin = {"top": 50, "right": 70, "bottom": 70, "left": 70}
    plot_w = width - margin["left"] - margin["right"]
    plot_h = height - margin["top"] - margin["bottom"]

    img = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(img)

    years = [a["year"] for a in annual]
    tmax_values = [a["mean_tmax_c"] for a in annual]
    precip_values = [a["total_precip_mm"] for a in annual]
    base_tmax = baseline.get("mean_tmax_c")
    base_precip = baseline.get("precip_mm")

    year_min, year_max = min(years), max(years)
    if year_max == year_min:
        year_max += 1

    tmax_min = min(tmax_values)
    tmax_max = max(tmax_values)
    if base_tmax is not None:
        tmax_min = min(tmax_min, base_tmax)
        tmax_max = max(tmax_max, base_tmax)
    tmax_pad = max(0.5, (tmax_max - tmax_min) * 0.1)
    tmax_min -= tmax_pad
    tmax_max += tmax_pad

    precip_min = min(precip_values)
    precip_max = max(precip_values)
    if base_precip is not None and base_precip > 0:
        pct_values = [100.0 * p / base_precip for p in precip_values]
        pmin = min(pct_values)
        pmax = max(pct_values)
    else:
        pct_values = [None] * len(precip_values)
        pmin = 50.0
        pmax = 150.0
    pmin = max(0.0, pmin - 10.0)
    pmax = pmax + 10.0
    pmax = max(pmax, 110.0)

    def x_for(year: int) -> float:
        return margin["left"] + (year - year_min) / (year_max - year_min) * plot_w

    def y_for_t(t: float) -> float:
        return margin["top"] + (1.0 - (t - tmax_min) / (tmax_max - tmax_min)) * plot_h

    def y_for_p(pct: float) -> float:
        return margin["top"] + (1.0 - (pct - pmin) / (pmax - pmin)) * plot_h

    # Grid lines
    grid_color = (230, 230, 230)
    axis_color = (80, 80, 80)
    for i in range(6):
        y = margin["top"] + i * plot_h / 5.0
        draw.line([(margin["left"], y), (width - margin["right"], y)], fill=grid_color)

    # Axes
    draw.line(
        [(margin["left"], margin["top"]), (margin["left"], height - margin["bottom"])],
        fill=axis_color,
        width=1,
    )
    draw.line(
        [
            (margin["left"], height - margin["bottom"]),
            (width - margin["right"], height - margin["bottom"]),
        ],
        fill=axis_color,
        width=1,
    )
    draw.line(
        [
            (width - margin["right"], margin["top"]),
            (width - margin["right"], height - margin["bottom"]),
        ],
        fill=axis_color,
        width=1,
    )

    # Title (centred by approximate character width)
    title = _safe(f"Climate context {year_min}–{year_max} · {lat:.3f}°N, {abs(lon):.3f}°{'E' if lon >= 0 else 'W'}")
    draw.text((width // 2 - len(title) * 3, 14), title, fill=(20, 20, 20))

    # Y-axis labels (temperature left)
    for i in range(6):
        t = tmax_min + i * (tmax_max - tmax_min) / 5.0
        y = margin["top"] + (1.0 - i / 5.0) * plot_h
        label = _fmt(t, 1)
        draw.text((margin["left"] - 8 - len(label) * 6, int(y) - 5), label, fill=(80, 80, 80))
    draw.text((margin["left"] - 50, margin["top"] - 25), "Tmax (°C)", fill=(80, 80, 80))

    # Y-axis labels (precipitation right)
    for i in range(6):
        p = pmin + i * (pmax - pmin) / 5.0
        y = margin["top"] + (1.0 - i / 5.0) * plot_h
        draw.text((width - margin["right"] + 8, int(y) - 5), _fmt(p, 0), fill=(80, 80, 80))
    draw.text((width - margin["right"] - 20, margin["top"] - 25), "Precip (% baseline)", fill=(80, 80, 80))

    # Baseline temperature line
    if base_tmax is not None:
        y_base = y_for_t(base_tmax)
        for x in range(int(margin["left"]), int(width - margin["right"]), 8):
            draw.line([(x, y_base), (x + 4, y_base)], fill=(180, 180, 180), width=1)
        bl_label = f"baseline {base_tmax:.2f}°C"
        draw.text(
            (width - margin["right"] - 4 - len(bl_label) * 6, int(y_base) - 14),
            bl_label,
            fill=(120, 120, 120),
        )

    # Bars for precipitation % of baseline
    bar_w = max(3.0, plot_w / len(years) * 0.35)
    for i, year in enumerate(years):
        pct = pct_values[i]
        if pct is None:
            continue
        x = x_for(year)
        y_top = y_for_p(pct)
        y_100 = y_for_p(100.0)
        color = (59, 130, 246) if pct >= 100.0 else (245, 158, 11)
        draw.rectangle(
            [(x - bar_w / 2, min(y_top, y_100)), (x + bar_w / 2, max(y_top, y_100))],
            fill=color,
        )

    # Temperature line
    points = [(x_for(y), y_for_t(t)) for y, t in zip(years, tmax_values)]
    if len(points) > 1:
        draw.line(points, fill=(220, 38, 38), width=2)
    for x, y in points:
        draw.ellipse([(x - 2, y - 2), (x + 2, y + 2)], fill=(220, 38, 38))

    # X-axis labels (every year if few, otherwise every N years)
    n_years = len(years)
    step = max(1, n_years // 8)
    for i in range(0, n_years, step):
        year = years[i]
        x = x_for(year)
        draw.text((int(x) - 12, height - margin["bottom"] + 8), str(year), fill=(80, 80, 80))

    # Legend
    legend_y = height - margin["bottom"] + 30
    draw.line([(margin["left"] + 10, legend_y), (margin["left"] + 40, legend_y)], fill=(220, 38, 38), width=2)
    draw.text((margin["left"] + 45, legend_y - 5), "Mean Tmax", fill=(60, 60, 60))
    draw.rectangle(
        [(margin["left"] + 140, legend_y - 5), (margin["left"] + 155, legend_y + 5)],
        fill=(59, 130, 246),
    )
    draw.text((margin["left"] + 160, legend_y - 5), _safe("Precip ≥ baseline"), fill=(60, 60, 60))
    draw.rectangle(
        [(margin["left"] + 280, legend_y - 5), (margin["left"] + 295, legend_y + 5)],
        fill=(245, 158, 11),
    )
    draw.text((margin["left"] + 300, legend_y - 5), "Precip < baseline", fill=(60, 60, 60))

    try:
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        return None
