#!/usr/bin/env python3
"""Talaix automated follow-up engine.

Reads leads, calculates follow-up dates, generates follow-up actions,
and integrates with outreach_composer.py for draft emails.

Usage:
    python scripts/followup_engine.py list          # show due follow-ups
    python scripts/followup_engine.py plan           # generate follow-up plan
    python scripts/followup_engine.py execute        # draft follow-up emails
    python scripts/followup_engine.py status         # follow-up statistics
"""

import json
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
FOLLOWUPS_DIR = MARKETING / "followups"
OUTREACH_QUEUE = MARKETING / "outreach" / "queue.json"
OUTREACH_AUDIT = MARKETING / "outreach" / "audit.jsonl"
OUTREACH_COMPOSER = PROJECT_ROOT / "scripts" / "outreach_composer.py"

FOLLOWUPS_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Follow-up timing rules
# ---------------------------------------------------------------------------

# Days to wait before next follow-up based on last interaction type
FOLLOWUP_INTERVALS = {
    "researched": 14,       # 2 weeks after research
    "qualified": 7,         # 1 week after qualification
    "draft_prepared": 3,    # 3 days after draft ready
    "contacted": 10,        # 10 days after first contact
    "responded": 5,         # 5 days after response (hot!)
    "meeting": 3,           # 3 days after meeting
    "demo": 3,              # 3 days after demo
    "proposal": 7,          # 7 days after proposal sent
    "trial": 5,             # 5 days during trial
    "customer": 30,         # 30 days for customer check-in
    "follow_up": 7,         # 7 days after follow-up
    "lost": 90,             # 90 days before re-engagement
    "renewal": 60,          # 60 days before renewal
}

# Priority multipliers (high priority = shorter intervals)
PRIORITY_MULTIPLIER = {
    "high": 0.5,    # half the interval
    "medium": 1.0,  # normal interval
    "low": 1.5,     # longer interval
}

# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------


def load_leads() -> list[dict]:
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


def load_outreach_queue() -> dict:
    if not OUTREACH_QUEUE.exists():
        return {"queue": []}
    return json.loads(OUTREACH_QUEUE.read_text())


def save_followup(followup: dict) -> str:
    """Save a follow-up action to marketing/followups/."""
    org_slug = followup["organization"].lower().replace(" ", "-").replace("/", "-")
    path = FOLLOWUPS_DIR / f"{org_slug}_followup.json"
    path.write_text(json.dumps(followup, indent=2, ensure_ascii=False))
    return str(path)


# ---------------------------------------------------------------------------
# Follow-up calculator
# ---------------------------------------------------------------------------


