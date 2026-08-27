"""
Human-readable HTML renderings of the public registries.

The JSON contracts of ``GET /api/sources`` and ``GET /api/v2/hazards`` are
the machine-readable product — SDKs, the map and the QGIS plugin consume
them. A human following the same link from the site footer used to receive
a raw JSON document, which reads as "broken" in a browser. These renderers
give the same two URLs a professional human face via HTTP content
negotiation: browsers (``Accept: text/html``) get the pages built here,
API clients keep the JSON contract byte-for-byte.

Every value is escaped; nothing is fabricated — the pages render exactly
the payload the JSON form carries, with honest availability states.
"""

from __future__ import annotations

import html
from typing import Dict, List

from flask import request


def prefers_html() -> bool:
    """True when the client prefers HTML over JSON — a browser following a
    link. API clients (no Accept header, ``*/*``, or an explicit
    ``application/json``) keep the JSON contract; ``?format=json`` is an
    explicit escape hatch for humans inspecting the JSON in a browser."""
    if (request.args.get("format") or "").lower() == "json":
        return False
    return (request.accept_mimetypes["text/html"]
            > request.accept_mimetypes["application/json"])

_BRAND = {
    "primary": "#0EA5E9",
    "primary_dark": "#0369A1",
    "secondary": "#10B981",
    "accent": "#F59E0B",
    "danger": "#EF4444",
    "dark": "#0F172A",
    "light": "#F8FAFC",
    "text": "#1E293B",
    "muted": "#64748B",
    "border": "#E2E8F0",
}

_STATUS_COLORS = {
    "integrated": ("#10B981", "INTEGRATED"),
    "candidate": ("#F59E0B", "CANDIDATE"),
    "rejected": ("#EF4444", "REJECTED"),
}


def _esc(value) -> str:
    return html.escape("" if value is None else str(value))


def _chip(color: str, label: str) -> str:
    return (
        f'<span style="display:inline-block;padding:2px 10px;border-radius:999px;'
        f'font-size:11px;font-weight:700;letter-spacing:.04em;color:#fff;'
        f'background:{color};">{_esc(label)}</span>'
    )


def _availability_chip(available: bool) -> str:
    return _chip("#10B981", "AVAILABLE") if available else _chip("#F59E0B", "UNAVAILABLE")


def _session_user():
    """The signed-in user for this request, or None for guests.

    Lazy import keeps the renderer import-light; any failure degrades to the
    guest view (CTA shown) rather than breaking the page.
    """
    try:
        from .auth_api import current_user

        return current_user()
    except Exception:
        return None


def _cta_block() -> str:
    """Session-aware call-to-action.

    Design rule: the create-account / subscribe invitation is shown ONLY to
    guests. A signed-in visitor never sees a registration or subscription
    prompt — they get a quiet link to the account they already have.
    """
    user = _session_user()
    if user is not None:
        name = user.get("display_name") or user.get("email") or "your account"
        return f"""  <div class="cta cta-account">
    <h2>Signed in as {_esc(name)}</h2>
    <p>Your API keys, webhook subscriptions, monitoring alerts and
       subscription already live in your account.</p>
    <a class="btn" href="/account.html">Open your account</a>
  </div>"""
    return """  <div class="cta">
    <h2>Use this data in your own systems</h2>
    <p>Create a free account and subscribe to receive an API key, webhook
       subscriptions and monitoring alerts. Subscriptions are recorded on the
       platform — no payment data is collected.</p>
    <a class="btn" href="/account.html">Create an account / Subscribe</a>
  </div>"""


