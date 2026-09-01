"""TX Engine API helpers for the QGIS plugin (``/api/tx/*``).

Pure functions only — no QGIS imports at module level, so this module is
unit-tested outside QGIS exactly like ``api_client``. The network layer
(QgsNetworkAccessManager) lives in ``api_client.http_get_json`` and is used
by the Processing algorithm on its worker thread.

The TX API returns the uniform TxResult envelope (docs/TX_ENGINE.md):
one analysis → one result per hazard, each with its honesty fields
(status, basis, validated, unavailable_reason). Nothing is filled in.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

BASE_URL = "https://talaix.com"

#: Hazard ids advertised by the TX registry (GET /api/tx/health).
TX_HAZARDS = [
    "coastal", "cyclone", "drought", "dust", "flood",
    "heat", "volcanic", "wildfire", "wind",
]

#: Depth presets accepted by the TX engine.
TX_DEPTHS = ["quick", "standard", "deep"]


def tx_analyze_url(lat: float, lon: float,
                   hazards: Optional[List[str]] = None,
                   depth: str = "standard",
                   name: Optional[str] = None,
                   base: str = BASE_URL) -> str:
    """GET /api/tx/analyze URL — repeated ``hazard`` params, TX depth."""
    from urllib.parse import quote

    url = f"{base}/api/tx/analyze?lat={lat:.5f}&lon={lon:.5f}"
    for hazard in hazards or []:
        url += f"&hazard={quote(hazard)}"
    url += f"&depth={quote(depth)}"
    if name:
        url += f"&name={quote(name)}"
    return url


def normalize_tx_result(payload: Dict[str, Any]) -> Dict[str, Any]:
    """One TxResult envelope → per-hazard feature records + summary rows.

    Each record carries the level and the honesty fields; absent values
    stay None (never invented). Rows are (key, value) pairs for the
    attribute table / dock details.
    """
    location = payload.get("location") or {}
    records: List[Dict[str, Any]] = []
    for result in payload.get("results") or []:
        if not isinstance(result, dict):
            continue
        level = result.get("level") or {}
        records.append({
            "hazard": result.get("hazard", "unknown"),
            "status": result.get("status", "unknown"),
            "summary": result.get("summary"),
            "level_label": level.get("label"),
            "level_score": level.get("score"),
            "level_score_max": level.get("score_max"),
            "level_basis": level.get("basis"),
            "validated": level.get("validated"),
            "unavailable_reason": result.get("unavailable_reason"),
            "lat": location.get("lat"),
            "lon": location.get("lon"),
            "name": location.get("name"),
            "analysis_id": payload.get("analysis_id"),
            "depth": payload.get("depth"),
            "engine_version": payload.get("engine_version"),
        })

    rows: List[Tuple[str, str]] = [
        ("analysis_id", str(payload.get("analysis_id", "unknown"))),
        ("status", str(payload.get("status", "unknown"))),
        ("depth", str(payload.get("depth", "unknown"))),
        ("engine", "tx-core {} / engine {} / tam {}".format(
            payload.get("tx_version", "?"),
            payload.get("engine_version", "?"),
            payload.get("tam_version", "?"))),
    ]
    counts = payload.get("status_counts") or {}
    if counts:
        rows.append(("status_counts", ", ".join(
            f"{key}={counts[key]}" for key in sorted(counts))))
    if payload.get("summary"):
        rows.append(("summary", str(payload["summary"])))
    for source in payload.get("sources") or []:
        if isinstance(source, dict) and source.get("name"):
            rows.append(("source", str(source["name"])))
    return {"records": records, "rows": rows}
