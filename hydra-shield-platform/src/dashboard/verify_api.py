"""Public TX seal verification API.

Registered from ``src/dashboard/api.py::create_app()`` with url_prefix ``/api/v2``.

Two modes:

* Registry lookup: ``GET /api/v2/verify/<code>`` checks the platform seal
  registry for documents issued by the product engines.
* Stateless recomputation: ``POST /api/v2/verify`` recomputes the seal for an
  arbitrary JSON payload (used for TX analysis JSON envelopes).
"""

from __future__ import annotations

from typing import Any, Dict

from flask import Blueprint, jsonify, request

verify_bp = Blueprint("verify", __name__, url_prefix="/api/v2")


def _rate(key: str, max_requests: int, window: float) -> bool:
    from .api import _client_key, _rate_limiter  # lazy: avoid circulars

    return _rate_limiter.allow(f"{key}:{_client_key()}", max_requests, window)


@verify_bp.get("/verify/<code>")
def verify_code(code: str):
    """GET /api/v2/verify/<code> — public registry lookup."""
    if not _rate("v2verify_get", 60, 60.0):
        return jsonify({"valid": False, "error": "Rate limit exceeded"}), 429

    from ..climate.tx_seal import verify_seal

    record = verify_seal(code)
    if record is None:
        return jsonify({
            "valid": False,
            "hint": "Unknown code. JSON analysis results verify via POST /api/v2/verify with the original payload.",
        }), 200
    return jsonify(record), 200


@verify_bp.post("/verify")
def verify_payload():
    """POST /api/v2/verify — stateless recomputation for any JSON payload."""
    if not _rate("v2verify_post", 60, 60.0):
        return jsonify({"valid": False, "error": "Rate limit exceeded"}), 429

    from ..climate.tx_seal import check_seal, is_seal_format, normalize_code

    data: Dict[str, Any] = request.get_json(silent=True) or {}
    payload = data.get("payload")
    code = data.get("code")

    if payload is None or code is None:
        return jsonify({"valid": False, "error": "Missing 'payload' or 'code' field"}), 400

    if not is_seal_format(code):
        return jsonify({"valid": False, "error": "Malformed seal code"}), 400

    normalized = normalize_code(code)
    return jsonify({
        "valid": check_seal(payload, code),
        "code": normalized,
    }), 200
