#!/usr/bin/env python3
"""Talaix outreach composer — draft personalized commercial email.

Reads a lead record from the marketing workspace, applies the segment's
outreach style and evidence requirements, and produces a structured draft
(subject, body, evidence references, CTA, follow-up date). The draft is
queued for HUMAN review in marketing/outreach/queue.json and an
append-only audit line is written to marketing/outreach/audit.jsonl.

HARD RULES (test-enforced):

- The sender identity is always info@talaix.com — never a personal
  mailbox.
- This script never sends anything (no network, no SMTP). Sending is a
  separate, explicit, human-approved step.
- Drafts are personalized from the lead's recorded evidence; if the lead
  has no evidence/problem recorded, the script refuses — no generic spam.

Usage (from the platform directory):

    python scripts/outreach_composer.py --lead <org-slug>.json \
        --purpose "monitoring pilot" [--followup 2026-09-01]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, timedelta

ROOT = os.path.join(os.path.dirname(__file__), "..")
MARKETING = os.path.join(ROOT, "marketing")
OFFICIAL_SENDER = "info@talaix.com"
FORBIDDEN_SENDERS = ("motaz3d@gmail.com", "motazomarien@gmail.com")

QUEUE = os.path.join(MARKETING, "outreach", "queue.json")
AUDIT = os.path.join(MARKETING, "outreach", "audit.jsonl")


def _load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _default_followup() -> str:
    return (date.today() + timedelta(days=7)).isoformat()


def compose_draft(lead: dict, segment: dict, purpose: str,
                  followup: str | None = None) -> dict:
    """Build the personalized draft from the lead's recorded evidence.

    Refuses (ValueError) when the lead carries no problem/evidence — a
    message without evidence would be generic spam.
    """
    org = lead.get("organization") or ""
    problem = lead.get("identified_problem") or lead.get("potential_pain")
    evidence = lead.get("evidence") or lead.get("evidence_to_show")
    if not org or not problem or not evidence:
        raise ValueError(
            "lead lacks organization/problem/evidence — a personalized, "
            "evidence-based draft is impossible; research the lead first")
    product = (lead.get("recommended_product") or "free_analysis").replace("_", " ")
    hazards = ", ".join(lead.get("relevant_hazards") or []) or "climate extremes"
    role = lead.get("decision_maker_role") or "team"
    style = (segment or {}).get("outreach_style", "professional")

    subject = f"{org} — {hazards} exposure: evidence and a concrete next step"
    body = (
        f"Hello {org} {role},\n\n"
        f"Talaix is a Climate Extreme Intelligence platform — real "
        f"data, official sources, and evidence labels on every figure.\n\n"
        f"Why this message: {problem}.\n\n"
        f"What we can show you today, from real analysis:\n"
        f"  - {evidence}\n\n"
        f"The relevant Talaix capability: {product}. You can run a "
        f"free analysis at https://talaix.com/intelligence.html — "
        f"no account needed — and we are happy to walk you through the "
        f"evidence for your specific locations.\n\n"
        f"Every Talaix result carries its source, method and "
        f"limitations; unavailable data is stated, never filled in.\n\n"
        f"Would a short call make sense? I will follow up around "
        f"{followup or _default_followup()} if I don't hear back.\n\n"
        f"Best regards,\nTalaix\n{OFFICIAL_SENDER}\n"
        f"https://talaix.com"
    )
    return {
        "to": {"organization": org, "role": role,
               "contact_type": lead.get("contact_type", "organization_generic")},
        "from": OFFICIAL_SENDER,
        "purpose": purpose,
        "segment": lead.get("segment"),
        "style": style,
        "subject": subject,
        "body": body,
        "evidence_references": [evidence],
        "cta": "Run the free analysis / short call",
        "followup_date": followup or _default_followup(),
        "status": "drafted",
        "created": date.today().isoformat(),
    }


def queue_draft(lead_file: str, draft: dict) -> None:
    """Append to the human-gated queue + the append-only audit trail."""
    queue_doc = _load(QUEUE)
    queue_doc.setdefault("queue", []).append({"lead": lead_file, **draft})
    with open(QUEUE, "w", encoding="utf-8") as fh:
        json.dump(queue_doc, fh, indent=2)
        fh.write("\n")
    with open(AUDIT, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "date": draft["created"], "action": "draft_created",
            "lead": lead_file, "purpose": draft["purpose"],
            "from": draft["from"], "status": "drafted",
        }) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lead", required=True,
                        help="lead filename inside marketing/leads/")
    parser.add_argument("--purpose", required=True,
                        help="why this outreach, one phrase")
    parser.add_argument("--followup", default=None,
                        help="ISO date for the follow-up (default +7 days)")
    args = parser.parse_args()

    lead_path = os.path.join(MARKETING, "leads", args.lead)
    if not os.path.exists(lead_path):
        print(f"No such lead: {lead_path}")
        return 2
    lead = _load(lead_path)
    segments = _load(os.path.join(MARKETING, "segments", "segments.json"))["segments"]
    segment = segments.get(lead.get("segment"), {})

    try:
        draft = compose_draft(lead, segment, args.purpose, args.followup)
    except ValueError as exc:
        print(f"Cannot draft: {exc}")
        return 2

    assert draft["from"] == OFFICIAL_SENDER
    for forbidden in FORBIDDEN_SENDERS:
        assert forbidden not in draft["body"]

    queue_draft(args.lead, draft)
    print("=" * 60)
    print(f"FROM: {draft['from']}")
    print(f"TO: {draft['to']['organization']} ({draft['to']['role']})")
    print(f"SUBJECT: {draft['subject']}")
    print("-" * 60)
    print(draft["body"])
    print("-" * 60)
    print(f"Queued for HUMAN review in marketing/outreach/queue.json "
          f"(status: drafted). Nothing was sent.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
