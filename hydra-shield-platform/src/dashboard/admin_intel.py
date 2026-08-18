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
    today = _today()
    followups_due = [
        {"organization": l.get("organization"),
         "next_followup": l.get("next_followup"),
         "next_action": l.get("next_action")}
        for l in leads
        if l.get("next_followup") and l["next_followup"] <= today
        and l.get("status", "open") not in ("won", "lost")
    ]
    return {
        "available": True,
        "leads": [
            {"organization": l.get("organization"),
             "segment": l.get("segment"), "country": l.get("country"),
             "identified_problem": l.get("identified_problem"),
             "hazards": l.get("relevant_hazards"),
             "priority": l.get("priority"), "urgency": l.get("urgency"),
             "outreach_status": l.get("outreach_status", "researched"),
             "status": l.get("status", "open"),
             "last_contact": l.get("last_contact"),
             "next_action": l.get("next_action"),
             "interactions": l.get("interactions") or []}
            for l in leads
        ],
        "signals": [
            {"organization": s.get("organization"), "sector": s.get("sector"),
             "signal_type": s.get("signal_type"),
             "signal_strength": s.get("signal_strength"),
             "date_observed": s.get("date_observed"),
             "source_url": s.get("source_url")}
            for s in signals
        ],
        "events": [
            {"event": e.get("event"), "location": e.get("location"),
             "date": e.get("date"), "relevance": e.get("relevance"),
             "status": e.get("status", "watching")}
            for e in events
        ],
        "followups_due": followups_due,
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

    return jsonify({
        "date": today,
        "today": {
            "new_users": users_today,
            "new_alert_rules": rules_today,
            "analytics_events": events_today,
        },
        "accounts": {"total_users": users_total, "by_role": by_role},
        "alerts": {
            "active_rules": alert_rules,
            "verified_phones": verified_phones,
            "records_last_7d": alert_records_7d,
        },
        "demand": {
            "funnel": funnel,
            "top_hazards": [{"hazard": h, "count": c} for h, c in top_hazards],
            "top_pages": [{"page": p, "count": c} for p, c in top_pages],
            "note": "Aggregate counts only — no individual visitor is "
                    "identifiable from this data.",
        },
        "workspace": _workspace_section(),
    })
