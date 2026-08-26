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
import threading
from collections import Counter
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from flask import Blueprint, jsonify, request

from . import email_discovery, hunter, mailer
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

_DAILY_SEND_CAP = int(os.environ.get("DAILY_SEND_CAP") or 20)


class _SimpleRateLimiter:
    """In-memory per-key sliding-window rate limiter."""

    def __init__(self) -> None:
        self._hits: Dict[str, List[float]] = {}

    def allow(self, key: str, max_requests: int, window_seconds: float) -> bool:
        import time
        now = time.time()
        with threading.Lock():
            window = [t for t in self._hits.get(key, []) if now - t < window_seconds]
            if len(window) >= max_requests:
                self._hits[key] = window
                return False
            window.append(now)
            self._hits[key] = window
            return True


_email_discovery_limiter = _SimpleRateLimiter()


def _rate_limit_discovery(key: str) -> bool:
    return _email_discovery_limiter.allow(key, max_requests=10, window_seconds=60.0)


def _daily_cap_reached() -> bool:
    return MarketingStore().sent_today_count() >= _DAILY_SEND_CAP


def _lead_store_state(lead_slug: str) -> Dict:
    """Return stored state fields merged with safe defaults."""
    state = MarketingStore().get_state(lead_slug) or {}
    return {
        "auto_send": bool(state.get("auto_send")),
        "unsubscribed": bool(state.get("unsubscribed")),
        "unsub_reason": state.get("unsub_reason"),
    }


def _all_leads() -> List[Dict]:
    """Merged workspace leads with working-state overlay."""
    return _overlay_ops(_records_ws("leads"))


def _lead_sector(lead: Dict) -> str:
    """The sector key used for grouping/filtering (alias-aware)."""
    return _target_sector(lead.get("segment") or "") or (lead.get("segment") or "")


# The six "Solutions for" categories (the site's for-* pages). Segments
# aliased into them roll up to the category; every other segment stays
# addressable under the "more" bucket — the platform targets all sectors.
_CATEGORY_ALIAS = {
    "municipalities": "governments",
    "municipal_climate_adaptation": "governments",
    "emergency_management": "governments",
    "water_management": "governments",
    "asset_management": "investment",
    "sustainable_finance": "investment",
    "green_investment": "investment",
    "engineering_firms": "environmental_consulting",
}
_CATEGORY_KEYS = [k for k, _ in _TARGET_SECTORS]


def _lead_category(lead: Dict) -> str:
    """Top-level targeting category: one of the six for-* sectors, or
    "more" for every other segment."""
    seg = lead.get("segment") or ""
    mapped = _CATEGORY_ALIAS.get(seg) or (_target_sector(seg) or seg)
    return mapped if mapped in _CATEGORY_KEYS else "more"


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
        "unsubscribe_url": "",
    }
    return template, context


