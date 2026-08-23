"""Talaix API client for the QGIS plugin.

Two layers, deliberately separated:

- **Pure functions** (no QGIS imports): URL building and response
  normalization from JSON dicts to plain Python records. These are unit
  tested outside QGIS.
- **Network layer** (QGIS-coupled): QgsNetworkAccessManager.blockingGet —
  so QGIS proxy/SSL/auth settings apply (official plugin guidance). Always
  called from worker threads (QgsTask / Processing), never the GUI thread.

Honesty contract: the API's own states are passed through untouched —
"unavailable" / "key_required" stay visible; nothing is filled in.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

BASE_URL = "https://talaix.com"
USER_AGENT = "hydrashield-qgis/0.1.0 (+https://talaix.com)"
TIMEOUT_MS = 30000


def hazards_url(base: str = BASE_URL) -> str:
    return f"{base}/api/v2/hazards"


def analyze_url(hazard: str, lat: float, lon: float,
                name: Optional[str] = None, base: str = BASE_URL) -> str:
    from urllib.parse import quote

    url = (f"{base}/api/v2/analyze?hazard={quote(hazard)}"
           f"&lat={lat:.5f}&lon={lon:.5f}")
    if name:
        url += f"&name={quote(name)}"
    return url


def normalize_hazard(descriptor: Dict[str, Any]) -> Dict[str, Any]:
    """One registry descriptor → a flat display record. Missing blocks are
    reported as unknown, never assumed."""
    analysis = descriptor.get("analysis") or {}
    events = descriptor.get("events") or {}
    sources = descriptor.get("sources") or []
    provenance = descriptor.get("provenance") or {}
    return {
        "id": descriptor.get("id", "unknown"),
        "name": descriptor.get("name", descriptor.get("id", "unknown")),
        "enabled": bool(descriptor.get("enabled", False)),
        "analysis_available": bool(analysis.get("available")),
        "analysis_reason": analysis.get("reason"),
        "events_available": bool(events.get("available")),
        "events_reason": events.get("reason"),
        "sources": [(s.get("name", ""), s.get("url", "")) for s in sources],
        "provenance_module": provenance.get("module", ""),
        "indicator_status": provenance.get("indicator_status", ""),
    }


def normalize_analysis(payload: Dict[str, Any]) -> Dict[str, Any]:
    """One /api/v2/analyze payload → a flat feature record + summary rows.

    The record carries the level and the honesty fields; summary rows are
    (key, value) pairs for the attribute table / dock details. No numbers
    are invented: absent values stay None.
    """
    level = payload.get("level") or {}
    location = payload.get("location") or {}
    record = {
        "hazard": payload.get("hazard", "unknown"),
        "status": payload.get("status", "unknown"),
        "summary": payload.get("summary"),
        "level_label": level.get("label"),
        "level_score": level.get("score"),
        "level_score_max": level.get("score_max"),
        "level_basis": level.get("basis"),
        "validated": level.get("validated"),
        "unavailable_reason": payload.get("unavailable_reason"),
        "lat": location.get("lat"),
        "lon": location.get("lon"),
        "name": location.get("name"),
    }
    rows: List[Tuple[str, str]] = []
    if record["summary"]:
        rows.append(("summary", str(record["summary"])))
    if record["level_label"]:
        rows.append(("level", str(record["level_label"])))
    if record["level_score"] is not None:
        rows.append(("score", f"{record['level_score']}"
                            f"/{record.get('level_score_max') or '?'}"))
    if record["level_basis"]:
        rows.append(("basis", str(record["level_basis"])))
    rows.append(("validated", str(record["validated"])))
    provenance = payload.get("provenance") or {}
    for comp, prov in sorted(provenance.items()):
        if isinstance(prov, dict) and prov.get("source"):
            rows.append((f"source:{comp}", str(prov["source"])))
    return {"record": record, "rows": rows}


# ---------------------------------------------------------------------------
# Network layer (QGIS-coupled — worker threads only)
# ---------------------------------------------------------------------------

def http_get_json(url: str, authcfg: str = "") -> Tuple[Optional[Dict[str, Any]],
                                                       Optional[str]]:
    """GET ``url`` and parse JSON. Returns (payload, None) or (None, error).

    Uses QgsNetworkAccessManager so QGIS proxy/SSL settings and — when
    given — the authcfg credential apply. Must be called from a worker
    thread (QgsTask/Processing), never the GUI thread.
    """
    from qgis.core import QgsNetworkAccessManager
    from qgis.PyQt.QtCore import QUrl
    from qgis.PyQt.QtNetwork import QNetworkRequest

    request = QNetworkRequest(QUrl(url))
    request.setRawHeader(b"User-Agent", USER_AGENT.encode("utf-8"))
    request.setRawHeader(b"Accept", b"application/json")
    nam = QgsNetworkAccessManager.instance()
    if authcfg:
        reply = nam.blockingGet(request, authcfg, True)
    else:
        reply = nam.blockingGet(request)
    error = reply.error()
    if error != 0:  # QNetworkReply.NoError == 0 (Qt5/Qt6-safe comparison)
        return None, f"HTTP request failed (code {error}): {reply.errorString()}"
    try:
        payload = json.loads(bytes(reply.content()).decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        return None, f"Invalid JSON from {url}: {exc}"
    if isinstance(payload, dict) and payload.get("error"):
        return None, str(payload["error"])
    return payload, None
