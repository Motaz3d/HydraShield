#!/usr/bin/env python3
"""Build and schedule the European banking cold-outreach wave (wave 1).

Discovers contacts if needed, selects the best OBSERVED contact per lead,
and schedules outreach via MarketingStore.schedule_send.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src.dashboard import mailer  # noqa: E402
from src.dashboard.marketing_crm import _outreach_template_and_context  # noqa: E402
from src.dashboard.marketing_store import MarketingStore  # noqa: E402

LEADS_DIR = os.path.join(ROOT, "marketing", "leads")
OUT_DIR = os.path.join(ROOT, "marketing", "outreach")
OUT_JSON = os.path.join(OUT_DIR, "eu_banking_wave1.json")
OUT_MD = os.path.join(OUT_DIR, "eu_banking_wave1.md")

TEMPLATE = "outreach_banking"

ISO_CC = {
    "DE", "NL", "AT", "CH", "ES", "FR", "GB", "IT", "BE", "NO", "SE", "DK",
    "FI", "PL", "GR", "PT", "CZ", "IE", "RO", "HR",
}
NAME_TO_ISO = {
    "Germany": "DE", "Netherlands": "NL", "Austria": "AT", "Switzerland": "CH",
    "Spain": "ES", "France": "FR", "United Kingdom": "GB", "Italy": "IT",
    "Belgium": "BE", "Norway": "NO", "Sweden": "SE", "Denmark": "DK",
    "Finland": "FI", "Poland": "PL", "Greece": "GR", "Portugal": "PT",
    "Czech Republic": "CZ", "Ireland": "IE", "Romania": "RO", "Croatia": "HR",
}
COUNTRY_NAMES = {
    "DE": "Germany", "NL": "Netherlands", "AT": "Austria", "CH": "Switzerland",
    "ES": "Spain", "FR": "France", "GB": "United Kingdom", "IT": "Italy",
    "BE": "Belgium", "NO": "Norway", "SE": "Sweden", "DK": "Denmark",
    "FI": "Finland", "PL": "Poland", "GR": "Greece", "PT": "Portugal",
    "CZ": "Czech Republic", "IE": "Ireland", "RO": "Romania", "HR": "Croatia",
}

# Country priority for banking selection.
COUNTRY_PRIORITY = ["DE", "FR", "NL", "IT", "ES", "GB"]

BAD_LOCALPARTS = {
    "hr", "jobs", "job", "careers", "career", "recruitment", "recruit",
    "askhr", "talent", "hiring",
    "phishing", "abuse", "fraud", "security", "infosec", "soc", "cert",
    "incident", "spam", "postmaster", "webmaster", "hostmaster",
}

_BAD_VERIFICATIONS = {"invalid", "disposable"}


def _is_bad_inbox(address: str) -> bool:
    local = (address or "").split("@", 1)[0].lower()
    local = re.split(r"[._+\-]", local)[0] if local else ""
    return local in BAD_LOCALPARTS


def _canonical_country(cc: str) -> Optional[str]:
    cc = (cc or "").strip()
    if cc in ISO_CC:
        return cc
    return NAME_TO_ISO.get(cc)


def _iter_eu_banking_leads() -> List[Dict]:
    leads = []
    for path in sorted(glob.glob(os.path.join(LEADS_DIR, "*.json"))):
        if path.endswith("schema.json"):
            continue
        try:
            lead = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if (lead.get("segment") or "") != "banking":
            continue
        if _canonical_country(lead.get("country") or "") is None:
            continue
        lead["_slug"] = Path(path).stem
        leads.append(lead)
    return leads


def _best_observed_contact(contacts: List[Dict]) -> Optional[Dict]:
    pool = [
        c for c in contacts
        if c.get("email")
        and not _is_bad_inbox(c["email"])
        and (c.get("verification") or "").upper() == "OBSERVED"
        and (c.get("verification") or "").strip().lower() not in _BAD_VERIFICATIONS
    ]
    if not pool:
        return None
    pool.sort(key=lambda c: -(c.get("confidence") or 0))
    return pool[0]


def _best_any_contact(contacts: List[Dict]) -> Optional[Dict]:
    pool = [
        c for c in contacts
        if c.get("email")
        and not _is_bad_inbox(c["email"])
        and (c.get("verification") or "").strip().lower() not in _BAD_VERIFICATIONS
    ]
    if not pool:
        return None
    pool.sort(key=lambda c: -(c.get("confidence") or 0))
    return pool[0]


def _country_rank(lead: Dict) -> int:
    cc = _canonical_country(lead.get("country") or "") or ""
    if cc in COUNTRY_PRIORITY:
        return COUNTRY_PRIORITY.index(cc)
    return 100


def _already_scheduled(store: MarketingStore, slug: str) -> bool:
    for row in store.list_scheduled(lead_slug=slug, status="scheduled"):
        if row.get("template") == TEMPLATE:
            return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=12,
                        help="cap the number of sendable entries (default: 12)")
    parser.add_argument("--today-count", type=int, default=5,
                        help="number of rows to schedule for today (default: 5)")
    args = parser.parse_args()

    mailer.load_dotenv(os.path.join(ROOT, ".env"))
    mailer.load_dotenv(os.path.join(os.path.dirname(ROOT), ".env"))

    store = MarketingStore()
    leads = _iter_eu_banking_leads()

    selected: List[Dict] = []
    inferred_only: List[Dict] = []
    contact_gap: List[Dict] = []
    content_gap: List[Dict] = []
    unsubscribed: List[str] = []
    replied: List[str] = []
    already_emailed: List[str] = []
    already_scheduled_list: List[str] = []

    priority_rank = {"high": 0, "medium": 1, "low": 2}
    leads.sort(key=lambda l: (
        _country_rank(l),
        priority_rank.get((l.get("priority") or "").lower(), 99),
        (l.get("organization") or "").lower(),
    ))

    for lead in leads:
        slug = lead["_slug"]

        if not (lead.get("identified_problem") or "").strip() or not (lead.get("relevant_capability") or "").strip():
            content_gap.append(slug)
            continue

        if store.is_unsubscribed(slug):
            unsubscribed.append(slug)
            continue

        state = store.get_state(slug) or {}
        if state.get("outreach_status") == "replied":
            replied.append(slug)
            continue

        if any(i.get("type") == "email" for i in store.list_interactions(slug)):
            already_emailed.append(slug)
            continue

        if _already_scheduled(store, slug):
            already_scheduled_list.append(slug)
            continue

        contacts = store.list_contacts(slug)
        observed = _best_observed_contact(contacts)
        if observed:
            lead["_observed_contact"] = observed
            selected.append(lead)
            continue

        any_contact = _best_any_contact(contacts)
        if any_contact:
            inferred_only.append({
                "slug": slug,
                "org": lead.get("organization") or "",
                "country": lead.get("country") or "",
                "inferred_email": any_contact["email"],
                "claim_status": any_contact.get("verification") or "INFERRED",
                "website": lead.get("website") or "",
            })
        else:
            contact_gap.append({
                "slug": slug,
                "org": lead.get("organization") or "",
                "country": lead.get("country") or "",
                "website": lead.get("website") or "",
            })

    if args.limit and len(selected) > args.limit:
        selected = selected[:args.limit]

    # Schedule: first N today at 13:05, 13:10, ..., rest tomorrow starting 08:05.
    schedule: List[Dict] = []
    today_count = min(args.today_count, len(selected))
    for i, lead in enumerate(selected):
        slug = lead["_slug"]
        observed = lead["_observed_contact"]
        if i < today_count:
            send_at = f"2026-09-03T13:{5 + 5 * i:02d}:00"
        else:
            j = i - today_count
            send_at = f"2026-09-04T08:{5 + 5 * j:02d}:00"

        template, context = _outreach_template_and_context(
            lead,
            {"contact_name": observed.get("name") or "there", "custom_message": ""},
        )
        if observed.get("name"):
            context["contact_name"] = observed["name"].strip()

        row = store.schedule_send(
            lead_slug=slug,
            to_email=observed["email"],
            contact_name=context.get("contact_name") or None,
            template=template,
            context=context,
            send_at=send_at,
        )
        if row is None:
            print(f"WARNING: schedule_send returned None for {slug}", file=sys.stderr)
            continue

        rendered = mailer.render_template(template, context)
        schedule.append({
            "slug": slug,
            "organization": lead.get("organization") or "",
            "country": lead.get("country") or "",
            "canonical_country": _canonical_country(lead.get("country") or ""),
            "to_email": observed["email"],
            "claim_status": observed.get("verification") or "OBSERVED",
            "contact_confidence": observed.get("confidence"),
            "contact_source": observed.get("source"),
            "send_at": send_at,
            "template": template,
            "subject": rendered["subject"],
            "body": rendered["text"],
        })

    Path(OUT_DIR).mkdir(parents=True, exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as fh:
        json.dump(
            [
                {
                    "slug": s["slug"],
                    "organization": s["organization"],
                    "country": s["country"],
                    "to_email": s["to_email"],
                    "claim_status": s["claim_status"],
                    "send_at": s["send_at"],
                }
                for s in schedule
            ],
            fh,
            indent=2,
            ensure_ascii=False,
        )
        fh.write("\n")

    lines: List[str] = []
    lines.append("# Talaix — European Banking Outreach Wave 1")
    lines.append("")
    lines.append("> Status: scheduled for automatic send via the platform cron. Nothing is sent by this script.")
    lines.append("> Cron: scripts/process_scheduled_outreach.py every 5 min, 07:00–17:00 UTC, cap 20/day.")
    lines.append("")
    lines.append("## Filter rules (binding)")
    lines.append("")
    lines.append("- Segment: banking.")
    lines.append("- Geography: European countries.")
    lines.append("- Contacts: OBSERVED only; INFERRED addresses are never mailed.")
    lines.append("- Skip unsubscribed, replied, and already-emailed leads.")
    lines.append("- Exclude leads with empty identified_problem or relevant_capability.")
    lines.append("- Recruitment / abuse inboxes are never outreach targets.")
    lines.append("- Verification verdicts 'invalid' or 'disposable' are never mailed.")
    lines.append(f"- Template: `{TEMPLATE}`.")
    lines.append("")

    per_country = Counter(s["canonical_country"] for s in schedule)
    lines.append(
        f"## Summary: {len(schedule)} scheduled | "
        f"{len(content_gap)} content-gap | "
        f"{len(inferred_only)} inferred-only | "
        f"{len(contact_gap)} contact-gap | "
        f"{len(unsubscribed)} unsubscribed | "
        f"{len(replied)} replied | "
        f"{len(already_emailed)} already-emailed | "
        f"{len(already_scheduled_list)} already-scheduled"
    )
    lines.append("")
    lines.append("### Per-country breakdown")
    lines.append("")
    for cc in sorted(per_country):
        lines.append(f"- {COUNTRY_NAMES.get(cc, cc)} ({cc}): {per_country[cc]}")
    lines.append("")
    if schedule:
        lines.append(f"**First send_at:** {schedule[0]['send_at']} UTC")
        lines.append(f"**Last send_at:** {schedule[-1]['send_at']} UTC")
        lines.append("")

    for i, s in enumerate(schedule, 1):
        lines.append(f"## {i}. {s['organization']} — {COUNTRY_NAMES.get(s['canonical_country'], s['country'])}")
        lines.append("")
        lines.append(f"- slug: `{s['slug']}`")
        lines.append(f"- to_email: {s['to_email']} ({s['claim_status']}, confidence {s.get('contact_confidence') or '—'}, source {s.get('contact_source') or '—'})")
        lines.append(f"- send_at: `{s['send_at']}` UTC")
        lines.append(f"- template: `{s['template']}`")
        lines.append("")
        lines.append(f"**Subject:** {s['subject']}")
        lines.append("")
        lines.append("```")
        lines.append(s["body"].rstrip())
        lines.append("```")
        lines.append("")

    if inferred_only:
        lines.append("## INFERRED contacts — human verification required")
        lines.append("")
        for r in inferred_only:
            lines.append(f"- {r['org']} ({r['country']}, `{r['slug']}`): {r['inferred_email']}")
        lines.append("")

    if contact_gap:
        lines.append("## Contact gap — manual discovery needed")
        lines.append("")
        for r in contact_gap:
            lines.append(f"- {r['org']} ({r['country']}, `{r['slug']}`)")
        lines.append("")

    lines.append("---")
    lines.append(f"Built at {datetime.utcnow().isoformat()[:19]} UTC. Status: scheduled — the cron will send.")

    with open(OUT_MD, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")

    print(f"Scheduled: {len(schedule)} EU banking leads")
    print(f"JSON:      {OUT_JSON}")
    print(f"Markdown:  {OUT_MD}")
    print(f"Today: {today_count}, Tomorrow: {len(schedule) - today_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
