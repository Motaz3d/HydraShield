"""
Marketing CRM API — operator-facing outreach, scheduling and lead drill-down.

Mounted under ``/api/v2/admin/marketing``. Admin-only. Reads the marketing
workspace for lead records; all working state lives in the platform DB via
``MarketingStore`` (never writes to marketing/*.json).
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from flask import Blueprint, jsonify, request

from . import mailer
from .admin_intel import (
    _TARGET_SECTORS,
    _WORKSPACE,
    _lead_score,
    _overlay_ops,
    _records_ws,
    _segment_doc,
    _target_sector,
)
from .auth_api import require_role
from .marketing_store import OUTREACH_STATUSES, MarketingStore

marketing_crm_bp = Blueprint("marketing_crm", __name__, url_prefix="/api/v2")

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _all_leads() -> List[Dict]:
    """Merged workspace leads with working-state overlay."""
    return _overlay_ops(_records_ws("leads"))


def _lead_sector(lead: Dict) -> str:
    """The sector key used for grouping/filtering (alias-aware)."""
    return _target_sector(lead.get("segment") or "") or (lead.get("segment") or "")


def _leads_by_slug() -> Dict[str, Dict]:
    return {lead.get("_slug"): lead for lead in _all_leads() if lead.get("_slug")}


def _outreach_template_and_context(lead: Dict, data: Dict):
    """Choose the sector-specific template (or generic) and build the render
    context shared by immediate send and scheduled send."""
    sector = _target_sector(lead.get("segment") or "") or (lead.get("segment") or "")
    template = f"outreach_{sector}"
    if not os.path.isfile(os.path.join(mailer.TEMPLATES_DIR, f"{template}.txt")):
        template = "outreach_generic"

    context = {
        "contact_name": (data.get("contact_name") or "").strip(),
        "organization": lead.get("organization") or "",
        "country": lead.get("country") or "",
        "identified_problem": lead.get("identified_problem") or "",
        "relevant_capability": lead.get("relevant_capability") or "",
        "recommended_product": lead.get("recommended_product") or "",
        "custom_message": (data.get("custom_message") or "").strip(),
    }
    return template, context


@marketing_crm_bp.get("/admin/marketing/tree")
@require_role("admin")
def marketing_tree():
    """Lazy navigation: sector → country → the sector×country intersection
    (all targeted organisations, status as a per-lead field + filter).

    Every segment present in the lead base is a first-class sector — the
    platform targets all sectors, not only the six for-* pages."""
    segment = (request.args.get("segment") or "").strip()
    country = (request.args.get("country") or "").strip()
    status = (request.args.get("status") or "").strip()

    leads = [l for l in _all_leads() if not l.get("excluded")]

    def _lead_row(l: Dict) -> Dict:
        return {
            "slug": l.get("_slug"),
            "organization": l.get("organization"),
            "priority": l.get("priority"),
            "urgency": l.get("urgency"),
            "score": _lead_score(l),
            "outreach_status": l.get("outreach_status", "researched"),
            "recommended_product": l.get("recommended_product"),
            "next_action": l.get("next_action"),
            "last_contact": l.get("last_contact"),
            "website": l.get("website"),
            "decision_maker_role": l.get("decision_maker_role"),
        }

    if not segment:
        if country or status:
            return jsonify({"error": "segment is required", "status": 400}), 400
        labels = dict(_TARGET_SECTORS)
        counts: Dict[str, int] = {}
        for l in leads:
            key = _lead_sector(l)
            counts[key] = counts.get(key, 0) + 1
        sectors = [
            {"key": key,
             "label": labels.get(key, key.replace("_", " ").title()),
             "count": ct}
            for key, ct in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        ]
        return jsonify({"sectors": sectors})

    if not country:
        if status:
            return jsonify({"error": "country is required", "status": 400}), 400
        seg_leads = [l for l in leads if _lead_sector(l) == segment]
        countries = Counter((l.get("country") or "?") for l in seg_leads)
        return jsonify({
            "segment": segment,
            "countries": [
                {"country": cc, "count": ct}
                for cc, ct in sorted(countries.items(), key=lambda kv: -kv[1])
            ],
        })

    seg_leads = [
        l for l in leads
        if _lead_sector(l) == segment and (l.get("country") or "") == country
    ]
    status_counts = Counter(
        l.get("outreach_status", "researched") for l in seg_leads)
    if status:
        seg_leads = [
            l for l in seg_leads
            if (l.get("outreach_status", "researched") or "") == status
        ]
    resp = {
        "segment": segment,
        "country": country,
        "statuses": [
            {"status": s, "count": status_counts[s]}
            for s in OUTREACH_STATUSES if status_counts.get(s)
        ],
        "leads": [_lead_row(l) for l in seg_leads],
    }
    if status:
        resp["status"] = status
    return jsonify(resp)


@marketing_crm_bp.get("/admin/marketing/stats")
@require_role("admin")
def marketing_stats():
    """Visitor, subscription and activity statistics for the marketing
    dashboard. Aggregate counts only — analytics sessions are pseudonymous
    hashes, so no individual visitor is identifiable from this data."""
    from .analytics import AnalyticsStore
    from .cache import default_cache

    now = datetime.utcnow()
    day_start = now.strftime("%Y-%m-%d") + "T00:00:00"
    week_start = (now - timedelta(days=7)).isoformat() + "Z"
    month_start = (now - timedelta(days=30)).isoformat() + "Z"

    store = AnalyticsStore(default_cache().db_path)
    with store._connect() as conn:
        def _one(sql, params=()):
            return conn.execute(sql, params).fetchone()[0]

        visitors = {
            "today": _one(
                "SELECT COUNT(DISTINCT session_hash) FROM analytics_events"
                " WHERE ts >= ?", (day_start,)),
            "last_7_days": _one(
                "SELECT COUNT(DISTINCT session_hash) FROM analytics_events"
                " WHERE ts >= ?", (week_start,)),
            "last_30_days": _one(
                "SELECT COUNT(DISTINCT session_hash) FROM analytics_events"
                " WHERE ts >= ?", (month_start,)),
            "total_unique_sessions": _one(
                "SELECT COUNT(DISTINCT session_hash) FROM analytics_events"),
            "total_page_views": _one(
                "SELECT COUNT(*) FROM analytics_events WHERE event = 'page_view'"),
        }
        event_counts = dict(conn.execute(
            "SELECT event, COUNT(*) FROM analytics_events GROUP BY event"
        ).fetchall())
        activity = {
            # Sessions that did something beyond viewing a page (last 30 days).
            "active_sessions_30d": _one(
                "SELECT COUNT(DISTINCT session_hash) FROM analytics_events"
                " WHERE ts >= ? AND event != 'page_view'", (month_start,)),
            "analyses": event_counts.get("location_analyzed", 0),
            "cta_clicks": event_counts.get("cta_clicked", 0),
            "accounts_created": event_counts.get("account_created", 0),
            "subscription_events": event_counts.get("subscription_started", 0),
        }
        top_pages = conn.execute(
            "SELECT page, COUNT(*) AS c, COUNT(DISTINCT session_hash) AS s"
            " FROM analytics_events WHERE page IS NOT NULL"
            " GROUP BY page ORDER BY c DESC LIMIT 10"
        ).fetchall()
        daily = conn.execute(
            "SELECT substr(ts, 1, 10) AS d,"
            " COUNT(DISTINCT session_hash) AS s,"
            " SUM(CASE WHEN event = 'page_view' THEN 1 ELSE 0 END) AS pv"
            " FROM analytics_events WHERE ts >= ?"
            " GROUP BY d ORDER BY d", (month_start,)
        ).fetchall()
        top_referrers = conn.execute(
            "SELECT referrer, COUNT(*) AS c FROM analytics_events"
            " WHERE referrer IS NOT NULL"
            " GROUP BY referrer ORDER BY c DESC LIMIT 8"
        ).fetchall()
        devices = conn.execute(
            "SELECT device, COUNT(*) AS c FROM analytics_events"
            " WHERE device IS NOT NULL GROUP BY device ORDER BY c DESC"
        ).fetchall()
        languages = conn.execute(
            "SELECT language, COUNT(*) AS c FROM analytics_events"
            " WHERE language IS NOT NULL"
            " GROUP BY language ORDER BY c DESC LIMIT 8"
        ).fetchall()
        top_hazards = conn.execute(
            "SELECT hazard, COUNT(*) AS c FROM analytics_events"
            " WHERE hazard IS NOT NULL"
            " GROUP BY hazard ORDER BY c DESC LIMIT 8"
        ).fetchall()
        accounts = _one("SELECT COUNT(*) FROM users")
        verified = _one(
            "SELECT COUNT(*) FROM users WHERE email_verified_at IS NOT NULL")
        active_subs = _one(
            "SELECT COUNT(*) FROM subscriptions WHERE status = 'active'")

    return jsonify({
        "visitors": visitors,
        "subscribers": {
            "active_subscriptions": active_subs,
            "accounts": accounts,
            "verified_accounts": verified,
        },
        "activity": activity,
        "top_pages": [{"page": p, "views": c, "unique_visitors": s}
                      for p, c, s in top_pages],
        "daily": [{"date": d, "visitors": s, "page_views": pv or 0}
                  for d, s, pv in daily],
        "top_referrers": [{"referrer": r, "count": c}
                          for r, c in top_referrers],
        "devices": [{"device": dv, "count": c} for dv, c in devices],
        "languages": [{"language": lg, "count": c} for lg, c in languages],
        "top_hazards": [{"hazard": h, "count": c} for h, c in top_hazards],
        "note": "Aggregate counts only — sessions are pseudonymous; no "
                "individual visitor is identifiable.",
        "generated_at": now.isoformat() + "Z",
    })


@marketing_crm_bp.get("/admin/marketing/lead/<lead_slug>")
@require_role("admin")
def marketing_lead_detail(lead_slug: str):
    """Full merged lead, score, interactions, follow-up file and scheduled
    outreach for a single lead."""
    lead = _leads_by_slug().get(lead_slug)
    if lead is None:
        return jsonify({"error": f"Unknown lead '{lead_slug}'", "status": 404}), 404

    # Follow-up files are named by scripts/followup_engine.py:save_followup as
    # organization.lower().replace(" ", "-").replace("/", "-") + "_followup.json"
    # — which keeps parentheses/commas, so it usually differs from the cleaned
    # lead slug. Try the generator's form first, then the slug form.
    followup = None
    org_slug = (lead.get("organization") or "").lower().replace(" ", "-").replace("/", "-")
    for name in (f"{org_slug}_followup.json", f"{lead_slug}_followup.json"):
        followup_path = os.path.join(
            _WORKSPACE, "followups", os.path.basename(name))
        if os.path.isfile(followup_path):
            try:
                with open(followup_path, encoding="utf-8") as fh:
                    followup = json.load(fh)
            except (OSError, ValueError):
                followup = None
            break

    return jsonify({
        "lead": lead,
        "score": _lead_score(lead),
        "interactions": lead.get("interactions") or [],
        "followup": followup,
        "scheduled": MarketingStore().list_scheduled(lead_slug=lead_slug),
    })


@marketing_crm_bp.post("/admin/marketing/lead/<lead_slug>/send")
@require_role("admin")
def marketing_lead_send(lead_slug: str):
    """Render and send an outreach email immediately."""
    lead = _leads_by_slug().get(lead_slug)
    if lead is None:
        return jsonify({"error": f"Unknown lead '{lead_slug}'", "status": 404}), 404
    if lead.get("excluded"):
        return jsonify({"error": "Lead is excluded", "status": 409}), 409

    data = request.get_json(silent=True) or {}
    to_email = (data.get("to_email") or "").strip()
    if not to_email or not _EMAIL_RE.match(to_email):
        return jsonify({"error": "to_email is required and must be valid", "status": 400}), 400

    template, context = _outreach_template_and_context(lead, data)
    try:
        delivery = mailer.send_mail(to_email, template, context)
    except Exception as exc:
        return jsonify({"error": "delivery failed", "detail": str(exc), "status": 502}), 502

    store = MarketingStore()
    subject = delivery.get("subject") or f"outreach ({template})"
    store.add_interaction(
        lead_slug,
        summary=f"Outreach email to {to_email} ({template}): {subject}",
        type="email",
    )

    current_status = lead.get("outreach_status") or "researched"
    if current_status in ("researched", "qualified", "draft_prepared", ""):
        store.update_state(lead_slug, outreach_status="contacted")

    new_state = store.get_state(lead_slug)
    return jsonify({
        "ok": True,
        "delivery": delivery,
        "outreach_status": (new_state or {}).get("outreach_status", "contacted"),
    })


@marketing_crm_bp.post("/admin/marketing/lead/<lead_slug>/schedule")
@require_role("admin")
def marketing_lead_schedule(lead_slug: str):
    """Queue an outreach email for future delivery."""
    lead = _leads_by_slug().get(lead_slug)
    if lead is None:
        return jsonify({"error": f"Unknown lead '{lead_slug}'", "status": 404}), 404
    if lead.get("excluded"):
        return jsonify({"error": "Lead is excluded", "status": 409}), 409

    data = request.get_json(silent=True) or {}
    to_email = (data.get("to_email") or "").strip()
    if not to_email or not _EMAIL_RE.match(to_email):
        return jsonify({"error": "to_email is required and must be valid", "status": 400}), 400

    send_at_raw = (data.get("send_at") or "").strip()
    normalized = send_at_raw.rstrip("Z")[:19]
    if not normalized or len(normalized) < 19:
        return jsonify({"error": "send_at must be an ISO datetime", "status": 400}), 400
    if normalized < datetime.utcnow().isoformat()[:19]:
        return jsonify({"error": "send_at must be in the future", "status": 400}), 400

    template, context = _outreach_template_and_context(lead, data)
    row = MarketingStore().schedule_send(
        lead_slug=lead_slug,
        to_email=to_email,
        contact_name=context.get("contact_name") or None,
        template=template,
        context=context,
        send_at=normalized,
    )
    if row is None:
        return jsonify({"error": "Invalid schedule data", "status": 400}), 400
    return jsonify({"ok": True, "scheduled": row})


@marketing_crm_bp.get("/admin/marketing/scheduled")
@require_role("admin")
def marketing_scheduled_list():
    """All scheduled outreach rows, optionally filtered to one lead."""
    lead = (request.args.get("lead") or "").strip() or None
    rows = MarketingStore().list_scheduled(lead_slug=lead)
    return jsonify({"scheduled": rows})


@marketing_crm_bp.post("/admin/marketing/scheduled/<int:sid>/cancel")
@require_role("admin")
def marketing_scheduled_cancel(sid: int):
    """Cancel a scheduled outreach row before it is sent."""
    store = MarketingStore()
    row = store.get_scheduled(sid)
    if row is None:
        return jsonify({"error": "Unknown scheduled outreach", "status": 404}), 404
    if row.get("status") != "scheduled":
        return jsonify({"error": "Scheduled outreach is not cancellable", "status": 409}), 409
    cancelled = store.cancel_scheduled(sid)
    if cancelled is None:
        return jsonify({"error": "Scheduled outreach is not cancellable", "status": 409}), 409
    return jsonify({"ok": True, "scheduled": cancelled})