def calculate_followup(lead: dict) -> dict | None:
    """Calculate the next follow-up for a lead.

    Returns a follow-up dict or None if no follow-up is needed.
    """
    org = lead.get("organization", "unknown")
    status = lead.get("outreach_status", "researched")
    priority = lead.get("priority", "medium")

    # Don't follow up if won or dormant
    if status in ("opportunity",) and lead.get("status") == "won":
        return None

    # Find the last interaction date
    interactions = lead.get("interactions", [])
    if not interactions:
        # No interactions yet — use date_checked as baseline
        last_date_str = lead.get("date_checked", "")
        last_type = "researched"
    else:
        last = interactions[-1]
        last_date_str = last.get("date", lead.get("date_checked", ""))
        last_type = last.get("type", "researched")

    if not last_date_str:
        return None

    # Parse date
    try:
        last_date = datetime.strptime(last_date_str, "%Y-%m-%d")
    except ValueError:
        return None

    # Calculate interval
    base_interval = FOLLOWUP_INTERVALS.get(last_type, 14)
    multiplier = PRIORITY_MULTIPLIER.get(priority, 1.0)
    interval_days = int(base_interval * multiplier)

    # Next follow-up date
    next_fu = last_date + timedelta(days=interval_days)
    today = datetime.now()
    days_until = (next_fu - today).days
    is_overdue = days_until < 0

    # Build follow-up action
    next_action = lead.get("next_action", "")
    if not next_action and interactions:
        # Suggest next action based on status
        action_suggestions = {
            "researched": "Qualify: verify current public signal and select contact route",
            "qualified": "Prepare personalized outreach draft",
            "draft_prepared": "Review draft and send to operator queue",
            "contacted": "Follow up on initial contact",
            "responded": "Respond promptly — schedule meeting or demo",
            "meeting": "Send meeting summary and next steps",
            "demo": "Follow up on demo — send proposal or trial offer",
            "proposal": "Check on proposal status",
            "trial": "Monitor trial usage and offer support",
            "customer": "Check in — upsell or renewal discussion",
            "lost": "Re-engage with new product update or signal",
        }
        next_action = action_suggestions.get(status, "Review and plan next step")

    followup = {
        "organization": org,
        "segment": lead.get("segment", "unknown"),
        "country": lead.get("country", "unknown"),
        "priority": priority,
        "current_status": status,
        "last_interaction_type": last_type,
        "last_interaction_date": last_date_str,
        "next_followup_date": next_fu.strftime("%Y-%m-%d"),
        "days_until_followup": days_until,
        "is_overdue": is_overdue,
        "suggested_action": next_action,
        "recommended_product": lead.get("recommended_product", ""),
        "recommended_message": lead.get("recommended_message", "")[:100],
        "calculated_at": today.isoformat(),
    }

    return followup


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_list(leads: list[dict]) -> None:
    """List follow-ups that are due or overdue."""
    today = datetime.now()
    followups = []

    for l in leads:
        fu = calculate_followup(l)
        if fu:
            # Save follow-up
            save_followup(fu)
            # Only show due/overdue
            if fu["days_until_followup"] <= 0:
                followups.append(fu)

    followups.sort(key=lambda x: x["days_until_followup"])

    overdue = [f for f in followups if f["is_overdue"]]
    due_today = [f for f in followups if f["days_until_followup"] == 0]

    print(f"\n{'=' * 70}")
    print(f"FOLLOW-UPS DUE — {today.strftime('%Y-%m-%d')}")
    print(f"{'=' * 70}")
    print(f"Overdue: {len(overdue)}  |  Due today: {len(due_today)}  |  Total due: {len(followups)}")
    print()

    if overdue:
        print("## OVERDUE")
        for f in overdue:
            days = abs(f["days_until_followup"])
            print(f"  ⚠ {f['organization']} ({f['segment']}, {f['country']})")
            print(f"    Overdue by {days}d | Status: {f['current_status']} | Priority: {f['priority']}")
            print(f"    Action: {f['suggested_action']}")
            print()

    if due_today:
        print("## DUE TODAY")
        for f in due_today:
            print(f"  • {f['organization']} ({f['segment']}, {f['country']})")
            print(f"    Status: {f['current_status']} | Priority: {f['priority']}")
            print(f"    Action: {f['suggested_action']}")
            print()


def cmd_plan(leads: list[dict]) -> None:
    """Generate a full follow-up plan for all leads."""
    today = datetime.now()
    plan = {"generated_at": today.isoformat(), "followups": []}

    for l in leads:
        fu = calculate_followup(l)
        if fu:
            plan["followups"].append(fu)
            save_followup(fu)

    # Sort by urgency
    plan["followups"].sort(key=lambda x: x["days_until_followup"])

    # Statistics
    total = len(plan["followups"])
    overdue = sum(1 for f in plan["followups"] if f["is_overdue"])
    this_week = sum(1 for f in plan["followups"] if 0 < f["days_until_followup"] <= 7)
    this_month = sum(1 for f in plan["followups"] if 7 < f["days_until_followup"] <= 30)

    # Status breakdown
    status_breakdown = Counter(f["current_status"] for f in plan["followups"])
    priority_breakdown = Counter(f["priority"] for f in plan["followups"])

    print(f"\n{'=' * 70}")
    print(f"FOLLOW-UP PLAN — {today.strftime('%Y-%m-%d')}")
    print(f"{'=' * 70}")
    print(f"Total follow-ups: {total}")
    print(f"  Overdue: {overdue}")
    print(f"  Due this week: {this_week}")
    print(f"  Due this month: {this_month}")
    print()
    print(f"Status breakdown: {dict(status_breakdown)}")
    print(f"Priority breakdown: {dict(priority_breakdown)}")

    # Save plan
    plan_path = FOLLOWUPS_DIR / f"plan_{today.strftime('%Y%m%d')}.json"
    plan_path.write_text(json.dumps(plan, indent=2, ensure_ascii=False))
    print(f"\n✓ Plan saved: {plan_path}")

    # Show top 10 urgent
    print(f"\n## TOP 10 URGENT")
    for f in plan["followups"][:10]:
        days = f["days_until_followup"]
        marker = "⚠" if days < 0 else "•"
        print(f"  {marker} [{days:+3}d] {f['organization']} ({f['current_status']}) — {f['suggested_action'][:50]}")


