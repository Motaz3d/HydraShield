#!/usr/bin/env python3
"""HydraShield marketing reports generator.

Generates periodic marketing reports from the file-based workspace.

Usage:
    python scripts/marketing_reports.py summary
    python scripts/marketing_reports.py weekly
    python scripts/marketing_reports.py monthly
    python scripts/marketing_reports.py segments
    python scripts/marketing_reports.py campaigns
"""

import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MARKETING = PROJECT_ROOT / "marketing"
LEADS_DIR = MARKETING / "leads"
SEGMENTS_FILE = MARKETING / "segments" / "segments.json"
CAMPAIGNS_FILE = MARKETING / "campaigns" / "linkedin_campaigns.json"
OUTREACH_QUEUE = MARKETING / "outreach" / "queue.json"
REPORTS_DIR = MARKETING / "reports"

REPORTS_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------


def load_leads() -> list[dict]:
    """Load all lead records from marketing/leads/."""
    leads = []
    if not LEADS_DIR.exists():
        return leads
    for f in LEADS_DIR.glob("*.json"):
        if f.name == "schema.json":
            continue
        try:
            leads.append(json.loads(f.read_text()))
        except (json.JSONDecodeError, OSError):
            continue
    return leads


def load_segments() -> dict:
    if not SEGMENTS_FILE.exists():
        return {}
    return json.loads(SEGMENTS_FILE.read_text())


def load_campaigns() -> list[dict]:
    if not CAMPAIGNS_FILE.exists():
        return []
    data = json.loads(CAMPAIGNS_FILE.read_text())
    return data.get("campaigns", [])


def load_outreach_queue() -> list[dict]:
    if not OUTREACH_QUEUE.exists():
        return []
    data = json.loads(OUTREACH_QUEUE.read_text())
    return data.get("queue", [])


# ---------------------------------------------------------------------------
# Report generators
# ---------------------------------------------------------------------------


def report_summary(leads: list[dict], campaigns: list[dict], segments: dict) -> dict:
    """High-level marketing summary."""
    total_leads = len(leads)

    # Outreach status distribution
    status_dist = Counter(l.get("outreach_status", "unknown") for l in leads)

    # Priority distribution
    priority_dist = Counter(l.get("priority", "unknown") for l in leads)

    # Segment distribution
    segment_dist = Counter(l.get("segment", "unknown") for l in leads)

    # Country distribution (top 10)
    country_dist = Counter(l.get("country", "unknown") for l in leads).most_common(10)

    # Campaign summary
    campaign_info = []
    for c in campaigns:
        c_leads = [
            l for l in leads if l.get("segment") in c.get("audience", {}).get("segments", [])
        ]
        campaign_info.append({
            "id": c.get("id", "?"),
            "name": c.get("name", "?"),
            "target_segments": c.get("audience", {}).get("segments", []),
            "leads_matched": len(c_leads),
            "conversion_goal": c.get("conversion_goal", []),
        })

    # Interaction activity
    total_interactions = sum(len(l.get("interactions", [])) for l in leads)
    contacted = sum(1 for l in leads if l.get("outreach_status") in ("contacted", "responded", "opportunity"))
    responded = sum(1 for l in leads if l.get("outreach_status") == "responded")
    opportunities = sum(1 for l in leads if l.get("outreach_status") == "opportunity")

    # Recent activity (last 7 days)
    week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    recent_interactions = []
    for l in leads:
        for ix in l.get("interactions", []):
            if ix.get("date", "") >= week_ago:
                recent_interactions.append({
                    "org": l.get("organization"),
                    "date": ix["date"],
                    "type": ix.get("type"),
                    "summary": ix.get("summary", "")[:80],
                })

    return {
        "generated_at": datetime.now().isoformat(),
        "report_type": "summary",
        "total_leads": total_leads,
        "total_campaigns": len(campaigns),
        "total_interactions": total_interactions,
        "status_distribution": dict(status_dist),
        "priority_distribution": dict(priority_dist),
        "segment_distribution": dict(segment_dist),
        "top_countries": country_dist,
        "funnel": {
            "researched": status_dist.get("researched", 0),
            "qualified": status_dist.get("qualified", 0),
            "draft_prepared": status_dist.get("draft_prepared", 0),
            "contacted": contacted,
            "responded": responded,
            "opportunity": opportunities,
        },
        "campaigns": campaign_info,
        "recent_activity": sorted(recent_interactions, key=lambda x: x["date"], reverse=True)[:20],
    }