def _page(title: str, lead: str, body: str, json_url: str) -> str:
    """The shared branded shell: header, lead, content, subscribe CTA, footer."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{_esc(title)} — Talaix</title>
<meta name="description" content="{_esc(lead)}">
<style>
  :root {{ color-scheme: light; }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: Inter, -apple-system, "Segoe UI", Roboto, sans-serif;
         background: {_BRAND["light"]}; color: {_BRAND["text"]}; line-height: 1.55; }}
  .topbar {{ background: {_BRAND["dark"]}; padding: 14px 0; }}
  .container {{ max-width: 1080px; margin: 0 auto; padding: 0 20px; }}
  .brand {{ color: #fff; text-decoration: none; font-weight: 700; font-size: 20px;
            font-family: "Space Grotesk", Inter, sans-serif; letter-spacing: 0.28em;
            text-transform: uppercase; }}
  .brand span {{ color: #47B3A8; }}
  .topnav {{ float: right; }}
  .topnav a {{ color: #CBD5E1; text-decoration: none; margin-left: 18px; font-size: 14px; }}
  .topnav a:hover {{ color: #fff; }}
  main {{ padding: 42px 0 30px; }}
  h1 {{ font-family: "Space Grotesk", Inter, sans-serif; font-size: 32px;
       color: {_BRAND["dark"]}; margin-bottom: 10px; }}
  .lead {{ color: {_BRAND["muted"]}; max-width: 820px; margin-bottom: 8px; }}
  .jsonlink {{ font-size: 13px; color: {_BRAND["muted"]}; margin-bottom: 26px; }}
  .jsonlink code {{ background: #E2E8F0; padding: 1px 6px; border-radius: 6px; }}
  .card {{ background: #fff; border: 1px solid {_BRAND["border"]}; border-radius: 14px;
           padding: 20px 22px; margin-bottom: 16px; box-shadow: 0 2px 8px rgba(0,0,0,.05); }}
  .card h2 {{ font-size: 18px; color: {_BRAND["dark"]}; margin-bottom: 4px; }}
  .card h3 {{ font-size: 14px; color: {_BRAND["dark"]}; margin: 12px 0 4px; }}
  .meta {{ color: {_BRAND["muted"]}; font-size: 13px; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 8px; font-size: 14px; }}
  th, td {{ text-align: left; padding: 7px 10px; border-bottom: 1px solid {_BRAND["border"]};
            vertical-align: top; }}
  th {{ color: {_BRAND["muted"]}; font-size: 12px; text-transform: uppercase;
       letter-spacing: .04em; }}
  a {{ color: {_BRAND["primary_dark"]}; }}
  .cta {{ background: linear-gradient(135deg, {_BRAND["primary"]} 0%, {_BRAND["secondary"]} 100%);
          border-radius: 14px; color: #fff; padding: 26px 28px; margin: 28px 0; }}
  .cta.cta-account {{ background: {_BRAND["dark"]}; }}
  .cta h2 {{ font-size: 20px; margin-bottom: 6px; }}
  .cta p {{ font-size: 14px; opacity: .95; max-width: 720px; }}
  .cta a.btn {{ display: inline-block; margin-top: 12px; background: #fff;
                color: {_BRAND["primary_dark"]}; font-weight: 700; text-decoration: none;
                padding: 10px 22px; border-radius: 10px; font-size: 14px; }}
  footer {{ border-top: 1px solid {_BRAND["border"]}; padding: 22px 0 40px;
            color: {_BRAND["muted"]}; font-size: 13px; }}
  footer a {{ color: {_BRAND["primary_dark"]}; text-decoration: none; margin-right: 16px; }}
</style>
</head>
<body>
<div class="topbar"><div class="container">
  <span class="topnav">
    <a href="/map.html">Map</a>
    <a href="/sources">Data sources</a>
    <a href="/account.html">Account</a>
  </span>
  <a class="brand" href="/">TALAIX<span>•</span></a>
</div></div>
<main><div class="container">
  <h1>{_esc(title)}</h1>
  <p class="lead">{_esc(lead)}</p>
  <p class="jsonlink">Machine-readable form: <a href="{_esc(json_url)}"><code>{_esc(json_url)}</code></a>
     — send <code>Accept: application/json</code> (or append <code>?format=json</code>)
     for the JSON contract consumed by the SDKs and the QGIS plugin.</p>
  {body}
  {_cta_block()}
</div></main>
<footer><div class="container">
  <a href="/">Home</a><a href="/technology.html">Technology</a>
  <a href="/privacy.html">Privacy</a><a href="/contact.html">Contact</a>
  <a href="mailto:info@talaix.com">info@talaix.com</a>
  <p style="margin-top:10px;">Talaix — real-data environmental risk intelligence.
     Nothing is claimed as used unless it is integrated.</p>
</div></footer>
</body>
</html>"""


