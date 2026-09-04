"""
/api/v2/report-builder — Visual Report Builder API.

Registered from ``src/dashboard.api.py::create_app()``.

Endpoints:
    POST /draft    Build a deterministic sectioned draft from engine data (registered+, 6/min)
    POST /polish   Polish one section's prose via the AI gateway (registered+, 6/min)
    POST /pdf      Export the edited sections as an honest PDF (registered+, 6/min)
"""

from __future__ import annotations

from typing import Any, Dict

from flask import Blueprint, Response, jsonify, request

report_builder = Blueprint("report_builder", __name__, url_prefix="/api/v2/report-builder")


def _err(message: str, status: int, **extra):
    payload = {"error": message, "status": status}
    payload.update(extra)
    return jsonify(payload), status


def _rate(key: str, max_requests: int, window: float) -> bool:
    from ..dashboard.api import _client_key, _rate_limiter  # lazy: avoid circulars

    return _rate_limiter.allow(f"{key}:{_client_key()}", max_requests, window)


def _registered_gate(func):
    """Require the 'registered' role; lazy import avoids dashboard load."""
    from ..dashboard.auth_api import require_role

    return require_role("registered")(func)


# -----------------------------------------------------------------------------
# Draft builder
# -----------------------------------------------------------------------------


@report_builder.post("/draft")
@_registered_gate
def create_draft():
    """POST /api/v2/report-builder/draft — build a deterministic draft."""
    if not _rate("v2reportbuilder_draft", 6, 60.0):
        return _err("Rate limit exceeded", 429)

    from .report_builder import REPORT_KINDS, build_draft

    data = request.get_json(silent=True) or {}
    kind = (data.get("kind") or "").strip().lower()
    params = data.get("params") or {}

    if kind not in REPORT_KINDS:
        return _err(
            f"kind must be one of: {', '.join(sorted(REPORT_KINDS))}",
            400,
            allowed_kinds=sorted(REPORT_KINDS),
        )

    try:
        draft = build_draft(kind, params)
    except ValueError as exc:
        return _err(str(exc), 400)
    except Exception as exc:
        return _err(f"Draft generation failed: {exc}", 502)

    return jsonify({"draft": draft})


# -----------------------------------------------------------------------------
# AI polish
# -----------------------------------------------------------------------------


@report_builder.post("/polish")
@_registered_gate
def polish_section():
    """POST /api/v2/report-builder/polish — polish one section's prose via AI."""
    if not _rate("v2reportbuilder_polish", 6, 60.0):
        return _err("Rate limit exceeded", 429)

    from ..ai import gateway

    if not gateway.configured():
        return _err("AI polish is not configured", 503)

    data = request.get_json(silent=True) or {}
    heading = str(data.get("heading") or "").strip()
    text = str(data.get("text") or "").strip()

    if not text:
        return _err("text is required", 400)
    if len(text) > 5000:
        return _err("text exceeds 5000 characters", 400)

    user_prompt = text
    if heading:
        user_prompt = f"Section heading: {heading}\n\n{text}"

    try:
        polished = gateway.complete(
            "polish",
            user_prompt,
            system_prompt=gateway.POLISH_SYSTEM_PROMPT,
            max_tokens=800,
            timeout=30,
        )
    except gateway.AIUnavailable as exc:
        return _err(f"AI polish unavailable: {exc}", 503)
    except Exception as exc:
        return _err(f"AI polish failed: {exc}", 502)

    return jsonify({"text": polished})


# -----------------------------------------------------------------------------
# PDF export
# -----------------------------------------------------------------------------


def _safe_title(raw: Any) -> str:
    title = str(raw or "").strip()
    if not title:
        return "interactive_report"
    return title[:200]


@report_builder.post("/pdf")
@_registered_gate
def export_pdf():
    """POST /api/v2/report-builder/pdf — export edited sections as PDF."""
    if not _rate("v2reportbuilder_pdf", 6, 60.0):
        return _err("Rate limit exceeded", 429)

    from .report_builder import prepare_sections
    from ..dashboard.report_builder_pdf import build_custom_pdf

    data = request.get_json(silent=True) or {}
    title = _safe_title(data.get("title"))
    sections = data.get("sections")
    if not isinstance(sections, list):
        return _err("sections must be a list", 400)

    try:
        cleaned, edited_count = prepare_sections(sections)
    except ValueError as exc:
        return _err(str(exc), 400)

    ai_polished_count = sum(1 for s in cleaned if s.get("ai_polished"))

    meta = {
        "draft_id": str(data.get("draft_id") or ""),
        "generated_at": str(data.get("generated_at") or ""),
        "kind": str(data.get("kind") or ""),
        "engine_version": str(data.get("engine_version") or ""),
        "edited_count": edited_count,
        "ai_polished_count": ai_polished_count,
        "honesty_note": str(data.get("honesty_note") or ""),
        "disclaimer": str(data.get("disclaimer") or ""),
        "authenticity": data.get("authenticity") or {},
    }

    # Optional site coordinates: enable the site-context image in the PDF.
    try:
        lat = float(data.get("lat"))
        lon = float(data.get("lon"))
        if -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0:
            meta["lat"], meta["lon"] = lat, lon
    except (TypeError, ValueError):
        pass  # no coordinates — the PDF declares the image unavailable

    try:
        pdf = build_custom_pdf(title, cleaned, meta)
    except RuntimeError as exc:
        return _err(f"PDF generation unavailable: {exc}", 503)
    except Exception as exc:
        return _err(f"PDF generation failed: {exc}", 502)

    from ..dashboard.auth_api import record_user_report

    record_user_report(
        meta["kind"] or "custom", "multi", meta.get("lat"), meta.get("lon"),
        {"title": title, "draft_id": meta["draft_id"]},
        {"edited_count": edited_count, "ai_polished_count": ai_polished_count},
    )

    safe = "".join(c if c.isalnum() else "_" for c in title)[:40]
    return Response(
        pdf,
        mimetype="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="talaix_builder_{safe}.pdf"',
            "Cache-Control": "no-store",
        },
    )
