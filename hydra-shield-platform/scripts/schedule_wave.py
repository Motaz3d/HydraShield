#!/usr/bin/env python3
"""Generic wave scheduler: queue an operator-approved outreach wave (JSON
table) into the marketing_store scheduled_outreach table, drained by the
email cron (scripts/email_cron.sh → process_scheduled_outreach.py).

Safety rules (same discipline as the other wave senders):
- DRY RUN by default: prints every row and schedules NOTHING.
  Writing requires the explicit --schedule flag (operator approval).
- Entries with channel "webform" (no published email) are NEVER scheduled —
  the operator submits those manually through the official form.
- Unsubscribed or already-replied slugs are skipped.
- Idempotent: a slug that already has a scheduled/sent row for the same
  template is skipped, so a re-run never double-queues.
- Pacing lives in the JSON send_at values; the platform cap DAILY_SEND_CAP
  and the OUTREACH_WINDOW are enforced by the processor at send time.

Usage:
    .venv/bin/python scripts/schedule_wave.py marketing/outreach/WAVE.json TEMPLATE
    .venv/bin/python scripts/schedule_wave.py marketing/outreach/WAVE.json TEMPLATE --schedule
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

CONTEXT_KEYS = (
    "contact_name", "organization", "country", "identified_problem",
    "relevant_capability", "recommended_product", "custom_message",
    "thesis_hook", "portfolio_overlap",
)


def already_queued(store: MarketingStore, slug: str, template: str) -> bool:
    return any(
        r.get("template") == template and r.get("status") in ("scheduled", "sent")
        for r in store.list_scheduled(lead_slug=slug)
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("json_path", help="wave JSON table (marketing/outreach/…)")
    ap.add_argument("template", help="mailer template name")
    ap.add_argument("--schedule", action="store_true",
                    help="actually write rows (default: dry run)")
    args = ap.parse_args()
    dry = not args.schedule

    with open(args.json_path, encoding="utf-8") as fh:
        entries = json.load(fh)
    email_entries = [e for e in entries if e.get("to_email")]
    webform_entries = [e for e in entries if e.get("channel") == "webform"]

    store = MarketingStore()
    label = os.path.basename(args.json_path)
    print("=" * 70)
    print(f"{label} | template {args.template} | email: {len(email_entries)} | "
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
        if already_queued(store, slug, args.template):
            print(f"[skipped — already queued/sent] {slug}")
            skipped += 1
            continue
        context = {k: entry.get(k) or "" for k in CONTEXT_KEYS}
        context["contact_name"] = entry.get("contact_name") or "there"
        context["organization"] = entry["organization"]
        context["unsubscribe_url"] = mailer.unsubscribe_mailto()
        if dry:
            rendered = mailer.render_template(args.template, context)
            print(f"[would schedule] {entry['send_at']}  {slug:<28}"
                  f" -> {entry['to_email']}")
            print(f"    SUBJECT: {rendered['subject']}")
        else:
            row = store.schedule_send(
                slug, entry["to_email"], entry.get("contact_name"),
                args.template, context, entry["send_at"],
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
              f"{len(email_entries) - skipped} row(s) ready; add --schedule.")
    else:
        print(f"Scheduled {queued} row(s); skipped {skipped}. "
              f"The email cron sends them when their send_at is due.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