def render_sources_page(registry: Dict) -> str:
    """HTML rendering of the data-source audit registry (/api/sources)."""
    sources: List[Dict] = registry.get("sources") or []
    counts = {"integrated": 0, "candidate": 0, "rejected": 0}
    for s in sources:
        key = str(s.get("status") or "").lower()
        if key in counts:
            counts[key] += 1

    cards = []
    for s in sources:
        status = str(s.get("status") or "").lower()
        color, label = _STATUS_COLORS.get(status, ("#64748B", status.upper() or "UNKNOWN"))
        rows = []
        for label_text, key in (
            ("Provider", "provider"), ("Purpose", "purpose"),
            ("Coverage", "coverage"), ("Resolution", "resolution"),
            ("Update frequency", "update_frequency"), ("Latency", "latency"),
            ("Access", "access"), ("License", "license"),
            ("Limitations", "limitations"),
        ):
            value = s.get(key)
            if value:
                rows.append(f"<tr><th>{_esc(label_text)}</th><td>{_esc(value)}</td></tr>")
        if s.get("url"):
            rows.append(
                f'<tr><th>URL</th><td><a href="{_esc(s["url"])}" rel="noopener" '
                f'target="_blank">{_esc(s["url"])}</a></td></tr>')
        if status == "integrated" and s.get("integrated_in"):
            rows.append(
                f"<tr><th>Integrated in</th><td>{_esc(s['integrated_in'])}</td></tr>")
        if status == "rejected" and s.get("rejection_reason"):
            rows.append(
                f"<tr><th>Rejection reason</th><td>{_esc(s['rejection_reason'])}</td></tr>")
        cards.append(
            f'<div class="card"><h2>{_esc(s.get("name") or "Unnamed source")} '
            f'{_chip(color, label)}</h2><table>{"".join(rows)}</table></div>')

    audit_bits = []
    if registry.get("audit_date"):
        audit_bits.append(f"Audit date: {_esc(registry['audit_date'])}")
    summary = (
        f"{len(sources)} evaluated sources — {counts['integrated']} integrated, "
        f"{counts['candidate']} candidates, {counts['rejected']} rejected."
        + (f" {' · '.join(audit_bits)}." if audit_bits else ""))

    body = f'<p class="meta" style="margin-bottom:18px;">{summary}</p>{"".join(cards)}'
    return _page(
        "Data-source registry",
        "Every data source Talaix has evaluated — integrated, candidate or "
        "rejected, with provider, resolution, license and limitations. Nothing is "
        "claimed as used unless it is integrated.",
        body,
        "/api/sources",
    )


def render_hazards_page(payload: Dict) -> str:
    """HTML rendering of the hazard registry (/api/v2/hazards)."""
    hazards: List[Dict] = payload.get("hazards") or []
    cards = []
    for h in hazards:
        analysis = h.get("analysis") or {}
        events = h.get("events") or {}
        rows = []
        if h.get("tagline"):
            rows.append(f"<tr><th>Scope</th><td>{_esc(h['tagline'])}</td></tr>")
        rows.append(
            f"<tr><th>Analysis</th><td>{_availability_chip(bool(analysis.get('available')))}"
            + (f' <span class="meta">{_esc(analysis.get("reason"))}</span>'
               if analysis.get("reason") else "")
            + "</td></tr>")
        rows.append(
            f"<tr><th>Observed events</th><td>{_availability_chip(bool(events.get('available')))}"
            + (f' <span class="meta">{_esc(events.get("reason"))}</span>'
               if events.get("reason") else "")
            + "</td></tr>")

        coverage = h.get("temporal_coverage") or {}
        if coverage:
            items = "".join(
                f"<tr><th>{_esc(name)}</th><td>{_esc(span.get('start'))} → {_esc(span.get('end'))}</td></tr>"
                for name, span in coverage.items() if isinstance(span, dict))
            if items:
                rows.append(
                    f'<tr><th>Temporal coverage</th><td>'
                    f'<table style="margin-top:0;">{items}</table></td></tr>')

        srcs = h.get("sources") or []
        if srcs:
            links = "<br>".join(
                f'<a href="{_esc(s.get("url"))}" rel="noopener" target="_blank">'
                f'{_esc(s.get("name"))}</a>' for s in srcs if s.get("name"))
            if links:
                rows.append(f"<tr><th>Sources</th><td>{links}</td></tr>")

        enabled = bool(h.get("enabled"))
        cards.append(
            f'<div class="card"><h2>{_esc(h.get("name") or h.get("id") or "Hazard")} '
            f'{_chip("#10B981", "ENABLED") if enabled else _chip("#64748B", "DISABLED")}'
            f'</h2><table>{"".join(rows)}</table>'
            f'<p class="meta" style="margin-top:10px;">Detail JSON: '
            f'<a href="/api/v2/hazards/{_esc(h.get("id"))}">'
            f'<code>/api/v2/hazards/{_esc(h.get("id"))}</code></a></p></div>')

    body = (
        f'<p class="meta" style="margin-bottom:18px;">{len(hazards)} registered '
        f'hazard(s). A hazard is registered only when wired to at least one real, '
        f'documented data source — no placeholders.</p>'
        + "".join(cards))
    return _page(
        "Hazard registry",
        "The hazards Talaix analyses. Each entry carries its availability, "
        "temporal coverage per dataset and the real sources behind it — screening "
        "indicators are labelled as such.",
        body,
        "/api/v2/hazards",
    )
