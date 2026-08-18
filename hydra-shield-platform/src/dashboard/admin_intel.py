"""
HydraShield operator intelligence — admin-only aggregate dashboard API.

``GET /api/v2/admin/intel`` answers the operator's daily questions from
aggregate counts (never row-level personal data):

- today: new users, new alert rules, analytics events today
- accounts: totals by role/status
- alerts: rules, verified phones, recent alert records
- demand: top hazards/pages + the conversion funnel (analytics store)
- workspace: the marketing/ workspace state when it is present in this
  deployment (it is excluded from the Docker image — then the endpoint
  honestly reports ``workspace.available = false``)

Admin-only via ``require_role("admin")``. Everything here is counts and
workspace record summaries; no individual visitor is identifiable.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from flask import Blueprint, jsonify

from .analytics import AnalyticsStore
from .auth_api import require_role
from .cache import default_cache

admin_intel_bp = Blueprint("admin_intel", __name__, url_prefix="/api/v2")

_WORKSPACE = os.path.normpath(os.path.join(
    os.path.dirname(__file__), "..", "..", "marketing"))


def _today() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d")


def _workspace_section() -> Dict[str, Any]:
    """Marketing workspace summary, or an honest unavailable marker."""
    if not os.path.isdir(_WORKSPACE):
        return {"available": False,
                "note": "The marketing workspace is not part of this "
                        "deployment (operator-local by design)."}

    def _records(subdir: str) -> List[Dict]:
        d = os.path.join(_WORKSPACE, subdir)
        out = []
        if not os.path.isdir(d):
            return out
        for name in sorted(os.listdir(d)):
            if name.endswith(".json") and name != "schema.json":
                try:
                    with open(os.path.join(d, name), encoding="utf-8") as fh:
                        out.append(json.load(fh))
                except (OSError, ValueError):
                    continue
        return out

    leads = _records("leads")
    signals = _records("signals")
    events = _records("events")
    eu_funding = _records("eu_funding")
    today = _today()
    followups_due = [
        {"organization": l.get("organization"),
         "next_followup": l.get("next_followup"),
         "next_action": l.get("next_action")}
        for l in leads
        if l.get("next_followup") and l["next_followup"] <= today
        and l.get("status", "open") not in ("won", "lost")
    ]

    def _status_count(leads, *statuses):
        return sum(1 for l in leads
                   if l.get("outreach_status", "researched") in statuses)

    interactions = []
    for l in leads:
        for i in l.get("interactions") or []:
            interactions.append({"organization": l.get("organization"),
                                 "date": i.get("date"), "type": i.get("type"),
                                 "summary": i.get("summary"),
                                 "next_action": i.get("next_action")})
    interactions.sort(key=lambda x: x.get("date") or "", reverse=True)

    markets = {}
    for l in leads:
        markets[l.get("segment", "?")] = markets.get(l.get("segment", "?"), 0) + 1

    return {
        "available": True,
        "prospects": {
            "total": len(leads),
            "new": _status_count(leads, "researched"),
            "qualified": _status_count(leads, "qualified", "draft_prepared"),
            "high_priority": sum(1 for l in leads if l.get("priority") == "high"),
            "contacted": _status_count(leads, "contacted"),
            "responded": _status_count(leads, "responded"),
            "opportunities": _status_count(leads, "opportunity"),
            "followups_due": followups_due,
        },
        "markets": markets,
        "signals": {
            "total": len(signals),
            "eu_funding_records": len(eu_funding),
            "events_tracked": len(events),
        },
        "leads": [
            {"organization": l.get("organization"),
             "segment": l.get("segment"), "country": l.get("country"),
             "identified_problem": l.get("identified_problem"),
             "hazards": l.get("relevant_hazards"),
             "priority": l.get("priority"), "urgency": l.get("urgency"),
             "outreach_status": l.get("outreach_status", "researched"),
             "relationship_type": l.get("relationship_type", "customer"),
             "status": l.get("status", "open"),
             "last_contact": l.get("last_contact"),
             "next_action": l.get("next_action"),
             "interactions": l.get("interactions") or []}
            for l in leads
        ],
        "relationships": interactions,
    }


@admin_intel_bp.get("/admin/intel")
@require_role("admin")
def admin_intelligence():
    db_path = default_cache().db_path
    today = _today()
    week_ago = (datetime.utcnow() - timedelta(days=7)).isoformat() + "Z"

    with sqlite3.connect(db_path, timeout=10.0) as conn:
        def _scalar(sql, params=()):
            try:
                return conn.execute(sql, params).fetchone()[0]
            except sqlite3.Error:
                return 0

        users_total = _scalar("SELECT COUNT(*) FROM users")
        users_today = _scalar(
            "SELECT COUNT(*) FROM users WHERE created_at >= ?", (today,))
        by_role = dict(conn.execute(
            "SELECT role, COUNT(*) FROM users GROUP BY role").fetchall())
        alert_rules = _scalar("SELECT COUNT(*) FROM alert_rules WHERE active = 1")
        rules_today = _scalar(
            "SELECT COUNT(*) FROM alert_rules WHERE created_at >= ?", (today,))
        verified_phones = _scalar(
            "SELECT COUNT(*) FROM phone_numbers WHERE verified_at IS NOT NULL")
        alert_records_7d = _scalar(
            "SELECT COUNT(*) FROM alert_records WHERE created_at >= ?",
            (week_ago,))
        events_today = _scalar(
            "SELECT COUNT(*) FROM analytics_events WHERE ts >= ?", (today,))
        saved_locations = _scalar("SELECT COUNT(*) FROM saved_locations")
        verified_accounts = _scalar(
            "SELECT COUNT(*) FROM users WHERE email_verified_at IS NOT NULL")

    store = AnalyticsStore(db_path)
    with store._connect() as conn:
        funnel = dict(conn.execute(
            "SELECT event, COUNT(*) FROM analytics_events GROUP BY event"
        ).fetchall())
        top_hazards = conn.execute(
            "SELECT hazard, COUNT(*) AS c FROM analytics_events "
            "WHERE hazard IS NOT NULL GROUP BY hazard ORDER BY c DESC LIMIT 6"
        ).fetchall()
        top_pages = conn.execute(
            "SELECT page, COUNT(*) AS c FROM analytics_events "
            "WHERE page IS NOT NULL GROUP BY page ORDER BY c DESC LIMIT 8"
        ).fetchall()
        visitors_today = conn.execute(
            "SELECT COUNT(DISTINCT session_hash) FROM analytics_events "
            "WHERE ts >= ? AND session_hash IS NOT NULL", (today,)).fetchone()[0]
        analyses_today = conn.execute(
            "SELECT COUNT(*) FROM analytics_events "
            "WHERE event = 'location_analyzed' AND ts >= ?", (today,)).fetchone()[0]
        reports_today = conn.execute(
            "SELECT COUNT(*) FROM analytics_events "
            "WHERE event = 'report_generated' AND ts >= ?", (today,)).fetchone()[0]
        # Repeat users: pseudonymous sessions seen on more than one day
        # (aggregate count only — privacy-safe).
        repeat_users = conn.execute(
            "SELECT COUNT(*) FROM (SELECT session_hash FROM analytics_events "
            "WHERE session_hash IS NOT NULL "
            "GROUP BY session_hash HAVING COUNT(DISTINCT substr(ts,1,10)) > 1)"
        ).fetchone()[0]
        repeat_analysis = conn.execute(
            "SELECT COUNT(*) FROM (SELECT session_hash FROM analytics_events "
            "WHERE event = 'location_analyzed' AND session_hash IS NOT NULL "
            "GROUP BY session_hash HAVING COUNT(*) > 1)").fetchone()[0]

    # 30-day commercial experiment: TARGETS vs ACTUAL — structurally
    # separate; targets are never presented as results.
    ws = _workspace_section()
    targets = {
        "researched_organizations": {"target": 100,
            "actual": (ws.get("prospects") or {}).get("total", 0) if ws.get("available") else 0},
        "qualified_prospects": {"target": 30,
            "actual": (ws.get("prospects") or {}).get("qualified", 0) if ws.get("available") else 0},
        "eu_funding_records": {"target": 10,
            "actual": (ws.get("signals") or {}).get("eu_funding_records", 0) if ws.get("available") else 0},
        "linkedin_posts_published": {"target": 12, "actual": 0},
        "target_meetings": {"target": 5,
            "actual": sum(1 for r in (ws.get("relationships") or [])
                          if r.get("type") in ("meeting", "demo")) if ws.get("available") else 0},
    }

    # CUSTOMERS block (workspace-derived; honest zeros when workspace absent)
    customers = {"new_prospects": 0, "qualified_prospects": 0, "hot_prospects": 0,
                 "customers": 0, "subscribers": 0, "renewals": 0, "lost": 0}
    marketing = {"campaigns": 0, "linkedin_drafts": 0, "email_queued": 0,
                 "content_drafts": 0, "eu_funding_records": 0, "events": 0,
                 "partners": 0}
    if ws.get("available"):
        prospects = ws.get("prospects") or {}
        leads = ws.get("leads") or []
        customers = {
            "new_prospects": prospects.get("total", 0),
            "qualified_prospects": prospects.get("qualified", 0),
            "hot_prospects": prospects.get("high_priority", 0),
            "customers": sum(1 for l in leads if l.get("status") == "won"),
            "subscribers": sum(1 for l in leads
                               if any(i.get("type") in ("subscription", "trial")
                                      for i in (l.get("interactions") or []))),
            "renewals": sum(1 for l in leads
                            if any(i.get("type") == "renewal"
                                   for i in (l.get("interactions") or []))),
            "lost": sum(1 for l in leads if l.get("status") == "lost"),
        }
        sig = ws.get("signals") or {}
        camp_path = os.path.join(_WORKSPACE, "campaigns",
                                 "linkedin_campaigns.json")
        campaigns = 0
        if os.path.exists(camp_path):
            try:
                with open(camp_path, encoding="utf-8") as fh:
                    campaigns = len(json.load(fh).get("campaigns") or [])
            except (OSError, ValueError):
                campaigns = 0
        drafts_dir = os.path.join(_WORKSPACE, "content", "drafts")
        content_drafts = len([f for f in os.listdir(drafts_dir)
                              if f.endswith(".md")]) if os.path.isdir(drafts_dir) else 0
        queue_path = os.path.join(_WORKSPACE, "outreach", "queue.json")
        email_queued = 0
        if os.path.exists(queue_path):
            try:
                with open(queue_path, encoding="utf-8") as fh:
                    email_queued = len(json.load(fh).get("queue") or [])
            except (OSError, ValueError):
                email_queued = 0
        marketing = {
            "campaigns": campaigns,
            "linkedin_drafts": content_drafts,
            "email_queued": email_queued,
            "content_drafts": content_drafts,
            "eu_funding_records": sig.get("eu_funding_records", 0),
            "events": sig.get("events_tracked", 0),
            "partners": sum(1 for l in leads
                            if l.get("relationship_type", "customer") != "customer"),
        }

    # Copilot answers (dashboard view of the marketing copilot): who to
    # contact now + why + follow-ups due + what to publish.
    copilot = {"contact_now": [], "followups_due": [], "publish_queue": []}
    alerts_block = {"organizations_with_signals": [],
                    "high_priority_prospects": [],
                    "sms_opportunity_users": 0}
    priority_markets = {}
    if ws.get("available"):
        leads_all = ws.get("leads") or []
        hot = [l for l in leads_all if l.get("priority") == "high"
               and l.get("status", "open") not in ("won", "lost")]
        hot.sort(key=lambda l: l.get("organization") or "")
        copilot["contact_now"] = [
            {"organization": l.get("organization"),
             "why": l.get("identified_problem"),
             "service": (l.get("recommended_product") or "").replace("_", " "),
             "next_action": l.get("next_action")}
            for l in hot[:8]
        ]
        copilot["followups_due"] = (ws.get("prospects") or {}).get(
            "followups_due", [])
        drafts_dir = os.path.join(_WORKSPACE, "content", "drafts")
        if os.path.isdir(drafts_dir):
            copilot["publish_queue"] = sorted(
                f for f in os.listdir(drafts_dir) if f.endswith(".md"))
        alerts_block["high_priority_prospects"] = [
            l.get("organization") for l in hot[:10]]
        # The six priority commercial markets, with hazard context (first
        # three carry the first commercial experiment; the rest follow).
        for seg_key, label in (
                ("environmental_consulting", "Climate / ESG Consulting"),
                ("investment", "Investment / Infrastructure"),
                ("insurance", "Insurance / Risk"),
                ("governments", "Governments / Municipalities"),
                ("real_estate", "Real Estate / Engineering"),
                ("research_centers", "Research / Earth Observation / GIS")):
            seg_leads = [l for l in leads_all if l.get("segment") == seg_key]
            priority_markets[label] = [
                {"organization": l.get("organization"),
                 "country": l.get("country"),
                 "hazards": l.get("relevant_hazards"),
                 "priority": l.get("priority"),
                 "why": l.get("identified_problem"),
                 "product": (l.get("recommended_product") or "").replace("_", " "),
                 "message": l.get("recommended_message"),
                 "next_action": l.get("next_action")}
                for l in sorted(seg_leads, key=lambda x: (
                    {"high": 0, "medium": 1, "low": 2}.get(x.get("priority"), 3),
                    x.get("organization") or ""))
            ]
    # SMS opportunities: verified phones exist but SMS delivery is not
    # configured → the honest operator signal.
    from . import sms as sms_module

    alerts_block["sms_opportunity_users"] = verified_phones
    alerts_block["sms_delivery_configured"] = sms_module.sms_configured()

    return jsonify({
        "date": today,
        "today": {
            "visitors": visitors_today,
            "repeat_users": repeat_users,
            "new_users": users_today,
            "verified_accounts": verified_accounts,
            "analyses": analyses_today,
            "reports": reports_today,
            "saved_locations": saved_locations,
            "monitoring_rules": alert_rules,
            "sms_interest": funnel.get("sms_interest", 0),
            "subscriptions": sum(v for k, v in by_role.items()
                                 if k in ("subscriber", "professional",
                                          "business", "municipality", "government")),
            "new_alert_rules": rules_today,
            "analytics_events": events_today,
        },
        "accounts": {"total_users": users_total, "by_role": by_role},
        "alerts": {
            "active_rules": alert_rules,
            "verified_phones": verified_phones,
            "records_last_7d": alert_records_7d,
        },
        "customers": customers,
        "marketing": marketing,
        "copilot": copilot,
        "attention": alerts_block,
        "priority_markets": priority_markets,
        "funnel_stages": {
            "visitor": funnel.get("page_view", 0),
            "analysis": funnel.get("location_analyzed", 0),
            "repeat_analysis": repeat_analysis,
            "account": funnel.get("account_created", 0),
            "saved_location": saved_locations,
            "monitoring": alert_rules,
            "sms": verified_phones,
            "subscription": funnel.get("subscription_started", 0),
            "professional": by_role.get("professional", 0),
            "business": sum(v for k, v in by_role.items()
                            if k in ("business", "municipality", "government")),
        },
        "demand": {
            "funnel": funnel,
            "top_hazards": [{"hazard": h, "count": c} for h, c in top_hazards],
            "top_pages": [{"page": p, "count": c} for p, c in top_pages],
            "note": "Aggregate counts only — no individual visitor is "
                    "identifiable from this data.",
        },
        "targets": targets,
        "workspace": ws,
    })
