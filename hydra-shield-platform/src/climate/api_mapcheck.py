"""
/api/v2/mapcheck — Map Check public endpoint.

Cross-checks open map data (OpenStreetMap green features) against satellite
observation (Sentinel-2 NDVI + ESA WorldCover) and reports discrepancies with
rule-based possible causes.
"""

from __future__ import annotations

from typing import Optional, Tuple

from flask import Blueprint, jsonify, request

from ..dashboard.api import _client_key, _error, _rate_limiter

mapcheck = Blueprint("mapcheck", __name__, url_prefix="/api/v2/mapcheck")


def _parse_latlon(args) -> Tuple[Optional[float], Optional[float], Optional[str]]:
    """Parse & validate lat/lon from request args. Returns (lat, lon, error)."""
    try:
        lat = float(args.get("lat"))
        lon = float(args.get("lon"))
    except (TypeError, ValueError):
        return None, None, "lat and lon must be numbers"
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return None, None, "lat/lon out of range"
    return lat, lon, None


@mapcheck.route("/", methods=["GET"])
def mapcheck_endpoint():
    """GET /api/v2/mapcheck/?lat=...&lon=...&radius_m=300"""
    if not _rate_limiter.allow(f"mapcheck:{_client_key()}", 10, 60.0):
        return _error("Rate limit exceeded (10 requests/minute)", 429)

    lat, lon, err = _parse_latlon(request.args)
    if err:
        return _error(err, 400)

    try:
        radius = int(request.args.get("radius_m", "300"))
    except (TypeError, ValueError):
        return _error("radius_m must be an integer", 400)
    if not (50 <= radius <= 2000):
        return _error("radius_m must be between 50 and 2000", 400)

    from .mapcheck import check_map_vs_satellite

    try:
        result = check_map_vs_satellite(lat, lon, radius_m=radius)
    except ValueError as exc:
        return _error(str(exc), 400)
    except Exception as exc:
        return _error(f"Map Check engine failed: {exc}", 502)

    return jsonify(result)
