"""
Talaix operator intelligence — admin-only aggregate dashboard API.

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
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from flask import Blueprint, g, jsonify, request

from .analytics import AnalyticsStore
from .auth_api import require_role
from .cache import default_cache

admin_intel_bp = Blueprint("admin_intel", __name__, url_prefix="/api/v2")

_WORKSPACE = os.path.normpath(os.path.join(
    os.path.dirname(__file__), "..", "..", "marketing"))


def _today() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d")


def _records_ws(subdir: str) -> List[Dict]:
    """Workspace records from marketing/<subdir> (empty list when absent).
    Each record carries ``_slug`` — the file stem that addresses it in the
    marketing-ops endpoints."""
    d = os.path.join(_WORKSPACE, subdir)
    out: List[Dict] = []
    if not os.path.isdir(d):
        return out
    for name in sorted(os.listdir(d)):
        if name.endswith(".json") and name != "schema.json":
            try:
                with open(os.path.join(d, name), encoding="utf-8") as fh:
                    rec = json.load(fh)
                    if isinstance(rec, dict):
                        rec["_slug"] = name[:-5]
                    out.append(rec)
            except (OSError, ValueError):
                continue
    return out


def _overlay_ops(leads: List[Dict]) -> List[Dict]:
    """Overlay the operator's working state (marketing_store, platform DB)
    onto the file-based lead records: pipeline fields + logged interactions.
    The workspace files are the research base; the DB is the working state —
    deploys never overwrite it."""
    from .marketing_store import MarketingStore

    store = MarketingStore()
    states = {s["lead_slug"]: s for s in store.list_states()}
    db_interactions = store.list_interactions()
    by_slug: Dict[str, List[Dict]] = {}
    for i in db_interactions:
        by_slug.setdefault(i["lead_slug"], []).append(i)

    merged = []
    for lead in leads:
        slug = lead.get("_slug")
        lead["id"] = slug
        st = states.get(slug)
        if st:
            for field in ("outreach_status", "status", "priority",
                          "next_action", "next_followup"):
                if st.get(field) is not None:
                    lead[field] = st[field]
            lead["excluded"] = bool(st.get("excluded"))
            lead["exclude_reason"] = st.get("exclude_reason")
            lead["ops_updated_at"] = st.get("updated_at")
        extra = [{"date": i["date"], "type": i["type"], "summary": i["summary"]}
                 for i in by_slug.get(slug, [])]
        if extra:
            lead["interactions"] = extra + (lead.get("interactions") or [])
        merged.append(lead)
    return merged


def _workspace_section() -> Dict[str, Any]:
    """Marketing workspace summary, or an honest unavailable marker."""
    if not os.path.isdir(_WORKSPACE):
        return {"available": False,
                "note": "The marketing workspace is not part of this "
                        "deployment (operator-local by design)."}

    leads = _overlay_ops(_records_ws("leads"))
    signals = _records_ws("signals")
    events = _records_ws("events")
    eu_funding = _records_ws("eu_funding")
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
            {"id": l.get("id"),
             "organization": l.get("organization"),
             "segment": l.get("segment"), "country": l.get("country"),
             "identified_problem": l.get("identified_problem"),
             "hazards": l.get("relevant_hazards"),
             # Raw field names carried through for the copilot, priority
             # markets and the hazard radar, which all read the lead-record
             # schema (relevant_hazards / recommended_product /
             # recommended_message / source / date_checked).
             "relevant_hazards": l.get("relevant_hazards"),
             "recommended_product": l.get("recommended_product"),
             "recommended_message": l.get("recommended_message"),
             "decision_maker_role": l.get("decision_maker_role"),
             "source": l.get("source"),
             "date_checked": l.get("date_checked"),
             "priority": l.get("priority"), "urgency": l.get("urgency"),
             "outreach_status": l.get("outreach_status", "researched"),
             "relationship_type": l.get("relationship_type", "customer"),
             "status": l.get("status", "open"),
             "excluded": bool(l.get("excluded")),
             "exclude_reason": l.get("exclude_reason"),
             "last_contact": l.get("last_contact"),
             "next_action": l.get("next_action"),
             "next_followup": l.get("next_followup"),
             "website": l.get("website"),
             "interactions": l.get("interactions") or []}
            for l in leads
        ],
        "relationships": interactions,
    }


# ---------------------------------------------------------------------------
# Contact map (خارطة التواصل): country-level positions for workspace leads.
# Positions are honest country centroids/capitals — the UI labels them as
# country-level, never as exact addresses.
# ---------------------------------------------------------------------------

COUNTRY_CENTROIDS = {
    "LU": (49.61, 6.13), "BE": (50.85, 4.35), "NL": (52.37, 4.90),
    "DE": (52.52, 13.40), "FR": (48.86, 2.35), "CH": (46.95, 7.45),
    "IT": (41.90, 12.50), "ES": (40.42, -3.70), "PT": (38.72, -9.14),
    "GB": (51.51, -0.13), "IE": (53.35, -6.26), "DK": (55.68, 12.57),
    "SE": (59.33, 18.07), "NO": (59.91, 10.75), "FI": (60.17, 24.94),
    "AT": (48.21, 16.37), "CZ": (50.08, 14.44), "PL": (52.23, 21.01),
    "GR": (37.98, 23.73), "HR": (45.81, 15.98), "RO": (44.43, 26.10),
    "BG": (42.70, 23.32), "US": (38.90, -77.04), "CA": (45.42, -75.70),
    "JP": (35.68, 139.69), "KR": (37.57, 126.98), "CN": (39.90, 116.40),
    "SG": (1.35, 103.82), "MY": (3.14, 101.69), "ID": (-6.21, 106.85),
    "PH": (14.60, 120.98), "IN": (28.61, 77.21), "AE": (25.20, 55.27),
    "AU": (-33.87, 151.21), "BR": (-15.79, -47.88), "ZA": (-25.75, 28.19),
}

_PRIORITY_W = {"high": 50, "medium": 25, "low": 10}
_URGENCY_W = {"high": 35, "medium": 20, "low": 5}
_OUTREACH_W = {"opportunity": 15, "responded": 12, "contacted": 8,
               "qualified": 5, "draft_prepared": 5, "researched": 0}


def _lead_score(lead: Dict) -> int:
    """Transparent rule-based prospect score (0–100): priority + urgency +
    outreach progress. No personal data, no opaque model — the components
    are visible in the UI next to the score."""
    score = (_PRIORITY_W.get(str(lead.get("priority") or "").lower(), 10)
             + _URGENCY_W.get(str(lead.get("urgency") or "").lower(), 5)
             + _OUTREACH_W.get(str(lead.get("outreach_status") or "researched").lower(), 0))
    return min(100, score)


def _leads_map(leads: List[Dict]) -> List[Dict]:
    """Country-level map markers for the Commercial Center prospect map."""
    out = []
    for l in leads:
        if l.get("status", "open") in ("won", "lost") or l.get("excluded"):
            continue
        cc = str(l.get("country") or "").strip().upper()
        if cc not in COUNTRY_CENTROIDS:
            continue
        lat, lon = COUNTRY_CENTROIDS[cc]
        out.append({
            "organization": l.get("organization"),
            "segment": l.get("segment"),
            "country": cc,
            "lat": lat, "lon": lon,
            "priority": l.get("priority"),
            "outreach_status": l.get("outreach_status", "researched"),
            "score": _lead_score(l),
            "recommended_product": l.get("recommended_product"),
            "next_action": l.get("next_action"),
        })
    out.sort(key=lambda m: -(m["score"] or 0))
    return out


# ---------------------------------------------------------------------------
# Segmentation (sector × country) and campaign correspondence plans
# ---------------------------------------------------------------------------

# The operator's six target sectors (the for-* pages). Segment keys come
# from marketing/segments/segments.json; labels are the public page names.
_TARGET_SECTORS = [
    ("banking", "Banks & lenders"),
    ("environmental_consulting", "Consultants"),
    ("investment", "Investors"),
    ("insurance", "Insurance"),
    ("real_estate", "Real estate"),
    ("governments", "Government"),
]
# Municipal leads belong to the Government target sector.
_SECTOR_ALIAS = {"municipalities": "governments",
                 "municipal_climate_adaptation": "governments"}

_STALE_DAYS = 30


def _segment_doc() -> Dict:
    path = os.path.join(_WORKSPACE, "segments", "segments.json")
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _target_sector(segment_key: str) -> Optional[str]:
    if segment_key in dict(_TARGET_SECTORS):
        return segment_key
    return _SECTOR_ALIAS.get(segment_key)


def _segmentation(leads: List[Dict]) -> List[Dict]:
    """Sector × country matrix over the operator's six target sectors."""
    doc = _segment_doc().get("segments") or {}
    out = []
    for key, label in _TARGET_SECTORS:
        seg_leads = [l for l in leads
                     if _target_sector(l.get("segment") or "") == key]
        countries: Dict[str, List[str]] = {}
        for l in seg_leads:
            cc = (l.get("country") or "?").upper()
            countries.setdefault(cc, []).append(l.get("id") or "")
        seg_doc = doc.get(key) or {}
        out.append({
            "key": key,
            "label": label,
            "count": len(seg_leads),
            "active_count": sum(1 for l in seg_leads
                                if not l.get("excluded")
                                and l.get("status", "open") not in ("won", "lost")),
            "countries": [{"country": cc, "count": len(ids), "leads": sorted(ids)}
                          for cc, ids in sorted(countries.items(),
                                                key=lambda kv: -len(kv[1]))],
            "offer": seg_doc.get("offer"),
            "cta": seg_doc.get("cta"),
            "outreach_style": seg_doc.get("outreach_style"),
            "decision_maker_roles": seg_doc.get("decision_maker_roles"),
        })
    return out


