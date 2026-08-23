#!/usr/bin/env python3
"""Talaix marketing copilot — the operator-facing entry point to the
commercial-intelligence workspace (marketing/).

Reads only the repository (and, for `demand`, the local product-analytics
SQLite DB); never writes, never sends. Fully offline.

Usage (from the platform directory):

    python scripts/marketing_status.py            # workspace status + integrity
    python scripts/marketing_status.py signals    # newest commercial signals
    python scripts/marketing_status.py sectors    # sector activity from signals
    python scripts/marketing_status.py events     # events radar, ranked
    python scripts/marketing_status.py priorities # who to contact, why, with what
    python scripts/marketing_status.py followups  # follow-ups due / overdue
    python scripts/marketing_status.py content    # drafts awaiting review/publish
    python scripts/marketing_status.py demand     # aggregate product demand signals
    python scripts/marketing_status.py lessons    # what past outreach taught us
    python scripts/marketing_status.py morning    # morning operator briefing
    python scripts/marketing_status.py evening    # evening record checklist

The workspace is the memory (marketing/README.md); this tool is the
orientation layer. It invents nothing: empty ledgers produce honest empty
states and the next action to fill them.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date

ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
MARKETING = os.path.join(ROOT, "marketing")
# The copilot imports platform modules (e.g. src.dashboard.hazard_market);
# make the platform root importable regardless of invocation directory.
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

LEAD_STATUSES = ["researched", "qualified", "draft_prepared", "contacted",
                 "responded", "opportunity", "closed_lost"]
DRAFT_STATUSES = ["draft", "reviewed", "queued", "published", "retired"]
INTERACTION_TYPES = ["discovered", "researched", "qualified", "contacted",
                     "replied", "meeting", "demo", "proposal",
                     "report_requested", "trial", "customer", "subscription",
                     "renewal", "lost", "follow_up"]
REQUIRED_LEAD_FIELDS = ("organization", "segment", "country", "website",
                        "source", "date_checked")
REQUIRED_SIGNAL_FIELDS = ("id", "organization", "sector", "country",
                          "hazards", "signal_type", "signal_strength",
                          "source", "source_url", "date_observed",
                          "date_checked", "evidence_type", "confidence")
REQUIRED_EVENT_FIELDS = ("event", "organizer", "location", "date", "url",
                         "source", "sectors", "relevance",
                         "relevance_reason", "date_checked")
_PRIORITY_RANK = {"high": 0, "medium": 1, "low": 2}
_STRENGTH_RANK = {"strong": 0, "moderate": 1, "weak": 2}
_RELEVANCE_RANK = {"high": 0, "medium": 1, "low": 2}
_ACTIVITY_RANK = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}


def _load_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _records(subdir, skip=()):
    """All JSON records in a workspace subdirectory (newest filename first)."""
    d = os.path.join(MARKETING, subdir)
    out = []
    if not os.path.isdir(d):
        return out
    for name in sorted(os.listdir(d)):
        if name.endswith(".json") and name not in skip and name != "schema.json":
            out.append((name, _load_json(os.path.join(d, name))))
    return out


def _segments():
    return _load_json(os.path.join(MARKETING, "segments", "segments.json"))["segments"]


def _leads():
    return _records("leads")


def _signals():
    return _records("signals")


def _events():
    return _records("events")


def _campaigns():
    path = os.path.join(MARKETING, "campaigns", "linkedin_campaigns.json")
    return _load_json(path)["campaigns"] if os.path.exists(path) else []


def _drafts():
    d = os.path.join(MARKETING, "content", "drafts")
    out = []
    if os.path.isdir(d):
        for name in sorted(os.listdir(d)):
            if not name.endswith(".md"):
                continue
            head = open(os.path.join(d, name), encoding="utf-8").read(600)
            meta = {}
            for line in head.splitlines():
                if line.startswith("status:"):
                    meta["status"] = line.split(":", 1)[1].strip()
                if line.startswith("segment:"):
                    meta["segment"] = line.split(":", 1)[1].strip()
                if line.startswith("cta:"):
                    meta["cta"] = line.split(":", 1)[1].strip().strip('"')
            out.append((name, meta))
    return out


# ---------------------------------------------------------------------------
# Integrity
# ---------------------------------------------------------------------------

def workspace_integrity():
    """Validate the workspace against the honesty contract. Returns
    (segments, leads, signals, events, campaigns, problems)."""
    problems = []
    segments = _segments()
    vocab_hazards = {"wildfire", "flood", "drought", "heat", "wind", "coastal"}

    leads = []
    for name, lead in _leads():
        leads.append((name, lead))
        for field in REQUIRED_LEAD_FIELDS:
            if not lead.get(field):
                problems.append(f"lead {name}: missing required field '{field}'")
        if lead.get("segment") and lead["segment"] not in segments:
            problems.append(f"lead {name}: unknown segment '{lead['segment']}'")
        status = lead.get("outreach_status", "researched")
        if status not in LEAD_STATUSES:
            problems.append(f"lead {name}: unknown outreach_status '{status}'")
        for ix, inter in enumerate(lead.get("interactions") or []):
            if inter.get("type") not in INTERACTION_TYPES:
                problems.append(
                    f"lead {name}: interaction {ix} unknown type "
                    f"'{inter.get('type')}'")
            if not inter.get("date") or not inter.get("summary"):
                problems.append(f"lead {name}: interaction {ix} lacks date/summary")

    signals = []
    for name, sig in _signals():
        signals.append((name, sig))
        for field in REQUIRED_SIGNAL_FIELDS:
            if not sig.get(field):
                problems.append(f"signal {name}: missing required field '{field}'")
        if sig.get("sector") and sig["sector"] not in segments:
            problems.append(f"signal {name}: unknown sector '{sig['sector']}'")
        if sig.get("hazards") and not set(sig["hazards"]) <= vocab_hazards:
            problems.append(f"signal {name}: unknown hazard(s)")
        # The no-fabricated-spend rule, machine-enforced.
        for key in sig:
            if any(tok in key.lower() for tok in ("spend", "budget", "cost_eur",
                                                  "ad_spend", "expenditure")):
                problems.append(
                    f"signal {name}: field '{key}' looks like an advertising-spend "
                    f"claim — prohibited without an authoritative published figure")

    events = []
    for name, ev in _events():
        events.append((name, ev))
        for field in REQUIRED_EVENT_FIELDS:
            if not ev.get(field):
                problems.append(f"event {name}: missing required field '{field}'")
        if ev.get("sectors") and not set(ev["sectors"]) <= set(segments):
            problems.append(f"event {name}: unknown sector(s)")

    campaigns = _campaigns()
    for camp in campaigns:
        for seg in camp.get("audience", {}).get("segments", []):
            if seg not in segments:
                problems.append(f"campaign {camp['id']}: unknown segment '{seg}'")
    return segments, leads, signals, events, campaigns, problems


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

def cmd_status() -> int:
    segments, leads, signals, events, campaigns, problems = workspace_integrity()
    print("HYDRASHIELD MARKETING STATUS")
    print("=" * 60)
    print(f"Segments defined: {len(segments)}")
    by_status = {}
    for _n, lead in leads:
        s = lead.get("outreach_status", "researched")
        by_status[s] = by_status.get(s, 0) + 1
    print(f"Leads: {len(leads)}  " +
          " ".join(f"{k}={v}" for k, v in sorted(by_status.items())))
    print(f"Commercial signals: {len(signals)}")
    print(f"Events tracked: {len(events)}")
    print(f"Campaigns: {len(campaigns)} " +
          (f"({', '.join(c['id'] for c in campaigns)})" if campaigns else ""))
    drafts = _drafts()
    print(f"Content drafts: {len(drafts)}")
    for d, meta in drafts:
        print(f"  - {d} [{meta.get('status', 'draft')}]")
    queue = _load_json(os.path.join(MARKETING, "outreach", "queue.json")).get("queue", [])
    print(f"Outreach queue: {len(queue)} entr(ies)")
    print("-" * 60)
    if problems:
        print("INTEGRITY PROBLEMS:")
        for p in problems:
            print(f"  ! {p}")
        return 1
    print("Next actions (derived, not invented):")
    if not leads:
        print("  · No leads yet — run lead discovery per MARKETING_INTELLIGENCE.md §4")
    if not signals:
        print("  · No commercial signals yet — see COMMERCIAL_INTELLIGENCE.md §2")
    if not queue:
        print("  · Outreach queue empty — qualify a lead and prepare a draft")
    unpublished = [d for d, m in drafts if m.get("status") != "published"]
    if unpublished:
        print(f"  · {len(unpublished)} draft(s) awaiting human review/publish")
    if leads and not problems:
        print("  · Run `priorities` and `followups` for today's operator actions")
    return 0


def cmd_signals() -> int:
    signals = _signals()
    print("NEW COMMERCIAL SIGNALS")
    print("=" * 60)
    if not signals:
        print("None recorded. Research path: docs/COMMERCIAL_INTELLIGENCE.md §2.")
        return 0
    ordered = sorted(signals, key=lambda kv: (
        kv[1].get("date_observed", ""), _STRENGTH_RANK.get(
            kv[1].get("signal_strength"), 3)), reverse=False)
    ordered.sort(key=lambda kv: kv[1].get("date_observed", ""), reverse=True)
    for _n, s in ordered:
        print(f"· {s.get('date_observed')}  {s.get('organization')} "
              f"({s.get('sector')}, {s.get('country')})")
        print(f"    {s.get('signal_type')} [{s.get('signal_strength')}] — "
              f"{s.get('evidence_type')}, confidence {s.get('confidence')}")
        print(f"    source: {s.get('source_url')} (checked {s.get('date_checked')})")
        if s.get("recommended_action"):
            print(f"    → {s['recommended_action']}")
    return 0


def cmd_sectors() -> int:
    signals = _signals()
    print("SECTOR ACTIVITY (from recorded signals)")
    print("=" * 60)
    if not signals:
        print("No signals recorded — sector activity is unknown, not zero.")
        return 0
    agg = {}
    for _n, s in signals:
        sec = s.get("sector", "?")
        a = agg.setdefault(sec, {"signals": 0, "activity": 0, "hazards": set()})
        a["signals"] += 1
        a["activity"] += _ACTIVITY_RANK.get(s.get("activity_level"), 0)
        a["hazards"].update(s.get("hazards") or [])
    for sec, a in sorted(agg.items(), key=lambda kv: (-kv[1]["signals"], -kv[1]["activity"])):
        print(f"· {sec}: {a['signals']} signal(s), hazards: "
              f"{', '.join(sorted(a['hazards'])) or '—'}")
    return 0


def cmd_events() -> int:
    events = _events()
    print("EVENTS RADAR")
    print("=" * 60)
    if not events:
        print("No events tracked. Add them from official event pages "
              "(marketing/events/schema.json).")
        return 0
    active = [(n, e) for n, e in events
              if e.get("status", "watching") in ("watching", "attending")]
    active.sort(key=lambda kv: (_RELEVANCE_RANK.get(kv[1].get("relevance"), 3),
                                kv[1].get("date", "")))
    for _n, e in active:
        print(f"· {e.get('event')} — {e.get('location')}, {e.get('date')} "
              f"[{e.get('relevance')}, {e.get('status', 'watching')}]")
        print(f"    {e.get('relevance_reason')}")
        print(f"    {e.get('url')} (checked {e.get('date_checked')})")
    return 0


def cmd_priorities() -> int:
    leads = _leads()
    print("TODAY'S PRIORITY PROSPECTS")
    print("=" * 60)
    if not leads:
        print("No leads yet. Qualification path: docs/COMMERCIAL_INTELLIGENCE.md §4.")
        return 0
    ordered = sorted(leads, key=lambda kv: (
        _PRIORITY_RANK.get(kv[1].get("priority"), 3),
        kv[1].get("organization", "")))
    for _n, lead in ordered:
        if lead.get("status", "open") in ("won", "lost"):
            continue
        print(f"· {lead.get('organization')} [{lead.get('priority', '?')}] "
              f"— {lead.get('segment')}, {lead.get('country')}")
        if lead.get("identified_problem"):
            print(f"    why now: {lead['identified_problem']}")
        if lead.get("recommended_product"):
            print(f"    present: {lead['recommended_product']}")
        if lead.get("evidence"):
            print(f"    evidence: {lead['evidence']}")
        if lead.get("next_action"):
            print(f"    → {lead['next_action']}")
    return 0


def cmd_followups() -> int:
    leads = _leads()
    print("FOLLOW-UPS DUE")
    print("=" * 60)
    if not leads:
        print("No leads yet — nothing to follow up.")
        return 0
    today = date.today().isoformat()
    due = []
    for _n, lead in leads:
        nf = lead.get("next_followup")
        if nf and nf <= today and lead.get("status", "open") not in ("won", "lost"):
            due.append((nf, lead))
    if not due:
        print("None due. (Leads with a next_followup date appear here when due.)")
        return 0
    for nf, lead in sorted(due):
        print(f"· {nf}  {lead.get('organization')} — "
              f"{lead.get('next_action') or 'follow up'}")
    return 0


def cmd_content() -> int:
    drafts = _drafts()
    print("CONTENT PIPELINE")
    print("=" * 60)
    pending = [(d, m) for d, m in drafts if m.get("status") in ("draft", "reviewed")]
    if not pending:
        print("No pending drafts. Calendar: marketing/content/calendar.json")
        return 0
    for d, m in pending:
        print(f"· {d} [{m.get('status')}] segment={m.get('segment', '?')}")
        if m.get("cta"):
            print(f"    CTA: {m['cta']}")
    print("Publishing is human-executed (docs/LINKEDIN_STRATEGY.md §5).")
    return 0


def cmd_demand() -> int:
    """Aggregate product demand from the local analytics DB — counts only,
    no individual users (docs/PRODUCT_ANALYTICS.md)."""
    print("AGGREGATE PRODUCT DEMAND (first-party analytics, counts only)")
    print("=" * 60)
    db = os.environ.get("HYDRASHIELD_CACHE_DB") or os.path.join(
        ROOT, "data", "cache", "hydrashield_cache.sqlite3")
    if not os.path.exists(db):
        print(f"No analytics DB at {db} — demand unknown (not zero).")
        return 0
    import sqlite3
    conn = sqlite3.connect(db)
    try:
        exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='analytics_events'").fetchone()
        if not exists:
            print("Analytics table not present yet — demand unknown (not zero).")
            return 0
        total = conn.execute("SELECT COUNT(*) FROM analytics_events").fetchone()[0]
        if not total:
            print("No events recorded yet — demand unknown (not zero).")
            return 0
        print(f"Total events: {total}")
        for label, sql in (
            ("Top hazards", "SELECT hazard, COUNT(*) c FROM analytics_events "
             "WHERE hazard IS NOT NULL GROUP BY hazard ORDER BY c DESC LIMIT 6"),
            ("Top pages", "SELECT page, COUNT(*) c FROM analytics_events "
             "WHERE page IS NOT NULL GROUP BY page ORDER BY c DESC LIMIT 8"),
            ("Funnel", "SELECT event, COUNT(*) c FROM analytics_events WHERE "
             "event IN ('location_analyzed','solution_viewed','report_generated',"
             "'account_created','alert_created','sms_enabled','contact_started') "
             "GROUP BY event ORDER BY c DESC"),
        ):
            print(f"{label}:")
            for value, count in conn.execute(sql):
                print(f"  · {value}: {count}")
    finally:
        conn.close()
    print("Note: aggregate counts only. Sector/country demand comes from lead "
          "records and events — never from user tracking.")
    return 0


def cmd_lessons() -> int:
    leads = _leads()
    print("OUTREACH LESSONS (from recorded interactions)")
    print("=" * 60)
    interactions = []
    for name, lead in leads:
        for inter in lead.get("interactions") or []:
            interactions.append((lead.get("organization"), inter))
    if not interactions:
        print("No interactions recorded yet. Lessons appear here after real "
              "outreach is recorded in lead records.")
        return 0
    wins = [i for _o, i in interactions if i["type"] in
            ("replied", "meeting", "demo", "report_requested", "trial", "subscription")]
    losses = [i for _o, i in interactions if i["type"] == "lost"]
    print(f"Interactions: {len(interactions)} · positive: {len(wins)} · lost: {len(losses)}")
    for org, i in interactions[-10:]:
        print(f"· {i.get('date')} {org}: {i.get('type')} — {i.get('summary')}")
    return 0


def _radar_score(lead: dict, signals: list) -> int:
    """Deterministic, documented ranking (docs/COMMERCIAL_INTELLIGENCE.md §7):

        score = urgency(0-3) + priority(0-3)
              + strongest linked signal strength (0-3)
              + 2 when a follow-up is due/overdue
              − 99 for won/lost leads (excluded)

    Every component is a recorded fact or judgement on the record — no
    fabricated precision.
    """
    if lead.get("status", "open") in ("won", "lost"):
        return -99
    score = {"high": 3, "medium": 2, "low": 1}.get(lead.get("urgency"), 0)
    score += {"high": 3, "medium": 2, "low": 1}.get(lead.get("priority"), 0)
    best = 0
    for sig in signals:
        if sig.get("organization") == lead.get("organization") or sig.get("id") in \
                set(lead.get("commercial_signals") or []):
            best = max(best, {"strong": 3, "moderate": 2, "weak": 1}.get(
                sig.get("signal_strength"), 0))
    score += best
    nf = lead.get("next_followup")
    if nf and nf <= date.today().isoformat():
        score += 2
    return score


def cmd_radar() -> int:
    """The commercial radar: who should I contact today — and the full why."""
    leads = _leads()
    signals = [s for _n, s in _signals()]
    print("COMMERCIAL RADAR — who to contact today")
    print("=" * 60)
    print("Ranking formula (documented, deterministic): urgency(0-3) + "
          "priority(0-3) + strongest linked signal(0-3) + overdue "
          "follow-up(2); won/lost excluded.")
    if not leads:
        print("No leads yet. Research path: docs/COMMERCIAL_INTELLIGENCE.md §4.")
        return 0
    ranked = sorted(leads, key=lambda kv: _radar_score(kv[1], signals),
                    reverse=True)
    for _n, lead in ranked:
        score = _radar_score(lead, signals)
        if score < 0:
            continue
        print()
        print(f"WHO: {lead.get('organization')} ({lead.get('segment')}, "
              f"{lead.get('country')}) — score {score}")
        print(f"  WHY NOW: {lead.get('identified_problem') or lead.get('potential_pain') or '—'}")
        print(f"  PROBLEM: {lead.get('climate_exposure') or '—'}")
        print(f"  EVIDENCE: {lead.get('evidence') or '—'}")
        print(f"  SERVICE: {(lead.get('recommended_product') or '—').replace('_', ' ')}")
        print(f"  MESSAGE: {lead.get('recommended_message') or '—'}")
        print(f"  NEXT ACTION: {lead.get('next_action') or '—'}")
    return 0


def cmd_morning() -> int:
    print("MORNING BRIEFING — hazard-driven marketing day (workflow §23)")
    print("=" * 60)
    steps = [("1 · Current hazard signals (where is the risk?)", cmd_hazards),
             ("2 · Hazard → market opportunities (who is affected?)", cmd_hazard_market),
             ("3 · High-priority prospects", cmd_priorities),
             ("4 · Follow-ups due", cmd_followups),
             ("5 · Product demand signals", cmd_demand),
             ("6 · Content this week", cmd_content)]
    for title, fn in steps:
        print()
        print("## " + title)
        fn()
    print()
    print("## 7 · Recommended outreach")
    print("Human decision: pick from the opportunities above; draft with "
          "scripts/outreach_composer.py (evidence required); queue; review; "
          "send from info@talaix.com only after human approval.")
    return 0


def cmd_evening() -> int:
    print("EVENING RECORD CHECKLIST (operator workflow §9)")
    print("=" * 60)
    print("Record today's reality into the workspace:")
    print("  1 · interactions → append to each lead's interactions[] "
          "(date, type, summary, source, next_action)")
    print("  2 · lead status → update outreach_status / status / next_followup")
    print("  3 · responses → record what worked/failed honestly")
    print("  4 · lessons → note persuasive evidence + dead ends in "
          "marketing/analytics/")
    print("  5 · next actions → tomorrow's priorities emerge from the records")
    print()
    cmd_followups()
    return 0


def cmd_prospects() -> int:
    leads = _leads()
    print(f"PROSPECTS ({len(leads)} researched organizations)")
    print("=" * 60)
    ordered = sorted(leads, key=lambda kv: (
        _PRIORITY_RANK.get(kv[1].get("priority"), 3),
        kv[1].get("segment", ""), kv[1].get("organization", "")))
    for _n, lead in ordered:
        print(f"· [{lead.get('priority','?')}] {lead.get('organization')} "
              f"({lead.get('segment')}, {lead.get('country')}) → "
              f"{(lead.get('recommended_product') or '?').replace('_', ' ')}")
    return 0


def cmd_market() -> int:
    leads = _leads()
    print("MARKET COVERAGE (leads by segment)")
    print("=" * 60)
    agg = {}
    for _n, lead in leads:
        agg.setdefault(lead.get("segment", "?"), []).append(lead)
    for seg, items in sorted(agg.items(), key=lambda kv: -len(kv[1])):
        high = sum(1 for l in items if l.get("priority") == "high")
        print(f"· {seg}: {len(items)} prospect(s), {high} high-priority")
    if not leads:
        print("No leads yet.")
    return 0


def cmd_campaigns() -> int:
    campaigns = _campaigns()
    print("CAMPAIGNS")
    print("=" * 60)
    for c in campaigns:
        print(f"· {c['id']} — {c['name']}")
        print(f"    audience: {', '.join(c.get('audience', {}).get('segments', []))}")
        print(f"    CTA: {c.get('cta')} → {c.get('conversion_goal')}")
    return 0


def cmd_outreach() -> int:
    print("OUTREACH QUEUE + AUDIT")
    print("=" * 60)
    queue = _load_json(os.path.join(MARKETING, "outreach", "queue.json")).get("queue", [])
    print(f"Queued drafts (awaiting human review): {len(queue)}")
    for q in queue:
        print(f"· {q.get('lead')} — {q.get('purpose')} [{q.get('status')}]")
    audit = os.path.join(MARKETING, "outreach", "audit.jsonl")
    if os.path.exists(audit):
        lines = [l for l in open(audit, encoding="utf-8").read().splitlines() if l.strip()]
        print(f"Audit records: {len(lines)}")
        for line in lines[-5:]:
            rec = json.loads(line)
            print(f"· {rec.get('date')} {rec.get('action')} — {rec.get('lead')}")
    else:
        print("No audit records yet.")
    print("Nothing sends automatically — human approval gates every send.")
    return 0


def cmd_pipeline() -> int:
    leads = _leads()
    print("PIPELINE (by outreach status)")
    print("=" * 60)
    counts = {s: 0 for s in LEAD_STATUSES}
    for _n, lead in leads:
        counts[lead.get("outreach_status", "researched")] = \
            counts.get(lead.get("outreach_status", "researched"), 0) + 1
    for status in LEAD_STATUSES:
        print(f"· {status}: {counts.get(status, 0)}")
    won = sum(1 for _n, l in leads if l.get("status") == "won")
    print(f"· won: {won}")
    return 0


def cmd_meetings() -> int:
    leads = _leads()
    print("MEETINGS & DEMOS")
    print("=" * 60)
    found = 0
    for _n, lead in leads:
        for inter in lead.get("interactions") or []:
            if inter.get("type") in ("meeting", "demo"):
                print(f"· {inter.get('date')} {lead.get('organization')}: "
                      f"{inter.get('type')} — {inter.get('summary')}")
                found += 1
    if not found:
        print("No meetings recorded yet.")
    return 0


def cmd_partners() -> int:
    leads = _leads()
    print("PARTNERS (by relationship type)")
    print("=" * 60)
    agg = {}
    for _n, lead in leads:
        agg.setdefault(lead.get("relationship_type", "customer"), []).append(
            lead.get("organization"))
    for rtype, orgs in sorted(agg.items()):
        print(f"· {rtype}: {len(orgs)}")
    if not leads:
        print("No leads yet.")
    return 0


def cmd_funding() -> int:
    """EU funding ledger + platform funding knowledge base state."""
    print("FUNDING INTELLIGENCE")
    print("=" * 60)
    ledger = _records("eu_funding")
    print(f"EU funding ledger records: {len(ledger)}")
    for _n, rec in ledger:
        print(f"· {rec.get('programme')} — {rec.get('status', 'watching')} "
              f"(checked {rec.get('date_checked')})")
        print(f"    {rec.get('hydrashield_relevance', '')}")
    kb_path = os.path.join(ROOT, "config", "funding_knowledge.json")
    if os.path.exists(kb_path):
        kb = _load_json(kb_path)
        programmes = kb.get("programmes") or []
        print(f"Platform funding knowledge base: {len(programmes)} curated "
              f"programmes (all with official URLs)")
        print("Match them via /api/v2/funding or funding.html; EU-ledger "
              "records stay marketing-side (opportunities being tracked).")
    if not ledger:
        print("Ledger empty — record opportunities only from official "
              "sources (marketing/eu_funding/schema.json).")
    return 0


def cmd_procurement() -> int:
    """Procurement & tender radar (marketing/procurement/)."""
    print("PROCUREMENT & TENDER RADAR")
    print("=" * 60)
    records = _records("procurement")
    if not records:
        print("No tenders tracked. Add them from official portals (TED, "
              "national portals) per marketing/procurement/schema.json.")
        return 0
    for _n, rec in records:
        print(f"· {rec.get('title')} — {rec.get('contracting_authority')} "
              f"({rec.get('geography')}) [{rec.get('status', 'watching')}]")
        print(f"    deadline: {rec.get('deadline', 'not currently verified')} "
              f"· {rec.get('official_url')}")
    return 0


# ---------------------------------------------------------------------------
# Hazard-driven marketing (the commercial intelligence engine)
# ---------------------------------------------------------------------------

_PRIORITY_SEGMENTS = ("environmental_consulting", "investment", "insurance",
                      "governments", "real_estate", "research_centers")


def _snapshot_areas():
    """Current elevated-risk areas from the public risk snapshot
    (real platform data) or an honest unavailable marker."""
    try:
        from scripts.hazard_feed import fetch_risk_snapshot, snapshot_entries
    except ImportError:
        from hazard_feed import fetch_risk_snapshot, snapshot_entries
    snap = fetch_risk_snapshot()
    if snap is None:
        return None
    return snapshot_entries(snap)


def cmd_hazards() -> int:
    print("CURRENT HAZARD SIGNALS (live risk snapshot)")
    print("=" * 60)
    areas = _snapshot_areas()
    if areas is None:
        print("Snapshot unreachable — current hazard state is unknown "
              "(not zero). Fetch https://talaix.com/api/risk-snapshot "
              "manually or run on the server.")
        return 0
    if not areas:
        print("No elevated areas in the current snapshot — the monitored "
              "areas show no meaningful risk right now. This is a real "
              "answer, not missing data.")
        return 0
    for e in areas:
        print(f"· {e.get('name')} — risk {e.get('risk')} "
              f"({e.get('risk_class')}), FWI class {e.get('fwi_class')}")
    return 0


def cmd_hazard_market() -> int:
    """The hazard-first radar: current hazard signals → affected regions →
    matched prospects with product fit, why-now, message, next action."""
    print("HAZARD-DRIVEN MARKET RADAR")
    print("=" * 60)
    print("Chain: HAZARD → REGION → SECTOR → ORGANIZATION → PROBLEM → "
          "PRODUCT → OUTREACH")
    areas = _snapshot_areas()
    if areas is None:
        print("Hazard snapshot unreachable — hazard state unknown, not zero. "
              "Run on the server or check /api/risk-snapshot.")
        return 0
    if not areas:
        print("No elevated hazard areas in the current snapshot — a real "
              "answer, not missing data.")
        return 0
    from src.dashboard.hazard_market import build_opportunities

    seg_doc = _load_json(os.path.join(MARKETING, "segments", "segments.json"))
    product_matching = seg_doc.get("product_matching") or {}
    leads = [l for _n, l in _leads()]
    opportunities = build_opportunities(leads, areas, product_matching)

    print(f"Current elevated areas (real data): "
          f"{', '.join(a.get('name', '?') for a in areas)}")
    print()
    if not opportunities:
        print("No prospects match the current hazard regions/interests — "
              "honestly none, not fabricated.")
        return 0
    for o in opportunities[:20]:
        print(f"· {o['organization']} ({o['segment_label']}, {o['country'] or '??'})")
        print(f"    hazard: {o['hazard']} @ {o['area']} [{o['risk_class']}] "
              f"— match: {o['match']}")
        print(f"    why now: {o['why_now']}")
        print(f"    product fit: {', '.join(o['product_fit'])}")
        print(f"    message: {o['message'] or '—'}")
        print(f"    next: {o['next_action'] or '—'}")
    if len(opportunities) > 20:
        print(f"  …and {len(opportunities) - 20} more")
    print()
    print("Region matching is name-based and explicitly approximate — "
          "verify before outreach. No hazard or prospect is fabricated.")
    return 0


_COMMANDS = {
    "status": cmd_status,
    "radar": cmd_radar,
    "hazards": cmd_hazards,
    "hazard-market": cmd_hazard_market,
    "market-radar": cmd_hazard_market,
    "signals": cmd_signals,
    "sectors": cmd_sectors,
    "events": cmd_events,
    "priorities": cmd_priorities,
    "followups": cmd_followups,
    "content": cmd_content,
    "demand": cmd_demand,
    "funding": cmd_funding,
    "procurement": cmd_procurement,
    "lessons": cmd_lessons,
    "prospects": cmd_prospects,
    "market": cmd_market,
    "campaigns": cmd_campaigns,
    "outreach": cmd_outreach,
    "pipeline": cmd_pipeline,
    "meetings": cmd_meetings,
    "partners": cmd_partners,
    "morning": cmd_morning,
    "evening": cmd_evening,
}


def main() -> int:
    command = sys.argv[1] if len(sys.argv) > 1 else "status"
    fn = _COMMANDS.get(command)
    if fn is None:
        print(__doc__)
        return 2
    return fn()


if __name__ == "__main__":
    sys.exit(main())