def cmd_execute(leads: list[dict]) -> None:
    """Draft follow-up emails for overdue/due leads."""
    today = datetime.now()
    drafted = 0

    for l in leads:
        fu = calculate_followup(l)
        if not fu or not fu["is_overdue"]:
            continue

        # Check if already in outreach queue
        queue = load_outreach_queue()
        already_queued = any(
            q.get("lead") == l.get("organization")
            for q in queue.get("queue", [])
        )
        if already_queued:
            continue

        # Try to use outreach_composer.py if available
        if OUTREACH_COMPOSER.exists():
            import subprocess
            lead_file = LEADS_DIR / f"{l.get('organization', '').lower().replace(' ', '-').replace('/', '-')}.json"
            if not lead_file.exists():
                # Find the actual file
                for f in LEADS_DIR.glob("*.json"):
                    if f.name == "schema.json":
                        continue
                    try:
                        data = json.loads(f.read_text())
                        if data.get("organization") == l.get("organization"):
                            lead_file = f
                            break
                    except Exception:
                        continue

            if lead_file.exists():
                result = subprocess.run(
                    [
                        sys.executable, str(OUTREACH_COMPOSER),
                        "--lead", lead_file.name,
                        "--purpose", f"follow-up: {fu['suggested_action'][:50]}",
                    ],
                    cwd=PROJECT_ROOT,
                    text=True,
                    capture_output=True,
                    timeout=30,
                )
                if result.returncode == 0:
                    drafted += 1
                    print(f"  ✓ Drafted follow-up for {fu['organization']}")
                else:
                    print(f"  ✗ Failed for {fu['organization']}: {result.stderr[:100]}")
            else:
                print(f"  ✗ Lead file not found for {fu['organization']}")
        else:
            # Fallback: create manual follow-up entry
            followup_entry = {
                "lead": l.get("organization"),
                "purpose": f"follow-up: {fu['suggested_action']}",
                "status": "drafted",
                "created_at": today.isoformat(),
                "followup_date": fu["next_followup_date"],
            }
            queue["queue"].append(followup_entry)
            drafted += 1
            print(f"  ✓ Queued follow-up for {fu['organization']}")

    # Save updated queue
    if drafted > 0:
        OUTREACH_QUEUE.parent.mkdir(parents=True, exist_ok=True)
        OUTREACH_QUEUE.write_text(json.dumps(queue, indent=2, ensure_ascii=False))

    print(f"\n{'=' * 70}")
    print(f"EXECUTE — {today.strftime('%Y-%m-%d')}")
    print(f"{'=' * 70}")
    print(f"Drafted: {drafted} follow-up emails")


def cmd_status(leads: list[dict]) -> None:
    """Follow-up statistics."""
    today = datetime.now()
    followups = []
    for l in leads:
        fu = calculate_followup(l)
        if fu:
            followups.append(fu)

    total = len(followups)
    overdue = sum(1 for f in followups if f["is_overdue"])
    this_week = sum(1 for f in followups if 0 < f["days_until_followup"] <= 7)
    this_month = sum(1 for f in followups if 7 < f["days_until_followup"] <= 30)
    future = sum(1 for f in followups if f["days_until_followup"] > 30)

    # Status distribution
    status_dist = Counter(f["current_status"] for f in followups)
    priority_dist = Counter(f["priority"] for f in followups)

    # Segment distribution
    seg_dist = Counter(f["segment"] for f in followups).most_common(10)

    print(f"\n{'=' * 70}")
    print(f"FOLLOW-UP STATUS — {today.strftime('%Y-%m-%d')}")
    print(f"{'=' * 70}")
    print(f"Total leads with follow-ups: {total}")
    print(f"  Overdue: {overdue} ({overdue/max(total,1):.0%})")
    print(f"  Due this week: {this_week}")
    print(f"  Due this month: {this_month}")
    print(f"  Future (>30d): {future}")
    print()
    print(f"Status: {dict(status_dist)}")
    print(f"Priority: {dict(priority_dist)}")
    print(f"Top segments: {seg_dist}")

    # Follow-up files count
    fu_files = list(FOLLOWUPS_DIR.glob("*.json"))
    print(f"\nFollow-up files in marketing/followups/: {len(fu_files)}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

COMMANDS = {
    "list": (cmd_list, "Show due/overdue follow-ups"),
    "plan": (cmd_plan, "Generate full follow-up plan"),
    "execute": (cmd_execute, "Draft follow-up emails"),
    "status": (cmd_status, "Follow-up statistics"),
}


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print("Usage: python scripts/followup_engine.py <command>")
        print(f"Commands: {', '.join(COMMANDS.keys())}")
        raise SystemExit(1)

    cmd = sys.argv[1]
    generator, description = COMMANDS[cmd]

    print(f"Follow-up engine — {description}")
    leads = load_leads()
    print(f"Loaded {len(leads)} leads from {LEADS_DIR}")

    generator(leads)


if __name__ == "__main__":
    main()