@marketing_crm_bp.get("/admin/marketing/tree")
@require_role("admin")
def marketing_tree():
    """Lazy navigation: category → country → (region) → intersection.

    Root returns the six "Solutions for" categories plus a "more" bucket
    holding every other segment (we target all sectors). The country level
    returns the intersection — statuses, sub-national regions and the full
    lead list — filterable by region and status."""
    segment = (request.args.get("segment") or "").strip()
    country = (request.args.get("country") or "").strip()
    region = (request.args.get("region") or "").strip()
    status = (request.args.get("status") or "").strip()

    leads = [l for l in _all_leads() if not l.get("excluded")]

    def _matches(l: Dict, key: str) -> bool:
        if key in _CATEGORY_KEYS or key == "more":
            return _lead_category(l) == key
        return (l.get("segment") or "") == key

    def _lead_row(l: Dict) -> Dict:
        return {
            "slug": l.get("_slug"),
            "organization": l.get("organization"),
            "segment": l.get("segment"),
            "region": l.get("region"),
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
        if country or status or region:
            return jsonify({"error": "segment is required", "status": 400}), 400
        counts: Dict[str, int] = {}
        for l in leads:
            key = _lead_category(l)
            counts[key] = counts.get(key, 0) + 1
        labels = dict(_TARGET_SECTORS)
        sectors = [{"key": key, "label": label,
                    "count": counts.get(key, 0)}
                   for key, label in _TARGET_SECTORS]
        if counts.get("more"):
            sectors.append({"key": "more", "label": "More sectors",
                            "count": counts["more"]})
        return jsonify({"sectors": sectors})

    if not country:
        if status or region:
            return jsonify({"error": "country is required", "status": 400}), 400
        seg_leads = [l for l in leads if _matches(l, segment)]
        if segment == "more":
            # Sub-sectors inside the "more" bucket (raw segments).
            sub = Counter(l.get("segment") or "?" for l in seg_leads)
            return jsonify({
                "segment": "more",
                "subsectors": [
                    {"key": k, "label": k.replace("_", " ").title(), "count": c}
                    for k, c in sorted(sub.items(), key=lambda kv: (-kv[1], kv[0]))
                ],
            })
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
        if _matches(l, segment) and (l.get("country") or "") == country
    ]
    region_counts = Counter(
        (l.get("region") or "").strip() for l in seg_leads
        if (l.get("region") or "").strip())
    if region:
        seg_leads = [
            l for l in seg_leads if (l.get("region") or "").strip() == region]
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
        "regions": [
            {"region": r, "count": c}
            for r, c in sorted(region_counts.items(), key=lambda kv: -kv[1])
        ],
        "statuses": [
            {"status": s, "count": status_counts[s]}
            for s in OUTREACH_STATUSES if status_counts.get(s)
        ],
        "leads": [_lead_row(l) for l in seg_leads],
    }
    if region:
        resp["region"] = region
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
    """Full merged lead, score, interactions, follow-up file, scheduled
    outreach and discovered contacts for a single lead."""
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

    store = MarketingStore()
    lead["auto_send"] = _lead_store_state(lead_slug)["auto_send"]
    lead["unsubscribed"] = _lead_store_state(lead_slug)["unsubscribed"]
    lead["unsub_reason"] = _lead_store_state(lead_slug)["unsub_reason"]
    return jsonify({
        "lead": lead,
        "score": _lead_score(lead),
        "interactions": lead.get("interactions") or [],
        "followup": followup,
        "scheduled": store.list_scheduled(lead_slug=lead_slug),
        "contacts": store.list_contacts(lead_slug),
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

    store = MarketingStore()
    if store.is_unsubscribed(lead_slug):
        return jsonify({"error": "Lead has unsubscribed from outreach", "status": 400}), 400
    if _daily_cap_reached():
        return jsonify({
            "error": "Daily outreach cap reached — retry tomorrow",
            "cap": _DAILY_SEND_CAP,
            "status": 429,
        }), 429

    data = request.get_json(silent=True) or {}
    to_email = (data.get("to_email") or "").strip()
    if not to_email or not _EMAIL_RE.match(to_email):
        return jsonify({"error": "to_email is required and must be valid", "status": 400}), 400

    template, context = _outreach_template_and_context(lead, data)
    try:
        delivery = mailer.send_mail(to_email, template, context)
    except Exception as exc:
        return jsonify({"error": "delivery failed", "detail": str(exc), "status": 502}), 502

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

    store = MarketingStore()
    if store.is_unsubscribed(lead_slug):
        return jsonify({"error": "Lead has unsubscribed from outreach", "status": 400}), 400

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
    row = store.schedule_send(
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


# ---------------------------------------------------------------------------
# Replies and campaigns (Phase 18)
# ---------------------------------------------------------------------------


@marketing_crm_bp.get("/admin/marketing/replies")
@require_role("admin")
def marketing_replies():
    """Latest reply interactions across leads, newest first."""
    store = MarketingStore()
    interactions = store.list_interactions()
    replies = [
        {
            "id": i["id"],
            "lead_slug": i["lead_slug"],
            "organization": _leads_by_slug().get(i["lead_slug"], {}).get("organization"),
            "date": i["date"],
            "summary": i["summary"],
        }
        for i in interactions
        if i["type"] in ("reply", "unsubscribe")
    ][:100]
    return jsonify({"replies": replies})


@marketing_crm_bp.get("/admin/marketing/campaigns")
@require_role("admin")
def marketing_campaigns():
    """Stats for all campaigns."""
    return jsonify({"campaigns": MarketingStore().campaign_stats()})


@marketing_crm_bp.get("/admin/marketing/campaigns/<name>")
@require_role("admin")
def marketing_campaign_detail(name: str):
    """Stats + per-wave breakdown + leads list for one campaign."""
    stats = MarketingStore().campaign_stats(campaign=name)
    if not stats:
        return jsonify({"error": f"Unknown campaign '{name}'", "status": 404}), 404
    return jsonify({"campaign": stats[0]})


@marketing_crm_bp.post("/admin/marketing/campaigns/start")
@require_role("admin")
def marketing_campaign_start():
    """Enqueue a campaign wave for matching leads."""
    from .campaigns import ALLOWED_TEMPLATES, start_campaign

    data = request.get_json(silent=True) or {}
    campaign = (data.get("campaign") or "").strip()
    wave = data.get("wave")
    template = (data.get("template") or "").strip()
    filters = data.get("filters") or {}
    delay_days = data.get("delay_days", 0.0)

    if not campaign:
        return jsonify({"error": "campaign is required", "status": 400}), 400
    if not isinstance(wave, int) or wave < 1:
        return jsonify({"error": "wave must be an integer >= 1", "status": 400}), 400
    if template not in ALLOWED_TEMPLATES:
        return jsonify({
            "error": f"template must be one of {sorted(ALLOWED_TEMPLATES)}",
            "status": 400,
        }), 400
    if not isinstance(filters, dict):
        return jsonify({"error": "filters must be an object", "status": 400}), 400
    if "segment" in filters and not isinstance(filters["segment"], str):
        return jsonify({"error": "filters.segment must be a string", "status": 400}), 400
    if "country" in filters and not isinstance(filters["country"], str):
        return jsonify({"error": "filters.country must be a string", "status": 400}), 400

    try:
        result = start_campaign(
            campaign=campaign,
            wave=wave,
            template=template,
            filters={k: v for k, v in filters.items() if k in ("segment", "country")},
            delay_days=float(delay_days) if delay_days is not None else 0.0,
        )
    except ValueError as exc:
        return jsonify({"error": str(exc), "status": 400}), 400

    return jsonify({"ok": True, **result})


# ---------------------------------------------------------------------------
# Lead contact discovery (Hunter.io)
# ---------------------------------------------------------------------------

@marketing_crm_bp.get("/admin/marketing/lead/<lead_slug>/contacts")
@require_role("admin")
def marketing_lead_contacts(lead_slug: str):
    """Stored discovered contacts for a lead."""
    if lead_slug not in _leads_by_slug():
        return jsonify({"error": f"Unknown lead '{lead_slug}'", "status": 404}), 404
    return jsonify({
        "configured": hunter.configured(),
        "contacts": MarketingStore().list_contacts(lead_slug),
    })


@marketing_crm_bp.post("/admin/marketing/lead/<lead_slug>/contacts/discover")
@require_role("admin")
def marketing_lead_contacts_discover(lead_slug: str):
    """Discover and store contacts for a lead's domain via Hunter.io."""
    lead = _leads_by_slug().get(lead_slug)
    if lead is None:
        return jsonify({"error": f"Unknown lead '{lead_slug}'", "status": 404}), 404

    store = MarketingStore()
    if not hunter.configured():
        return jsonify({
            "configured": False,
            "note": "Hunter.io is not configured on this server — set HUNTER_API_KEY and redeploy.",
            "contacts": store.list_contacts(lead_slug),
        }), 200

    domain = hunter.domain_from_url(lead.get("website"))
    if domain is None:
        return jsonify({"error": "no usable domain on this lead", "status": 422}), 422

    try:
        contacts = hunter.domain_search(domain)
    except hunter.HunterError as exc:
        return jsonify({"error": str(exc), "status": 502}), 502

    added = store.add_contacts(lead_slug, contacts, source="hunter")
    return jsonify({
        "configured": True,
        "domain": domain,
        "added": added,
        "contacts": store.list_contacts(lead_slug),
    })


@marketing_crm_bp.post("/admin/marketing/contacts/<int:cid>/delete")
@require_role("admin")
def marketing_contact_delete(cid: int):
    """Delete a stored discovered contact."""
    deleted = MarketingStore().delete_contact(cid)
    if deleted is None:
        return jsonify({"error": "Unknown contact", "status": 404}), 404
    return jsonify({"ok": True})


@marketing_crm_bp.post("/admin/marketing/lead/<lead_slug>/find-email")
@require_role("admin")
def marketing_lead_find_email(lead_slug: str):
    """Find a single email address on the lead's domain given a name."""
    lead = _leads_by_slug().get(lead_slug)
    if lead is None:
        return jsonify({"error": f"Unknown lead '{lead_slug}'", "status": 404}), 404
    if not hunter.configured():
        return jsonify({
            "error": "Hunter.io is not configured on this server — set HUNTER_API_KEY and redeploy.",
            "status": 503,
        }), 503

    data = request.get_json(silent=True) or {}
    first_name = (data.get("first_name") or "").strip()
    last_name = (data.get("last_name") or "").strip()
    if not first_name or not last_name:
        return jsonify({"error": "first_name and last_name are required", "status": 400}), 400

    domain = hunter.domain_from_url(lead.get("website"))
    if domain is None:
        return jsonify({"error": "no usable domain on this lead", "status": 422}), 422

    try:
        found = hunter.email_finder(domain, first_name, last_name)
    except hunter.HunterError as exc:
        return jsonify({"error": str(exc), "status": 502}), 502

    if found is None:
        return jsonify({"found": False, "domain": domain}), 200

    store = MarketingStore()
    store.add_contacts(
        lead_slug,
        [{
            "email": found["email"],
            "name": f"{first_name} {last_name}".strip(),
            "confidence": found.get("score"),
            "verification": found.get("verification"),
        }],
        source="hunter_finder",
    )
    return jsonify({
        "found": True,
        "domain": domain,
        "contact": store.list_contacts(lead_slug)[0],
    })


@marketing_crm_bp.post("/admin/marketing/verify-email")
@require_role("admin")
def marketing_verify_email():
    """Verify an arbitrary email address with Hunter.io."""
    if not hunter.configured():
        return jsonify({
            "error": "Hunter.io is not configured on this server — set HUNTER_API_KEY and redeploy.",
            "status": 503,
        }), 503

    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip()
    if not email or not _EMAIL_RE.match(email):
        return jsonify({"error": "email is required and must be valid", "status": 400}), 400

    try:
        result = hunter.verify_email(email)
    except hunter.HunterError as exc:
        return jsonify({"error": str(exc), "status": 502}), 502
    return jsonify({"ok": True, "verification": result})


@marketing_crm_bp.post("/admin/marketing/contacts/<int:cid>/verify")
@require_role("admin")
def marketing_contact_verify(cid: int):
    """Verify a stored contact's email and persist the result."""
    if not hunter.configured():
        return jsonify({
            "error": "Hunter.io is not configured on this server — set HUNTER_API_KEY and redeploy.",
            "status": 503,
        }), 503

    store = MarketingStore()
    contact = store.get_contact(cid)
    if contact is None:
        return jsonify({"error": "Unknown contact", "status": 404}), 404

    try:
        result = hunter.verify_email(contact["email"])
    except hunter.HunterError as exc:
        return jsonify({"error": str(exc), "status": 502}), 502

    verification = result.get("result") or result.get("status") or "unknown"
    store.set_contact_verification(cid, verification)
    return jsonify({"ok": True, "verification": result})


@marketing_crm_bp.post("/admin/marketing/tree/discover")
@require_role("admin")
def marketing_tree_discover():
    """Bulk-discover contacts for every lead in an intersection."""
    if not hunter.configured():
        return jsonify({
            "error": "Hunter.io is not configured on this server — set HUNTER_API_KEY and redeploy.",
            "status": 503,
        }), 503

    data = request.get_json(silent=True) or {}
    segment = (data.get("segment") or "").strip()
    country = (data.get("country") or "").strip()
    region = (data.get("region") or "").strip()
    if not segment or not country:
        return jsonify({"error": "segment and country are required", "status": 400}), 400

    leads = [
        l for l in _all_leads()
        if _lead_category(l) == segment
        and (l.get("country") or "") == country
        and (not region or (l.get("region") or "").strip() == region)
        and not l.get("excluded")
    ]

    store = MarketingStore()
    added = 0
    domains = []
    skipped = 0
    for lead in leads:
        slug = lead.get("_slug")
        if not slug:
            skipped += 1
            continue
        if store.list_contacts(slug):
            skipped += 1
            continue
        domain = hunter.domain_from_url(lead.get("website"))
        if domain is None:
            skipped += 1
            continue
        try:
            contacts = hunter.domain_search(domain)
        except hunter.HunterError:
            skipped += 1
            continue
        if contacts:
            new = store.add_contacts(slug, contacts, source="hunter")
            added += new
            domains.append(domain)

    return jsonify({
        "added": added,
        "domains": domains,
        "skipped": skipped,
        "leads": len(leads),
    })


@marketing_crm_bp.post("/admin/marketing/lead/<lead_slug>/auto-send")
@require_role("admin")
def marketing_lead_auto_send(lead_slug: str):
    """Toggle auto-send for a lead."""
    if lead_slug not in _leads_by_slug():
        return jsonify({"error": f"Unknown lead '{lead_slug}'", "status": 404}), 404
    data = request.get_json(silent=True) or {}
    enabled = bool(data.get("enabled"))
    MarketingStore().set_auto_send(lead_slug, enabled)
    return jsonify({"ok": True, "auto_send": enabled})


@marketing_crm_bp.post("/admin/marketing/lead/<lead_slug>/unsubscribe")
@require_role("admin")
def marketing_lead_unsubscribe(lead_slug: str):
    """Mark a lead as unsubscribed from outreach."""
    if lead_slug not in _leads_by_slug():
        return jsonify({"error": f"Unknown lead '{lead_slug}'", "status": 404}), 404
    data = request.get_json(silent=True) or {}
    reason = (data.get("reason") or "").strip() or None
    MarketingStore().unsubscribe(lead_slug, reason)
    return jsonify({"ok": True, "unsubscribed": True})


@marketing_crm_bp.post("/admin/marketing/lead/<lead_slug>/preview")
@require_role("admin")
def marketing_lead_preview(lead_slug: str):
    """Render the outreach template for a lead without sending."""
    lead = _leads_by_slug().get(lead_slug)
    if lead is None:
        return jsonify({"error": f"Unknown lead '{lead_slug}'", "status": 404}), 404
    data = request.get_json(silent=True) or {}
    template, context = _outreach_template_and_context(lead, data)
    try:
        rendered = mailer.render_template(template, context)
    except Exception as exc:
        return jsonify({"error": "render failed", "detail": str(exc), "status": 502}), 502
    return jsonify({
        "ok": True,
        "template": template,
        "subject": rendered["subject"],
        "body": rendered["text"],
    })


# ---------------------------------------------------------------------------
# Self-hosted email discovery (Talaix engine)
# ---------------------------------------------------------------------------

def _discovery_client_key() -> str:
    return request.headers.get(
        "X-Forwarded-For", request.remote_addr or "unknown"
    ).split(",")[0].strip()


@marketing_crm_bp.post("/admin/marketing/lead/<lead_slug>/contacts/discover-own")
@require_role("admin")
def marketing_lead_contacts_discover_own(lead_slug: str):
    """Discover and store contacts for a lead's domain using the Talaix engine."""
    lead = _leads_by_slug().get(lead_slug)
    if lead is None:
        return jsonify({"error": f"Unknown lead '{lead_slug}'", "status": 404}), 404

    if not _rate_limit_discovery(f"discover-own:{_discovery_client_key()}"):
        return jsonify({"error": "Rate limit exceeded (10 requests/minute)", "status": 429}), 429

    domain = hunter.domain_from_url(lead.get("website"))
    if domain is None:
        return jsonify({"error": "no usable domain on this lead", "status": 400}), 400

    result = email_discovery.discover_emails(domain)
    contacts = result.get("contacts", [])
    store = MarketingStore()
    added = store.add_contacts(
        lead_slug,
        [{
            "email": c["email"],
            "name": None,
            "confidence": int(c.get("confidence", 0.5) * 100) if c.get("confidence") is not None else None,
            "source": "talaix-discovery",
            "verification": c.get("claim_status", "OBSERVED"),
        } for c in contacts],
        source="talaix-discovery",
    )
    return jsonify({
        "ok": True,
        "domain": domain,
        "added": added,
        "contacts": store.list_contacts(lead_slug),
        "pages_fetched": result.get("pages_fetched"),
        "robots_respected": result.get("robots_respected"),
        "note": result.get("note"),
    })


@marketing_crm_bp.post("/admin/marketing/lead/<lead_slug>/contacts/infer-email")
@require_role("admin")
def marketing_lead_contacts_infer_email(lead_slug: str):
    """Infer an email for a person from observed domain patterns.

    Stores the result only when an email was inferred; UNKNOWN verdicts are
    returned without writing to the database.
    """
    lead = _leads_by_slug().get(lead_slug)
    if lead is None:
        return jsonify({"error": f"Unknown lead '{lead_slug}'", "status": 404}), 404

    if not _rate_limit_discovery(f"infer-email:{_discovery_client_key()}"):
        return jsonify({"error": "Rate limit exceeded (10 requests/minute)", "status": 429}), 429

    data = request.get_json(silent=True) or {}
    first_name = (data.get("first_name") or "").strip()
    last_name = (data.get("last_name") or "").strip()
    if not first_name or not last_name:
        return jsonify({"error": "first_name and last_name are required", "status": 400}), 400

    domain = hunter.domain_from_url(lead.get("website"))
    if domain is None:
        return jsonify({"error": "no usable domain on this lead", "status": 400}), 400

    store = MarketingStore()
    known = [c["email"] for c in store.list_contacts(lead_slug)]
    verdict = email_discovery.find_for_person(domain, first_name, last_name, known_emails=known or None)

    if verdict.get("claim_status") != "INFERRED" or not verdict.get("email"):
        return jsonify({
            "ok": True,
            "found": False,
            "claim_status": verdict.get("claim_status"),
            "reason": verdict.get("reason"),
        })

    store.add_contacts(
        lead_slug,
        [{
            "email": verdict["email"],
            "name": f"{first_name} {last_name}".strip(),
            "confidence": int(verdict.get("confidence", 0.6) * 100),
            "source": "talaix-inference",
            "verification": "INFERRED",
            "position": "pattern-inferred — verify before sending",
        }],
        source="talaix-inference",
    )
    return jsonify({
        "ok": True,
        "found": True,
        "claim_status": "INFERRED",
        "email": verdict["email"],
        "pattern": verdict.get("pattern"),
        "basis": verdict.get("basis"),
        "contacts": store.list_contacts(lead_slug),
    })


@marketing_crm_bp.post("/admin/marketing/tree/discover-own")
@require_role("admin")
def marketing_tree_discover_own():
    """Bulk-discover contacts with the Talaix engine across an intersection."""
    if not _rate_limit_discovery(f"tree-discover-own:{_discovery_client_key()}"):
        return jsonify({"error": "Rate limit exceeded (10 requests/minute)", "status": 429}), 429

    data = request.get_json(silent=True) or {}
    segment = (data.get("segment") or "").strip()
    country = (data.get("country") or "").strip()
    region = (data.get("region") or "").strip()
    if not segment or not country:
        return jsonify({"error": "segment and country are required", "status": 400}), 400

    leads = [
        l for l in _all_leads()
        if _lead_category(l) == segment
        and (l.get("country") or "") == country
        and (not region or (l.get("region") or "").strip() == region)
        and not l.get("excluded")
    ][:10]

    store = MarketingStore()
    processed = added = skipped = errors = 0
    for lead in leads:
        slug = lead.get("_slug")
        if not slug:
            skipped += 1
            continue
        if store.list_contacts(slug):
            skipped += 1
            continue
        domain = hunter.domain_from_url(lead.get("website"))
        if domain is None:
            skipped += 1
            continue
        try:
            result = email_discovery.discover_emails(domain, max_pages=8)
            contacts = result.get("contacts", [])
            if contacts:
                new = store.add_contacts(
                    slug,
                    [{
                        "email": c["email"],
                        "confidence": int(c.get("confidence", 0.5) * 100) if c.get("confidence") is not None else None,
                        "source": "talaix-discovery",
                        "verification": c.get("claim_status", "OBSERVED"),
                    } for c in contacts],
                    source="talaix-discovery",
                )
                added += new
            processed += 1
        except Exception:
            errors += 1

    return jsonify({
        "ok": True,
        "processed": processed,
        "added": added,
        "skipped": skipped,
        "errors": errors,
        "leads": len(leads),
    })
