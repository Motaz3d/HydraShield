"""
/api/v2/briefs — Talaix Knowledge Arm API.

Registered from ``src/dashboard.api.py::create_app()``.

Endpoints:
    GET  /                    List published briefs (60/min)
    GET  /<brief_id>          One published brief (60/min)
"""

from __future__ import annotations

from typing import Any, Dict

from flask import Blueprint, jsonify, request

briefs = Blueprint("briefs", __name__, url_prefix="/api/v2/briefs")


_BRIEF_KINDS = {"framework_explainer", "evidence_brief"}


def _err(message: str, status: int, **extra):
    payload = {"error": message, "status": status}
    payload.update(extra)
    return jsonify(payload), status


def _rate(key: str, max_requests: int, window: float) -> bool:
    from ..dashboard.api import _client_key, _rate_limiter  # lazy: avoid circulars

    return _rate_limiter.allow(f"{key}:{_client_key()}", max_requests, window)


# -----------------------------------------------------------------------------
# Public catalogue
# -----------------------------------------------------------------------------


@briefs.get("/")
def list_briefs():
    """GET /api/v2/briefs — public list of published briefs."""
    if not _rate("v2briefs_list", 60, 60.0):
        return _err("Rate limit exceeded", 429)

    from .briefs import load_briefs, list_briefs as _list_briefs

    kind = request.args.get("kind", "").strip() or None
    if kind is not None and kind not in _BRIEF_KINDS:
        return jsonify({"briefs": [], "note": "Unknown kind; use framework_explainer or evidence_brief."})

    config = load_briefs()
    return jsonify({
        "briefs": _list_briefs(kind=kind, config=config),
        "note": config.get("note"),
    })


@briefs.get("/<brief_id>")
def get_brief(brief_id: str):
    """GET /api/v2/briefs/<id> — one published brief, or honest 404."""
    if not _rate("v2briefs_detail", 60, 60.0):
        return _err("Rate limit exceeded", 429)

    from .briefs import get_brief as _get_brief

    brief = _get_brief(brief_id)
    if brief is None:
        return _err(f"Unknown brief '{brief_id}'", 404)
    return jsonify({"brief": brief})