def report_weekly(leads: list[dict]) -> dict:
    """Weekly activity report — focuses on last 7 days."""
    week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    today = datetime.now().strftime("%Y-%m-%d")

    weekly_interactions = []
    new_leads = []
    status_changes = []

    for l in leads:
        # New leads this week
        if l.get("date_checked", "") >= week_ago:
            new_leads.append({
                "org": l.get("organization"),
                "segment": l.get("segment"),
                "country": l.get("country"),
                "priority": l.get("priority"),
            })

        # Interactions this week
        for ix in l.get("interactions", []):
            if ix.get("date", "") >= week_ago:
                weekly_interactions.append({
                    "org": l.get("organization"),
                    "date": ix["date"],
                    "type": ix.get("type"),
                    "summary": ix.get("summary", "")[:100],
                })

        # Status changes (last interaction type indicates current status)
        if l.get("interactions"):
            last = l["interactions"][-1]
            if last.get("date", "") >= week_ago:
                status_changes.append({
                    "org": l.get("organization"),
                    "new_status": last.get("type"),
                    "date": last["date"],
                })

    # Follow-ups due this week
    followups_due = []
    for l in leads:
        fu = l.get("next_followup", "")
        if fu and week_ago <= fu <= today:
            followups_due.append({
                "org": l.get("organization"),
                "followup_date": fu,
                "next_action": l.get("next_action", ""),
            })

    return {
        "generated_at": datetime.now().isoformat(),
        "report_type": "weekly",
        "period": f"{week_ago} to {today}",
        "new_leads_count": len(new_leads),
        "new_leads": new_leads,
        "interactions_count": len(weekly_interactions),
        "interactions": sorted(weekly_interactions, key=lambda x: x["date"], reverse=True),
        "status_changes": status_changes,
        "followups_due": followups_due,
    }


def report_monthly(leads: list[dict], campaigns: list[dict]) -> dict:
    """Monthly marketing performance report."""
    month_ago = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    today = datetime.now().strftime("%Y-%m-%d")

    # Monthly funnel movement
    monthly_interactions = []
    for l in leads:
        for ix in l.get("interactions", []):
            if ix.get("date", "") >= month_ago:
                monthly_interactions.append(ix.get("type"))

    interaction_types = Counter(monthly_interactions)

    # Pipeline velocity — how many leads moved forward this month
    moved_forward = 0
    for l in leads:
        interactions = l.get("interactions", [])
        recent = [ix for ix in interactions if ix.get("date", "") >= month_ago]
        if recent:
            # Check if any recent interaction moved the lead forward
            forward_types = {"qualified", "contacted", "replied", "meeting", "demo", "proposal", "customer"}
            if any(ix.get("type") in forward_types for ix in recent):
                moved_forward += 1

    # Campaign effectiveness — which campaigns target engaged segments
    engaged_segments = set()
    for l in leads:
        if l.get("outreach_status") in ("contacted", "responded", "opportunity"):
            engaged_segments.add(l.get("segment"))

    campaign_effectiveness = []
    for c in campaigns:
        target_segs = set(c.get("audience", {}).get("segments", []))
        overlap = target_segs & engaged_segments
        campaign_effectiveness.append({
            "id": c.get("id"),
            "name": c.get("name"),
            "target_segments": list(target_segs),
            "engaged_segments": list(overlap),
            "engagement_score": len(overlap) / max(len(target_segs), 1),
        })

    campaign_effectiveness.sort(key=lambda x: x["engagement_score"], reverse=True)

    # Top performing segments
    segment_engagement = defaultdict(lambda: {"total": 0, "engaged": 0})
    for l in leads:
        seg = l.get("segment", "unknown")
        segment_engagement[seg]["total"] += 1
        if l.get("outreach_status") in ("contacted", "responded", "opportunity"):
            segment_engagement[seg]["engaged"] += 1

    for seg in segment_engagement:
        t = segment_engagement[seg]["total"]
        e = segment_engagement[seg]["engaged"]
        segment_engagement[seg]["engagement_rate"] = e / max(t, 1)

    return {
        "generated_at": datetime.now().isoformat(),
        "report_type": "monthly",
        "period": f"Last 30 days (since {month_ago})",
        "total_leads": len(leads),
        "pipeline_movement": {
            "total_interactions": len(monthly_interactions),
            "interaction_breakdown": dict(interaction_types),
            "leads_moved_forward": moved_forward,
            "conversion_rate": moved_forward / max(len(leads), 1),
        },
        "campaign_effectiveness": campaign_effectiveness,
        "segment_performance": {
            seg: {
                "total": data["total"],
                "engaged": data["engaged"],
                "engagement_rate": round(data["engagement_rate"], 3),
            }
            for seg, data in sorted(
                segment_engagement.items(),
                key=lambda x: x[1]["engagement_rate"],
                reverse=True,
            )
        },
    }