def _latest_signals(signals: List[Dict]) -> Dict[str, Dict]:
    """Latest signal per organization + an honest staleness flag (the
    record was last checked more than _STALE_DAYS ago)."""
    today = _today()
    latest: Dict[str, Dict] = {}
    for s in signals:
        org = s.get("organization")
        if not org:
            continue
        cur = latest.get(org)
        if cur is None or (s.get("date_observed") or "") > (cur.get("date_observed") or ""):
            checked = s.get("date_checked") or ""
            stale = bool(checked) and checked < (
                datetime.utcnow() - timedelta(days=_STALE_DAYS)).strftime("%Y-%m-%d")
            latest[org] = {
                "signal_type": s.get("signal_type"),
                "signal_strength": s.get("signal_strength"),
                "activity_level": s.get("activity_level"),
                "date_observed": s.get("date_observed"),
                "date_checked": checked,
                "stale": stale,
                "source_url": s.get("source_url"),
                "recommended_action": s.get("recommended_action"),
            }
    return latest


def _campaign_plans(leads: List[Dict], signals: List[Dict]) -> List[Dict]:
    """Per campaign: the goal, the matched leads (sector-matched, active,
    never competitors/excluded), and the correspondence plan per lead —
    who to contact (decision-maker role), how (channel/website), with what
    message, and when (next action / follow-up)."""
    camp_path = os.path.join(_WORKSPACE, "campaigns", "linkedin_campaigns.json")
    campaigns = []
    if os.path.isfile(camp_path):
        try:
            with open(camp_path, encoding="utf-8") as fh:
                campaigns = json.load(fh).get("campaigns") or []
        except (OSError, ValueError):
            campaigns = []

    latest_sig = _latest_signals(signals)
    active = [l for l in leads
              if not l.get("excluded")
              and l.get("status", "open") not in ("won", "lost")]

    plans = []
    for c in campaigns:
        aud_segments = set((c.get("audience") or {}).get("segments") or [])
        matched = [l for l in active
                   if (l.get("segment") in aud_segments
                       or _target_sector(l.get("segment") or "") in aud_segments)]
        matched.sort(key=lambda l: (
            {"high": 0, "medium": 1, "low": 2}.get(l.get("priority"), 3),
            l.get("organization") or ""))
        plans.append({
            "id": c.get("id"),
            "name": c.get("name"),
            "objective": c.get("objective"),
            "cta": c.get("cta"),
            "landing_page": c.get("landing_page"),
            "follow_up": c.get("follow_up"),
            "conversion_goal": c.get("conversion_goal"),
            "matched_count": len(matched),
            "leads": [{
                "id": l.get("id"),
                "organization": l.get("organization"),
                "country": l.get("country"),
                "priority": l.get("priority"),
                "outreach_status": l.get("outreach_status", "researched"),
                "decision_maker_role": l.get("decision_maker_role"),
                "contact_url": l.get("website"),
                "recommended_message": l.get("recommended_message"),
                "next_action": l.get("next_action"),
                "next_followup": l.get("next_followup"),
                "activity": latest_sig.get(l.get("organization")),
            } for l in matched],
        })
    return plans


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
               and l.get("status", "open") not in ("won", "lost")
               and not l.get("excluded")]
        hot.sort(key=lambda l: l.get("organization") or "")
        copilot["contact_now"] = [
            {"organization": l.get("organization"),
             "segment": l.get("segment"),
             "country": l.get("country"),
             "why": l.get("identified_problem"),
             "hazards": l.get("relevant_hazards"),
             "service": (l.get("recommended_product") or "").replace("_", " "),
             "message": l.get("recommended_message"),
             "next_action": l.get("next_action"),
             "next_followup": l.get("next_followup")}
            for l in hot[:8]
        ]
        copilot["followups_due"] = (ws.get("prospects") or {}).get(
            "followups_due", [])
        drafts_dir = os.path.join(_WORKSPACE, "content", "drafts")
        if os.path.isdir(drafts_dir):
            copilot["publish_queue"] = sorted(
                f for f in os.listdir(drafts_dir) if f.endswith(".md"))
        # Today's workspace activity (new leads + interactions dated today).
        copilot["new_leads_today"] = [
            l.get("organization") for l in leads_all
            if (l.get("interactions") or [{}])[0].get("date") == today
            and (l.get("interactions") or [{}])[0].get("type") == "discovered"
        ]
        copilot["interactions_today"] = [
            {"organization": l.get("organization"),
             "type": i.get("type"), "summary": i.get("summary")}
            for l in leads_all for i in (l.get("interactions") or [])
            if i.get("date") == today
        ]
        # Campaign summary for the workspace view.
        camp_path = os.path.join(_WORKSPACE, "campaigns",
                                 "linkedin_campaigns.json")
        copilot["campaigns"] = []
        if os.path.exists(camp_path):
            try:
                with open(camp_path, encoding="utf-8") as fh:
                    for c in json.load(fh).get("campaigns") or []:
                        copilot["campaigns"].append({
                            "id": c.get("id"), "name": c.get("name"),
                            "cta": c.get("cta"),
                            "conversion_goal": c.get("conversion_goal")})
            except (OSError, ValueError):
                copilot["campaigns"] = []
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

    # Hazard-driven opportunities (the radar): current snapshot × workspace
    # leads. The snapshot is read from the local cache only — a rebuild is
    # never triggered from the admin endpoint.
    hazard_opportunities = []
    hazard_areas = []
    if ws.get("available"):
        from .hazard_market import build_opportunities

        snapshot = default_cache().get("risk_snapshot:current")
        entries = (snapshot or {}).get("entries") or []
        hazard_areas = [
            {"area": e.get("name"), "risk_class": e.get("risk_class")}
            for e in entries
        ]
        seg_doc_path = os.path.join(_WORKSPACE, "segments", "segments.json")
        product_matching = {}
        if os.path.exists(seg_doc_path):
            try:
                with open(seg_doc_path, encoding="utf-8") as fh:
                    product_matching = json.load(fh).get("product_matching") or {}
            except (OSError, ValueError):
                product_matching = {}
        hazard_opportunities = build_opportunities(
            ws.get("leads") or [], entries, product_matching)

    # Funding & Procurement Radar: platform KB programmes + EU funding
    # ledger + procurement ledger — each with source, date_checked,
    # eligibility, geography, sector, hazard, fit and next action.
    funding_radar: Dict[str, Any] = {"programmes": [], "eu_funding": [],
                                     "procurement": []}
    kb_path = os.path.join(os.path.dirname(_WORKSPACE), "config",
                           "funding_knowledge.json")
    if os.path.exists(kb_path):
        try:
            with open(kb_path, encoding="utf-8") as fh:
                kb = json.load(fh)
            funding_radar["programmes"] = [
                {"name": p.get("name"),
                 "funding_body": p.get("funding_body"),
                 "funding_type": p.get("funding_type"),
                 "jurisdiction": p.get("jurisdiction"),
                 "hazards": p.get("hazards"),
                 "eligibility": p.get("eligibility"),
                 "deadline": p.get("deadline"),
                 "official_url": p.get("official_url"),
                 "fit": p.get("hydrashield_relevance"),
                 "next_action": p.get("recommended_action"),
                 "date_checked": p.get("date_checked")}
                for p in kb.get("programmes") or []
            ]
        except (OSError, ValueError):
            funding_radar["programmes"] = []
    if ws.get("available"):
        funding_radar["eu_funding"] = [
            {"programme": r.get("programme"), "call": r.get("call"),
             "institution": r.get("institution"),
             "official_source": r.get("official_source"),
             "deadline": r.get("deadline"),
             "sector": r.get("sector"), "hazards": r.get("hazards"),
             "fit": r.get("hydrashield_relevance"),
             "next_action": r.get("recommended_strategy"),
             "date_checked": r.get("date_checked"),
             "status": r.get("status", "watching")}
            for r in _records_ws("eu_funding")
        ]
        funding_radar["procurement"] = [
            {"title": r.get("title"), "type": r.get("type"),
             "contracting_authority": r.get("contracting_authority"),
             "geography": r.get("geography"), "sector": r.get("sector"),
             "hazards": r.get("hazards"), "eligibility": r.get("eligibility"),
             "deadline": r.get("deadline"),
             "official_url": r.get("official_url"),
             "fit": r.get("hydrashield_relevance"),
             "next_action": r.get("next_action"),
             "date_checked": r.get("date_checked"),
             "status": r.get("status", "watching")}
            for r in _records_ws("procurement")
        ]

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
        "hazard_opportunities": hazard_opportunities,
        "hazard_areas": hazard_areas,
        "funding_radar": funding_radar,
        "funnel_stages": {
            "visitor": funnel.get("page_view", 0),
            "cta_viewed": funnel.get("cta_viewed", 0),
            "cta_clicked": funnel.get("cta_clicked", 0),
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
        "leads_map": _leads_map(ws.get("leads") or []) if ws.get("available") else [],
        "leads_map_note": "Country-level positions (capital/centroid) — "
                          "never exact addresses. Score is rule-based "
                          "(priority + urgency + outreach progress).",
        # Sector × country segmentation and per-campaign correspondence
        # plans (competitors/excluded never enter a plan).
        "segmentation": _segmentation(ws.get("leads") or []) if ws.get("available") else [],
        "campaign_plans": _campaign_plans(ws.get("leads") or [],
                                          _records_ws("signals")) if ws.get("available") else [],
    })


