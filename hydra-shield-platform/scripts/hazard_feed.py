#!/usr/bin/env python3
"""Talaix hazard feed — read-only fetch of the public risk snapshot.

Used by the marketing copilot's hazard-driven commands. READ-ONLY: this
module performs GET requests against Talaix's own public API and
nothing else. No sending, no scraping, no third-party calls.

Offline behaviour: when the snapshot cannot be fetched (no network, API
down), callers get an honest unavailable marker — never fabricated hazard
data.
"""

from __future__ import annotations

import json
import urllib.request
from typing import Any, Dict, Optional

SNAPSHOT_URL = "https://talaix.com/api/risk-snapshot"
_TIMEOUT = 20.0
_UA = "hydrashield-marketing-copilot/1.0 (+https://talaix.com)"


def fetch_risk_snapshot(url: str = SNAPSHOT_URL) -> Optional[Dict[str, Any]]:
    """GET the public risk snapshot. Returns the parsed payload or None on
    any failure (caller reports honest unavailability)."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:  # noqa: BLE001 — network/parse failure → None
        return None


def snapshot_entries(snapshot: Optional[Dict[str, Any]]) -> list:
    """The snapshot's current entries (real, computed by the platform), or
    an empty list."""
    if not snapshot or snapshot.get("status") != "ok":
        return []
    entries = snapshot.get("entries") or []
    return entries if isinstance(entries, list) else []
