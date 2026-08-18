#!/usr/bin/env python3
"""HydraShield marketing workspace status — the AI copilot's entry point.

Reads the repository-based marketing workspace (marketing/) and prints the
current state: segments, leads by status, campaigns, content drafts,
outreach queue depth, and suggested next actions. Fully offline; no
writes. Run from the platform directory:

    python scripts/marketing_status.py

The workspace is the memory (marketing/README.md); this script is the
quick orientation so a session starts from the repo, not from recall.
"""

from __future__ import annotations

import json
import os
import sys

ROOT = os.path.join(os.path.dirname(__file__), "..")
MARKETING = os.path.join(ROOT, "marketing")

LEAD_STATUSES = ["researched", "qualified", "draft_prepared", "contacted",
                 "responded", "opportunity", "closed_lost"]
DRAFT_STATUSES = ["draft", "reviewed", "queued", "published", "retired"]


def _load_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def workspace_integrity():
    """Validate the workspace: segments parse, leads follow the schema's
    required fields and honesty rules, campaigns reference real segments."""
    problems = []
    seg_path = os.path.join(MARKETING, "segments", "segments.json")
    segments = _load_json(seg_path)["segments"]

    leads_dir = os.path.join(MARKETING, "leads")
    leads = []
    for name in sorted(os.listdir(leads_dir)):
        if not name.endswith(".json") or name == "schema.json":
            continue
        lead = _load_json(os.path.join(leads_dir, name))
        leads.append((name, lead))
        for field in ("organization", "segment", "country", "website",
                      "source", "date_checked"):
            if not lead.get(field):
                problems.append(f"{name}: missing required field '{field}'")
        if lead.get("segment") and lead["segment"] not in segments:
            problems.append(f"{name}: unknown segment '{lead['segment']}'")
        status = lead.get("outreach_status", "researched")
        if status not in LEAD_STATUSES:
            problems.append(f"{name}: unknown outreach_status '{status}'")

    camp_path = os.path.join(MARKETING, "campaigns", "linkedin_campaigns.json")
    campaigns = []
    if os.path.exists(camp_path):
        campaigns = _load_json(camp_path)["campaigns"]
        for camp in campaigns:
            for seg in camp.get("audience", {}).get("segments", []):
                if seg not in segments:
                    problems.append(
                        f"campaign {camp['id']}: unknown segment '{seg}'")
    return segments, leads, campaigns, problems


def main() -> int:
    segments, leads, campaigns, problems = workspace_integrity()

    print("HYDRASHIELD MARKETING STATUS")
    print("=" * 60)
    print(f"Segments defined: {len(segments)}")

    by_status = {s: 0 for s in LEAD_STATUSES}
    for _name, lead in leads:
        by_status[lead.get("outreach_status", "researched")] += 1
    print(f"Leads: {len(leads)}  " +
          " ".join(f"{k}={v}" for k, v in by_status.items() if v))

    print(f"Campaigns: {len(campaigns)} " +
          f"({', '.join(c['id'] for c in campaigns)})" if campaigns else
          "Campaigns: 0")

    drafts_dir = os.path.join(MARKETING, "content", "drafts")
    drafts = [d for d in sorted(os.listdir(drafts_dir)) if d.endswith(".md")] \
        if os.path.isdir(drafts_dir) else []
    print(f"Content drafts: {len(drafts)}")
    for d in drafts:
        head = open(os.path.join(drafts_dir, d), encoding="utf-8").read(400)
        status = "draft"
        for line in head.splitlines():
            if line.startswith("status:"):
                status = line.split(":", 1)[1].strip()
                break
        print(f"  - {d} [{status}]")

    queue_path = os.path.join(MARKETING, "outreach", "queue.json")
    queue = _load_json(queue_path).get("queue", [])
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
    if not queue:
        print("  · Outreach queue empty — qualify a lead and prepare a draft")
    unpublished = [d for d in drafts if "[published]" not in d]
    if unpublished:
        print(f"  · {len(unpublished)} draft(s) awaiting human review/publish")
    if not problems and leads and queue:
        print("  · Review queue entries pending human execution")
    return 0


if __name__ == "__main__":
    sys.exit(main())