def report_segments(leads: list[dict], segments: dict) -> dict:
    """Detailed segment analysis."""
    seg_defs = segments.get("segments", {})
    segment_data = defaultdict(lambda: {
        "leads": [],
        "priorities": [],
        "statuses": [],
        "countries": [],
        "hazards": [],
    })

    for l in leads:
        seg = l.get("segment", "unknown")
        segment_data[seg]["leads"].append(l.get("organization"))
        segment_data[seg]["priorities"].append(l.get("priority", "unknown"))
        segment_data[seg]["statuses"].append(l.get("outreach_status", "unknown"))
        segment_data[seg]["countries"].append(l.get("country", "unknown"))
        segment_data[seg]["hazards"].extend(l.get("relevant_hazards", []))

    result = {}
    for seg, data in segment_data.items():
        definition = seg_defs.get(seg, {})
        result[seg] = {
            "definition": {
                "pain_points": definition.get("pain_points", [])[:3],
                "cta": definition.get("cta", ""),
                "outreach_style": definition.get("outreach_style", ""),
            },
            "lead_count": len(data["leads"]),
            "leads": data["leads"],
            "priority_distribution": dict(Counter(data["priorities"])),
            "status_distribution": dict(Counter(data["statuses"])),
            "top_countries": Counter(data["countries"]).most_common(5),
            "top_hazards": Counter(data["hazards"]).most_common(5),
        }

    return {
        "generated_at": datetime.now().isoformat(),
        "report_type": "segments",
        "segments": result,
    }


def report_campaigns(leads: list[dict], campaigns: list[dict]) -> dict:
    """Campaign performance analysis."""
    results = []
    for c in campaigns:
        target_segs = set(c.get("audience", {}).get("segments", []))
        c_leads = [l for l in leads if l.get("segment") in target_segs]

        # Funnel for this campaign's target leads
        funnel = Counter(l.get("outreach_status", "unknown") for l in c_leads)

        # Engagement rate
        engaged = sum(1 for l in c_leads if l.get("outreach_status") in ("contacted", "responded", "opportunity"))
        engagement_rate = engaged / max(len(c_leads), 1)

        # Countries covered
        countries = Counter(l.get("country", "unknown") for l in c_leads).most_common(5)

        results.append({
            "id": c.get("id"),
            "name": c.get("name"),
            "target_segments": list(target_segs),
            "total_target_leads": len(c_leads),
            "funnel": dict(funnel),
            "engaged_count": engaged,
            "engagement_rate": round(engagement_rate, 3),
            "top_countries": countries,
            "conversion_goal": c.get("conversion_goal", []),
            "landing_page": c.get("landing_page", ""),
        })

    results.sort(key=lambda x: x["engagement_rate"], reverse=True)

    return {
        "generated_at": datetime.now().isoformat(),
        "report_type": "campaigns",
        "campaigns": results,
    }


# ---------------------------------------------------------------------------
# Markdown formatter
# ---------------------------------------------------------------------------