# ---------------------------------------------------------------------------
# Inbound contact messages (Commercial Center leads inbox)
# ---------------------------------------------------------------------------

@admin_intel_bp.get("/admin/contacts")
@require_role("admin")
def admin_contacts():
    """Inbound contact-form messages, newest first (operator-only)."""
    from .contact_store import ContactStore

    return jsonify({"contacts": ContactStore().list_messages()})


@admin_intel_bp.patch("/admin/contacts/<int:message_id>")
@require_role("admin")
def admin_contact_status(message_id: int):
    """Move an inbound message through the pipeline (new → contacted →
    qualified → closed)."""
    from .contact_store import ContactStore

    data = request.get_json(silent=True) or {}
    status = str(data.get("status") or "").strip()
    if not ContactStore().set_status(message_id, status):
        return jsonify({"error": "Unknown message or invalid status",
                        "status": 404}), 404
    return jsonify({"id": message_id, "status": status})


# ---------------------------------------------------------------------------
# Campaign performance endpoint
# ---------------------------------------------------------------------------

@admin_intel_bp.get("/admin/campaigns")
@require_role("admin")
def admin_campaigns():
    """Campaign performance dashboard data.

    Aggregates per-campaign metrics from the marketing workspace:
    - leads targeted per campaign
    - outreach status distribution
    - engagement rate
    - top countries
    - conversion funnel
    - recommendations
    """
    campaigns_file = os.path.join(_WORKSPACE, "campaigns", "linkedin_campaigns.json")
    segments_file = os.path.join(_WORKSPACE, "segments", "segments.json")

    campaigns = []
    if os.path.isfile(campaigns_file):
        try:
            with open(campaigns_file, encoding="utf-8") as fh:
                campaigns = json.load(fh).get("campaigns", [])
        except (OSError, ValueError):
            pass

    segments = {}
    if os.path.isfile(segments_file):
        try:
            with open(segments_file, encoding="utf-8") as fh:
                segments = json.load(fh).get("segments", {})
        except (OSError, ValueError):
            pass

    leads = _records_ws("leads")

    results = []
    all_engaged = 0
    all_targeted = 0

    for c in campaigns:
        target_segs = set(c.get("audience", {}).get("segments", []))
        c_leads = [l for l in leads if l.get("segment") in target_segs]

        # Funnel
        funnel = Counter(l.get("outreach_status", "unknown") for l in c_leads)

        # Engagement
        engaged = sum(
            1 for l in c_leads
            if l.get("outreach_status") in ("contacted", "responded", "opportunity")
        )
        all_engaged += engaged
        all_targeted += len(c_leads)

        # Countries
        countries = Counter(l.get("country", "?") for l in c_leads).most_common(5)

        # Priorities
        priorities = Counter(l.get("priority", "unknown") for l in c_leads)

        # Recent interactions (last 30 days)
        month_ago = (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%d")
        recent = 0
        for l in c_leads:
            for ix in l.get("interactions", []):
                if ix.get("date", "") >= month_ago:
                    recent += 1

        results.append({
            "id": c.get("id", "?"),
            "name": c.get("name", "?"),
            "target_segments": list(target_segs),
            "total_target_leads": len(c_leads),
            "funnel": dict(funnel),
            "engaged_count": engaged,
            "engagement_rate": round(engaged / max(len(c_leads), 1), 3),
            "recent_interactions": recent,
            "priority_distribution": dict(priorities),
            "top_countries": [{"country": co, "count": ct} for co, ct in countries],
            "conversion_goal": c.get("conversion_goal", []),
            "landing_page": c.get("landing_page", ""),
        })

    results.sort(key=lambda x: x["engagement_rate"], reverse=True)

    # Recommendations
    recommendations = []
    for r in results:
        if r["engagement_rate"] > 0.3:
            recommendations.append({
                "campaign_id": r["id"],
                "campaign_name": r["name"],
                "type": "boost",
                "reason": f"High engagement ({r['engagement_rate']:.0%}) — consider increasing output",
            })
        elif r["total_target_leads"] > 0 and r["engagement_rate"] < 0.05:
            recommendations.append({
                "campaign_id": r["id"],
                "campaign_name": r["name"],
                "type": "review",
                "reason": f"Low engagement ({r['engagement_rate']:.0%}) — review messaging or targeting",
            })

    # Overall engagement rate
    overall_rate = all_engaged / max(all_targeted, 1)

    return jsonify({
        "generated_at": datetime.utcnow().isoformat(),
        "total_campaigns": len(campaigns),
        "overall_engagement_rate": round(overall_rate, 3),
        "total_targeted_leads": all_targeted,
        "total_engaged_leads": all_engaged,
        "campaigns": results,
        "recommendations": recommendations,
    })


# ---------------------------------------------------------------------------
# Marketing operations — the operator works the pipeline from the UI.
# Writes live in the platform DB (marketing_store), never in the read-only
# workspace mount; every change is audited.
# ---------------------------------------------------------------------------

def _lead_slugs() -> set:
    """The slugs of existing workspace leads — the addressable set for the
    marketing-ops endpoints (unknown slugs are honest 404s, never silently
    created orphan state)."""
    return {r.get("_slug") for r in _records_ws("leads") if r.get("_slug")}


@admin_intel_bp.patch("/admin/leads/<lead_slug>")
@require_role("admin")
def admin_lead_update(lead_slug: str):
    """Update pipeline fields of a lead (outreach_status / status /
    priority / next_action / next_followup / excluded). Sparse overlay —
    only the changed fields are stored. 404 for unknown lead slugs."""
    from .marketing_store import MarketingStore

    if lead_slug not in _lead_slugs():
        return jsonify({"error": f"Unknown lead '{lead_slug}'",
                        "status": 404}), 404
    data = request.get_json(silent=True) or {}
    fields = {k: data[k] for k in
              ("outreach_status", "status", "priority",
               "next_action", "next_followup", "excluded", "exclude_reason")
              if k in data}
    result = MarketingStore().update_state(lead_slug, **fields)
    if result is None:
        return jsonify({"error": "Invalid field value",
                        "status": 400}), 400
    from .accounts import UserStore

    UserStore().audit(g.current_user["id"], "lead_update",
                      target=lead_slug, meta=fields)
    return jsonify({"lead": result})


@admin_intel_bp.post("/admin/leads/<lead_slug>/interactions")
@require_role("admin")
def admin_lead_interaction(lead_slug: str):
    """Log an interaction on a lead (email/call/meeting/demo/note/…).
    The entry joins the lead's relationship history immediately."""
    from .marketing_store import MarketingStore

    if lead_slug not in _lead_slugs():
        return jsonify({"error": f"Unknown lead '{lead_slug}'",
                        "status": 404}), 404
    data = request.get_json(silent=True) or {}
    result = MarketingStore().add_interaction(
        lead_slug,
        summary=data.get("summary"),
        type=data.get("type") or "note",
        date=data.get("date"),
    )
    if result is None:
        return jsonify({"error": "Invalid type, bad date or empty summary",
                        "status": 400}), 400
    from .accounts import UserStore

    UserStore().audit(g.current_user["id"], "lead_interaction",
                      target=lead_slug,
                      meta={"type": result["type"], "date": result["date"]})
    return jsonify({"interaction": result}), 201
