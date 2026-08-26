"""
/api/v2/sector-screen — Sector Exposure Screening API.

Public endpoint for the sector exposure screen:
sector sensitivity x location hazards x physical trajectory x official crime
statistics where available.

Honesty contract: returns screening evidence only. No investment advice, no
valuation, no loss prediction.
"""

from __future__ import annotations

from typing import Optional, Tuple

from flask import Blueprint, jsonify, request

sector_screen_bp = Blueprint("sector_screen", __name__, url_prefix="/api/v2/sector-screen")


def _err(message: str, status: int, **extra):
    payload = {"error": message, "status": status}
    payload.update(extra)
    return jsonify(payload), status


def _rate(key: str, max_requests: int, window: float) -> bool:
    from ..dashboard.api import _client_key, _rate_limiter  # lazy: avoid circulars

    return _rate_limiter.allow(f"{key}:{_client_key()}", max_requests, window)


def _parse_latlon(args) -> Tuple[Optional[float], Optional[float], Optional[str]]:
    try:
        lat = float(args.get("lat"))
        lon = float(args.get("lon"))
    except (TypeError, ValueError):
        return None, None, "lat and lon must be numbers"
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return None, None, "lat/lon out of range"
    return lat, lon, None


@sector_screen_bp.get("/")
def screen():
    """GET /api/v2/sector-screen/?lat=...&lon=...&name=...&sectors=a,b,c"""
    if not _rate("v2sector_screen", 20, 60.0):
        return _err("Rate limit exceeded", 429)

    lat, lon, err = _parse_latlon(request.args)
    if err:
        return _err(err, 400)

    from .sector_screen import _sector_ids, build_sector_screen

    valid_ids = _sector_ids()
    requested_sectors: Optional[list] = None
    sectors_param = (request.args.get("sectors") or "").strip()
    if sectors_param:
        requested_sectors = [s.strip() for s in sectors_param.split(",") if s.strip()]
        unknown = [s for s in requested_sectors if s not in valid_ids]
        if unknown:
            return _err(
                f"Unknown sector id(s): {', '.join(unknown)}",
                400,
                valid_sectors=valid_ids,
            )

    name = (request.args.get("name") or "").strip() or None

    try:
        payload = build_sector_screen(
            lat, lon, sectors=requested_sectors, name=name
        )
    except ValueError as exc:
        return _err(str(exc), 400)
    except Exception as exc:
        return _err(f"Screen generation failed: {exc}", 502)

    return jsonify(payload)
