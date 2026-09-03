#!/usr/bin/env python3
"""Fill the DE insurance gap for the 2026-09 send plan.

Discovers additional DE insurance contacts (already done by the operator
separately), selects up to 6 eligible leads, schedules them at the front of
tomorrow's insurance queue, and shifts the existing tomorrow insurance rows
later by 5 minutes per inserted lead.
"""

from __future__ import annotations

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
OUT_JSON = os.path.join(OUT_DIR, "eu_insurance_wave1.json")
OUT_MD = os.path.join(OUT_DIR, "eu_insurance_wave1.md")

TEMPLATE = "outreach_insurance"

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


def _iter_de_insurance_leads() -> List[Dict]:
    leads = []
    for path in sorted(glob.glob(os.path.join(LEADS_DIR, "*.json"))):
        if path.endswith("schema.json"):
            continue
        try:
            lead = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if (lead.get("segment") or "") != "insurance":
            continue
        if (lead.get("country") or "").upper() != "DE":
            continue
        lead["_slug"] = Path(path).stem
        leads.append(lead)
    return leads


def _already_scheduled(store: MarketingStore, slug: str) -> bool:
    for row in store.list_scheduled(lead_slug=slug, status="scheduled"):
        if row.get("template") == TEMPLATE:
            return True
    return False


def main() -> int:
    mailer.load_dotenv(os.path.join(ROOT, ".env"))
    mailer.load_dotenv(os.path.join(os.path.dirname(ROOT), ".env"))

    store = MarketingStore()

    # Select eligible new DE insurance leads.
    leads = _iter_de_insurance_leads()
    priority_rank = {"high": 0, "medium": 1, "low": 2}
    leads.sort(key=lambda l: (
        priority_rank.get((l.get("priority") or "").lower(), 99),
        (l.get("organization") or "").lower(),
    ))

    new_leads: List[Dict] = []
    for lead in leads:
        slug = lead["_slug"]
        if not (lead.get("identified_problem") or "").strip() or not (lead.get("relevant_capability") or "").strip():
            continue
        if store.is_unsubscribed(slug):
            continue
        state = store.get_state(slug) or {}
        if state.get("outreach_status") == "replied":
            continue
        if any(i.get("type") == "email" for i in store.list_interactions(slug)):
            continue
        if _already_scheduled(store, slug):
            continue
        contacts = store.list_contacts(slug)
        observed = _best_observed_contact(contacts)
        if observed:
            lead["_observed_contact"] = observed
            new_leads.append(lead)
            if len(new_leads) >= 6:
                break

    if not new_leads:
        print("No new eligible DE insurance leads with OBSERVED contacts.")
        return 0

    # Shift existing tomorrow insurance rows (2026-09-04) later by N*5 minutes.
    n = len(new_leads)
    scheduled_rows = store.list_scheduled(status="scheduled")
    tomorrow_insurance = sorted(
        [r for r in scheduled_rows
         if r.get("template") == TEMPLATE and r["send_at"].startswith("2026-09-04")],
        key=lambda r: r["send_at"],
    )

    from datetime import timedelta
    for row in tomorrow_insurance:
        old = datetime.fromisoformat(row["send_at"])
        new = old + timedelta(minutes=5 * n)
        new_send_at = new.strftime("%Y-%m-%dT%H:%M:%S")
        store.reschedule_scheduled(row["id"], new_send_at)

    # Schedule new DE leads at the front: 07:05, 07:10, ..., 07:05+5*(n-1).
    scheduled_new: List[Dict] = []
    for i, lead in enumerate(new_leads):
        slug = lead["_slug"]
        observed = lead["_observed_contact"]
        send_at = f"2026-09-04T07:{5 + 5 * i:02d}:00"

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
        scheduled_new.append({
            "slug": slug,
            "organization": lead.get("organization") or "",
            "country": "DE",
            "to_email": observed["email"],
            "claim_status": observed.get("verification") or "OBSERVED",
            "send_at": send_at,
        })

    print(f"Added {len(scheduled_new)} new DE insurance leads")
    for s in scheduled_new:
        print(f"  {s['send_at']} | {s['slug']} | {s['to_email']}")
    print(f"Shifted {len(tomorrow_insurance)} existing tomorrow insurance rows by {5 * n} minutes")

    # Re-write review artifacts with updated counts.
    _rewrite_artifacts(store)
    return 0


def _rewrite_artifacts(store: MarketingStore) -> None:
    rows = store.list_scheduled(status="scheduled")
    insurance_rows = [r for r in rows if r.get("template") == "outreach_insurance"]

    # Load lead data for each row.
    by_slug: Dict[str, Dict] = {}
    for p in glob.glob(os.path.join(LEADS_DIR, "*.json")):
        if p.endswith("schema.json"):
            continue
        try:
            lead = json.loads(Path(p).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        by_slug[Path(p).stem] = lead

    entries = []
    for r in sorted(insurance_rows, key=lambda x: x["send_at"]):
        lead = by_slug.get(r["lead_slug"], {})
        entries.append({
            "slug": r["lead_slug"],
            "organization": lead.get("organization") or "",
            "country": lead.get("country") or "",
            "to_email": r["to_email"],
            "claim_status": "OBSERVED",
            "send_at": r["send_at"],
        })

    Path(OUT_DIR).mkdir(parents=True, exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as fh:
        json.dump(entries, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    per_country = Counter((e["country"] or "?") for e in entries)
    lines = [
        "# Talaix — European Insurance Outreach Wave 1",
        "",
        "> Status: scheduled for automatic send via the platform cron. Nothing is sent by this script.",
        "> Cron: scripts/process_scheduled_outreach.py every 5 min, 07:00–17:00 UTC, cap 20/day.",
        "",
        f"## Summary: {len(entries)} scheduled",
        "",
        "### Per-country breakdown",
        "",
    ]
    for cc in sorted(per_country):
        lines.append(f"- {cc}: {per_country[cc]}")
    lines.append("")
    if entries:
        lines.append(f"**First send_at:** {entries[0]['send_at']} UTC")
        lines.append(f"**Last send_at:** {entries[-1]['send_at']} UTC")
        lines.append("")
    lines.append("## Machine-readable rows")
    lines.append("")
    lines.append("See `eu_insurance_wave1.json`.")
    lines.append("")
    lines.append("---")
    lines.append(f"Updated at {datetime.utcnow().isoformat()[:19]} UTC.")

    with open(OUT_MD, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