def to_markdown(data: dict) -> str:
    """Convert report dict to readable Markdown."""
    lines = []
    rpt = data.get("report_type", "report")
    lines.append(f"# HydraShield Marketing Report — {rpt.upper()}")
    lines.append(f"\nGenerated: {data.get('generated_at', 'N/A')}\n")

    if rpt == "summary":
        lines.append(f"## Overview")
        lines.append(f"- **Total Leads:** {data['total_leads']}")
        lines.append(f"- **Total Campaigns:** {data['total_campaigns']}")
        lines.append(f"- **Total Interactions:** {data['total_interactions']}")
        lines.append(f"\n## Funnel")
        for stage, count in data.get("funnel", {}).items():
            lines.append(f"- {stage}: {count}")
        lines.append(f"\n## Segment Distribution")
        for seg, count in sorted(data.get("segment_distribution", {}).items(), key=lambda x: -x[1]):
            lines.append(f"- {seg}: {count}")
        lines.append(f"\n## Campaigns")
        for c in data.get("campaigns", []):
            lines.append(f"- **{c['id']}** {c['name']}: {c['leads_matched']} leads matched")

    elif rpt == "weekly":
        lines.append(f"## Period: {data['period']}")
        lines.append(f"\n### New Leads ({data['new_leads_count']})")
        for l in data.get("new_leads", []):
            lines.append(f"- {l['org']} ({l['segment']}, {l['country']}) — {l['priority']}")
        lines.append(f"\n### Interactions ({data['interactions_count']})")
        for ix in data.get("interactions", [])[:15]:
            lines.append(f"- {ix['date']} | {ix['org']} | {ix['type']} | {ix['summary'][:60]}")
        lines.append(f"\n### Follow-ups Due")
        for f in data.get("followups_due", []):
            lines.append(f"- {f['org']} — {f['followup_date']}: {f['next_action'][:60]}")

    elif rpt == "monthly":
        pm = data.get("pipeline_movement", {})
        lines.append(f"## Period: {data['period']}")
        lines.append(f"\n### Pipeline Movement")
        lines.append(f"- Total interactions: {pm.get('total_interactions', 0)}")
        lines.append(f"- Leads moved forward: {pm.get('leads_moved_forward', 0)}")
        lines.append(f"- Conversion rate: {pm.get('conversion_rate', 0):.1%}")
        lines.append(f"\n### Campaign Effectiveness")
        for c in data.get("campaign_effectiveness", []):
            lines.append(f"- **{c['id']}** {c['name']}: engagement {c['engagement_score']:.1%} ({len(c['engaged_segments'])} engaged segments)")
        lines.append(f"\n### Segment Performance")
        for seg, perf in data.get("segment_performance", {}).items():
            lines.append(f"- {seg}: {perf['engaged']}/{perf['total']} engaged ({perf['engagement_rate']:.1%})")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Save reports
# ---------------------------------------------------------------------------


def save_report(data: dict, md: str, report_type: str) -> tuple[str, str]:
    """Save JSON and Markdown reports."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = REPORTS_DIR / f"{report_type}_{ts}.json"
    md_path = REPORTS_DIR / f"{report_type}_{ts}.md"

    json_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    md_path.write_text(md)

    # Update latest symlinks
    latest_json = REPORTS_DIR / f"{report_type}_latest.json"
    latest_md = REPORTS_DIR / f"{report_type}_latest.md"

    try:
        latest_json.unlink(missing_ok=True)
    except TypeError:
        if latest_json.exists():
            latest_json.unlink()
    try:
        latest_md.unlink(missing_ok=True)
    except TypeError:
        if latest_md.exists():
            latest_md.unlink()

    latest_json.symlink_to(json_path.name)
    latest_md.symlink_to(md_path.name)

    return str(json_path), str(md_path)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

COMMANDS = {
    "summary": (report_summary, "Marketing summary"),
    "weekly": (report_weekly, "Weekly activity"),
    "monthly": (report_monthly, "Monthly performance"),
    "segments": (report_segments, "Segment analysis"),
    "campaigns": (report_campaigns, "Campaign performance"),
}


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print("Usage: python scripts/marketing_reports.py <command>")
        print(f"Commands: {', '.join(COMMANDS.keys())}")
        raise SystemExit(1)

    cmd = sys.argv[1]
    generator, description = COMMANDS[cmd]

    print(f"Generating {description} report...")

    leads = load_leads()
    segments = load_segments()
    campaigns = load_campaigns()

    # Generate report
    if cmd in ("summary",):
        data = generator(leads, campaigns, segments)
    elif cmd in ("monthly",):
        data = generator(leads, campaigns)
    elif cmd in ("segments",):
        data = generator(leads, segments)
    elif cmd in ("campaigns",):
        data = generator(leads, campaigns)
    else:
        data = generator(leads)

    md = to_markdown(data)
    json_path, md_path = save_report(data, md, cmd)

    print(f"\n✓ JSON report: {json_path}")
    print(f"✓ Markdown report: {md_path}")
    print(f"\n{'=' * 60}")
    print(md)


if __name__ == "__main__":
    main()
