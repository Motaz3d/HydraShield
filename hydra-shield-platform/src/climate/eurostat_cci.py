"""
Eurostat construction-cost index (STS_COPI_A) — official price calibration
for the Talaix loss screening estimate (docs/LOSS_DATA_ACQUISITION.md §2).

Fetches the annual Eurostat series "Construction producer prices or costs,
new residential buildings" (index 2015=100) via the SDMX 2.1 TSV endpoint,
parses the COST rows per country, and derives the calibration factor
between the benchmarks' declared price-basis year and the latest official
index value. The whole table is fetched once and cached (7 days — the
series is annual).

Honesty contract: the factor scales all three declared bands equally —
the official index DATES the benchmarks, it never narrows them. Every
output carries the source, both index values, both years and the Eurostat
flags (p = provisional, e = estimated, i = value with metadata).
"""

from __future__ import annotations

import urllib.error
import urllib.request
from typing import Any, Dict, Optional

from ..dashboard.cache import cached

CCI_URL = (
    "https://ec.europa.eu/eurostat/api/dissemination/sdmx/2.1/data/"
    "STS_COPI_A?format=TSV"
)

CCI_SOURCE = (
    "Eurostat STS_COPI_A — Construction producer prices or costs, new "
    "residential buildings, annual (2015=100)"
)

TTL_CCI = 7 * 24 * 3600.0  # 7 days — the series is annual


@cached("eurostat_cci_tsv", TTL_CCI)
def _fetch_cci_tsv() -> str:
    """Download the STS_COPI_A TSV (all countries, one fetch). Cached 7 d."""
    req = urllib.request.Request(
        CCI_URL, headers={"User-Agent": "Talaix-LossCalibration/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=40.0) as resp:
            return resp.read().decode("utf-8")
    except (urllib.error.URLError, OSError) as exc:
        raise RuntimeError(f"Eurostat STS_COPI_A fetch failed: {exc}") from exc


def parse_cci_tsv(text: str) -> Dict[str, Dict[int, Dict[str, Any]]]:
    """Parse the SDMX TSV into {geo: {year: {"value", "flag"}}}.

    Only COST (construction cost) rows are kept. Cells look like
    ``"134.4 p"`` (provisional), ``"86.2 i"`` (metadata flag) or ``":"``
    (missing). The flag letters are preserved for the honesty note.
    """
    out: Dict[str, Dict[int, Dict[str, Any]]] = {}
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return out
    header = lines[0].split("\t")
    years = []
    for cell in header[1:]:
        cell = cell.strip()
        years.append(int(cell) if cell.isdigit() else None)

    for line in lines[1:]:
        cells = line.split("\t")
        dims = cells[0].split(",")
        if len(dims) < 6 or dims[1] != "COST":
            continue
        geo = dims[5].strip()
        series: Dict[int, Dict[str, Any]] = {}
        for idx, year in enumerate(years):
            if year is None or idx + 1 >= len(cells):
                continue
            raw = cells[idx + 1].strip()
            if not raw or raw == ":":
                continue
            parts = raw.split()
            try:
                value = float(parts[0])
            except (ValueError, IndexError):
                continue
            flag = " ".join(parts[1:]).strip()
            series[year] = {"value": value, "flag": flag}
        if series:
            out[geo] = series
    return out


def latest_cci(geo: str) -> Optional[Dict[str, Any]]:
    """The latest official index point for a country, or None."""
    try:
        table = parse_cci_tsv(_fetch_cci_tsv())
    except RuntimeError:
        return None
    series = table.get(geo) or {}
    if not series:
        return None
    year = max(series)
    return {"year": year, "value": series[year]["value"],
            "flag": series[year]["flag"]}


def calibration(geo: Optional[str], basis_year: int = 2023) -> Dict[str, Any]:
    """Calibration factor between the benchmarks' price-basis year and the
    latest official Eurostat index for ``geo``.

    factor = CCI(latest) / CCI(basis_year) — applied to all declared bands
    equally. ``status: unavailable`` (with reason) when the index cannot be
    fetched or the country/years are missing; callers then keep the
    declared bands unchanged.
    """
    if not geo:
        return {"status": "unavailable",
                "reason": "no country benchmark matched — generic defaults in use"}
    try:
        table = parse_cci_tsv(_fetch_cci_tsv())
    except RuntimeError as exc:
        return {"status": "unavailable", "reason": str(exc)}
    series = table.get(geo) or {}
    if not series:
        return {"status": "unavailable",
                "reason": f"Eurostat STS_COPI_A has no COST series for {geo}"}
    latest_year = max(series)
    latest = series[latest_year]
    basis = series.get(basis_year)
    if not basis:
        return {"status": "unavailable",
                "reason": f"Eurostat STS_COPI_A {geo}: no {basis_year} index value"}
    factor = latest["value"] / basis["value"]
    return {
        "status": "ok",
        "factor": round(factor, 4),
        "basis_year": basis_year,
        "basis_value": basis["value"],
        "latest_year": latest_year,
        "latest_value": latest["value"],
        "flags": {"latest": latest["flag"], "basis": basis["flag"]},
        "source": CCI_SOURCE,
        "url": CCI_URL,
        "method": (
            f"All declared benchmark bands are scaled by the official index "
            f"ratio {latest['value']} ({latest_year}) / {basis['value']} "
            f"({basis_year}) = {round(factor, 4)}. The index dates the "
            "benchmarks; band widths are unchanged."),
    }
