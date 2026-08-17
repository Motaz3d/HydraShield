"""
/api/v2 losses blueprint — Loss Data Registry (additive; does not change
any existing endpoint).

Exposes:

- ``GET /api/v2/losses``         — the loss summary (observed / estimated /
  modelled / projected strictly separated; observed unavailable — no
  documented loss figures in integrated sources)
- ``GET /api/v2/losses/sources`` — the registry's candidate source records
  (EM-DAT, DesInventar, World Bank/GFDRR, NOAA, Munich Re, Swiss Re) with
  access and licence conditions

The blueprint is deliberately NOT registered here — the lead registers it
in ``src/dashboard/api.py``.

Honesty contract: no loss figures are served anywhere — the registry holds
candidate sources only; every block says so explicitly.
"""

from __future__ import annotations

from flask import Blueprint, jsonify

from .api_v2 import _err, _rate

losses_bp = Blueprint("losses", __name__, url_prefix="/api/v2")

_RATE_MAX = 20
_RATE_WINDOW = 60.0


@losses_bp.get("/losses")
def losses():
    """Loss summary: /api/v2/losses

    Observed losses unavailable — no documented loss figures in integrated
    sources; estimated / modelled / projected each not_available. The
    registry metadata and the strict-separation note are included.
    """
    if not _rate("v2losses", _RATE_MAX, _RATE_WINDOW):
        return _err("Rate limit exceeded", 429)

    from .losses import loss_summary

    payload = loss_summary()
    if "error" in payload:
        return _err(payload["error"], 500)
    return jsonify(payload)


@losses_bp.get("/losses/sources")
def losses_sources():
    """Candidate loss-data sources: /api/v2/losses/sources

    The registry's source records (candidates — none integrated) with
    provider, official URL, access mode, licence note, coverage and status.
    """
    if not _rate("v2lossessources", _RATE_MAX, _RATE_WINDOW):
        return _err("Rate limit exceeded", 429)

    from .losses import load_loss_registry

    registry = load_loss_registry()
    sources = registry.get("sources") or []
    return jsonify({
        "sources": sources,
        "source_count": len(sources),
        "registry": {
            "registry_id": registry.get("registry_id"),
            "version": registry.get("version"),
            "config": "config/loss_registry.json",
        },
        "note": "All listed sources are candidates — none is integrated and "
                "no loss figures are served. Access and licence conditions "
                "are stated per source.",
    })
