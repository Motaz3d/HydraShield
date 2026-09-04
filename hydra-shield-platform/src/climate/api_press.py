"""
/api/v2/press — Talaix Press evidence-pack API.

Registered from ``src/dashboard.api.py::create_app()``.

Endpoints:
    GET  /pack?lat=&lon=&name=&lang=      Structured evidence pack (JSON)
    GET  /pack.pdf?lat=&lon=&name=&lang=  Evidence pack as PDF
    GET  /figure/<kind>?lat=&lon=         PNG figure (climate, ndvi, site)
    GET  /sources                         Curated press-watch registry

English packs are public; all other supported languages are subscriber-gated.
"""

from __future__ import annotations

from typing import Optional, Tuple

from flask import Blueprint, Response, jsonify, request

press = Blueprint("press", __name__, url_prefix="/api/v2/press")

SUPPORTED_LANGS = {"en", "fr", "de"}
DEFAULT_LANG = "en"


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


def _require_subscriber_for_language(lang: str):
    """Return a 403 response when a non-English pack is requested by a non-subscriber."""
    if lang == DEFAULT_LANG:
        return None
    from ..dashboard.auth_api import current_user, require_role

    user = current_user()
    if user is None:
        from ..dashboard.auth_api import _unauthorized

        return _unauthorized()
    return require_role("subscriber")(lambda: None)()


@press.get("/pack")
def pack():
    """GET /api/v2/press/pack — structured evidence pack."""
    if not _rate("v2press_pack", 30, 60.0):
        return _err("Rate limit exceeded", 429)

    lat, lon, err = _parse_latlon(request.args)
    if err:
        return _err(err, 400)

    lang = (request.args.get("lang") or DEFAULT_LANG).strip().lower()
    if lang not in SUPPORTED_LANGS:
        return _err(f"Unsupported language '{lang}'", 400)

    gate = _require_subscriber_for_language(lang)
    if gate is not None:
        return gate

    name = (request.args.get("name") or "").strip() or None

    from .press import build_press_pack

    payload = build_press_pack(lat, lon, name=name, lang=lang)
    if not payload.get("ok"):
        return _err(payload.get("error", "Pack generation failed"), 502)
    return jsonify(payload)


@press.get("/pack.pdf")
def pack_pdf():
    """GET /api/v2/press/pack.pdf — evidence pack as PDF."""
    if not _rate("v2press_pack_pdf", 10, 60.0):
        return _err("Rate limit exceeded", 429)

    lat, lon, err = _parse_latlon(request.args)
    if err:
        return _err(err, 400)

    lang = (request.args.get("lang") or DEFAULT_LANG).strip().lower()
    if lang not in SUPPORTED_LANGS:
        return _err(f"Unsupported language '{lang}'", 400)

    gate = _require_subscriber_for_language(lang)
    if gate is not None:
        return gate

    name = (request.args.get("name") or "").strip() or None

    from ..dashboard.press_pdf import build_press_pdf
    from .press import build_press_pack

    payload = build_press_pack(lat, lon, name=name, lang=lang)
    if not payload.get("ok"):
        return _err(payload.get("error", "Pack generation failed"), 502)

    try:
        pdf = build_press_pdf(payload)
    except RuntimeError as exc:
        return _err(f"PDF generation unavailable: {exc}", 503)
    except Exception as exc:
        return _err(f"PDF generation failed: {exc}", 502)

    safe = "".join(c if c.isalnum() else "_" for c in (name or f"{lat}_{lon}"))[:40]
    return Response(
        pdf,
        mimetype="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="talaix_press_{safe}.pdf"',
            "Cache-Control": "no-store",
        },
    )


@press.get("/figure/<kind>")
def figure(kind: str):
    """GET /api/v2/press/figure/<kind>?lat=&lon= — PNG figure."""
    if kind not in {"climate", "ndvi", "site"}:
        return _err("Unknown figure kind; use climate, ndvi or site", 404)

    if not _rate(f"v2press_figure_{kind}", 60, 60.0):
        return _err("Rate limit exceeded", 429)

    lat, lon, err = _parse_latlon(request.args)
    if err:
        return _err(err, 400)

    png: Optional[bytes] = None

    if kind == "climate":
        from ..dashboard.press_charts import climate_series_png

        png = climate_series_png(lat, lon)
    elif kind == "ndvi":
        from ..dashboard.press_charts import build_ndvi_png
        from ..dashboard.real_data import fetch_satellite_data

        satellite = fetch_satellite_data(lat, lon)
        grid = satellite.get("ndvi_grid") if isinstance(satellite, dict) else None
        png = build_ndvi_png(grid)
    elif kind == "site":
        from ..dashboard.site_image import build_site_context_png

        png = build_site_context_png(lat, lon)

    if png is None:
        return _err("Figure unavailable for this location", 503)
    return Response(png, mimetype="image/png", headers={"Cache-Control": "max-age=3600"})


@press.get("/sources")
def sources():
    """GET /api/v2/press/sources — curated press-watch registry."""
    if not _rate("v2press_sources", 60, 60.0):
        return _err("Rate limit exceeded", 429)

    from .press import load_press_watch

    return jsonify({"sources": load_press_watch()})
