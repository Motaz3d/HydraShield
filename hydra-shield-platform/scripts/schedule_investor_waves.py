#!/usr/bin/env python3
"""Schedule the operator-approved investor outreach wave (A/B/C) into the
marketing_store scheduled_outreach table — the queue the email cron
(scripts/email_cron.sh → process_scheduled_outreach.py) drains every 5
minutes on this machine.

Safety rules (same discipline as the other wave senders):
- DRY RUN by default: prints every row and schedules NOTHING.
  Writing requires the explicit --schedule flag (operator approval 2026-09-07).
- Entries with channel "webform" (no published email) are NEVER scheduled —
  the operator submits those manually through the official form.
- Unsubscribed or already-replied slugs are skipped.
- Idempotent: a slug that already has a scheduled/sent row for the
  outreach_investor template is skipped, so a re-run never double-queues.
- Pacing lives in the JSON send_at values (11 on 2026-09-08 + 4 on
  2026-09-09, 15-minute stagger); the platform cap DAILY_SEND_CAP=15 and the
  OUTREACH_WINDOW 07:00-17:00 UTC are enforced by the processor at send time.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from src.dashboard import mailer  # noqa: E402
from src.dashboard.marketing_store import MarketingStore  # noqa: E402

DATA_PATH = os.path.join(BASE, "marketing", "outreach", "investor_waves_abc.json")
TEMPLATE = "outreach_investor"


def already_queued(store: MarketingStore, slug: str) -> bool:
    """True when this slug already has a live or completed investor-wave row."""
    return any(
        r.get("template") == TEMPLATE and r.get("status") in ("scheduled", "sent")
        for r in store.list_scheduled(lead_slug=slug)
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--schedule", action="store_true",
                    help="actually write rows (default: dry run)")
    args = ap.parse_args()
    dry = not args.schedule

    with open(DATA_PATH, encoding="utf-8") as fh:
        entries = json.load(fh)
    email_entries = [e for e in entries if e.get("to_email")]
    webform_entries = [e for e in entries if e.get("channel") == "webform"]

    store = MarketingStore()
    print("=" * 70)
    print(f"InvestorWaveABC | email targets: {len(email_entries)} | "
          f"webform-manual: {len(webform_entries)} | "
          f"mode: {'DRY RUN' if dry else 'SCHEDULE'}")
    print("=" * 70)

    queued = skipped = 0
    for entry in email_entries:
        slug = entry["slug"]
        if store.is_unsubscribed(slug):
            print(f"[skipped — unsubscribed] {slug}")
            skipped += 1
            continue
        state = store.get_state(slug)
        if state and state.get("outreach_status") == "replied":
            print(f"[skipped — already replied] {slug}")
            skipped += 1
            continue
        if already_queued(store, slug):
            print(f"[skipped — already queued/sent] {slug}")
            skipped += 1
            continue
        context = {
            "contact_name": entry.get("contact_name") or "there",
            "organization": entry["organization"],
            "thesis_hook": entry.get("thesis_hook") or "",
            "portfolio_overlap": entry.get("portfolio_overlap") or "",
            "custom_message": entry.get("custom_message") or "",
            "unsubscribe_url": mailer.unsubscribe_mailto(),
        }
        if dry:
            rendered = mailer.render_template(TEMPLATE, context)
            print(f"[would schedule] {entry['send_at']}  {slug:<28}"
                  f" -> {entry['to_email']}")
            print(f"    SUBJECT: {rendered['subject']}")
        else:
            row = store.schedule_send(
                slug, entry["to_email"], entry.get("contact_name"),
                TEMPLATE, context, entry["send_at"],
            )
            if row is None:
                print(f"[FAILED validation] {slug} — not queued")
                skipped += 1
                continue
            queued += 1
            print(f">>> QUEUED #{row['id']} {entry['send_at']}  {slug}"
                  f" -> {entry['to_email']}")

    if webform_entries:
        print("-" * 70)
        print("Webform-only (operator submits manually — never auto-scheduled):")
        for e in webform_entries:
            print(f"  · {e['organization']}: {e['form_url']}")
    print("=" * 70)
    if dry:
        print(f"DRY RUN — nothing was scheduled. "
              f"{len(email_entries) - skipped} row(s) ready; re-run with "
              f"--schedule to write them.")
    else:
        print(f"Scheduled {queued} row(s); skipped {skipped}. "
              f"The email cron sends them when their send_at is due.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
