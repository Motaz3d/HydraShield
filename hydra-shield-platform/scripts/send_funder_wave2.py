#!/usr/bin/env python3
"""Send Funders Wave 2 from a JSON table. For Vultr where SMTP secrets live.

Safety rules (aligned with the media wave sender):
- DRY RUN by default: prints every message and sends NOTHING.
  Sending requires the explicit --send flag AND SMTP being configured.
- Leads that unsubscribed or already replied are skipped.
- Respects the platform daily cap (DAILY_SEND_CAP, counted across every
  send path) and the smaller WAVE_DAILY_CAP for this script.
- Idempotent: an entry whose wave email was already logged as sent is
  skipped, so a re-run never double-mails a funder.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from src.dashboard import mailer
from src.dashboard.marketing_store import MarketingStore

SENDER_NAME = "Motaz OMARIEN - initiator, Talaix"
DATA_PATH = os.path.join(BASE, "marketing", "outreach", "funders_wave2.json")
FOLLOWUP_DAYS = 7
WAVE_LABEL = "Wave2"
DAILY_CAP = int(os.environ.get("WAVE_DAILY_CAP", "10"))
PLATFORM_CAP = int(os.environ.get("DAILY_SEND_CAP", "20"))


def already_sent(store: MarketingStore, slug: str, email: str) -> bool:
    """True when this wave's email to this address is already logged."""
    marker = f"{WAVE_LABEL} funder outreach email sent to {email}"
    return any(
        i.get("type") == "email" and marker in (i.get("summary") or "")
        for i in store.list_interactions(slug)
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--send", action="store_true",
                    help="actually send (default: dry run)")
    args = ap.parse_args()

    mailer.load_dotenv(os.path.join(BASE, ".env"))
    mailer.load_dotenv(os.path.join(os.path.dirname(BASE), ".env"))

    with open(DATA_PATH, encoding="utf-8") as fh:
        entries = json.load(fh)
    followup = (date.today() + timedelta(days=FOLLOWUP_DAYS)).isoformat()

    dry = not args.send or os.environ.get("WAVE_DRY_RUN", "").strip().lower() in ("1", "true", "yes", "on")
    if not dry and not mailer.smtp_configured():
        print("WARNING: --send given but SMTP_HOST is not set; falling back to dry run.",
              file=sys.stderr)
        dry = True

    store = MarketingStore()
    sent = 0
    total = len(entries)
    print("=" * 70)
    print(f"{WAVE_LABEL} funders | entries: {total} | mode: {'SEND' if not dry else 'DRY RUN'}")
    print(f"caps: wave {DAILY_CAP}/run, platform {PLATFORM_CAP}/day")
    print("=" * 70)
    for entry in entries:
        if sent >= DAILY_CAP or store.sent_today_count() >= PLATFORM_CAP:
            print("[cap reached — remaining entries stay for the next run]")
            break
        slug = entry["slug"]
        email = entry["email"]
        if store.is_unsubscribed(slug):
            print(f"[skipped — unsubscribed] {slug}")
            continue
        state = store.get_state(slug)
        if state and state.get("outreach_status") == "replied":
            print(f"[skipped — already replied] {slug}")
            continue
        if already_sent(store, slug, email):
            print(f"[skipped — already sent] {slug} -> {email}")
            continue
        context = {
            "organization": entry["org"],
            "programme": entry["programme"],
            "contact_name": entry["role"],
            "programme_context": entry["context"],
            "ask": entry["ask"],
            "followup_date": followup,
            "signer": SENDER_NAME,
        }
        if dry:
            rendered = mailer.render_template("outreach_funders", context)
            print("=" * 70)
            print("TO: " + email + " - " + entry["org"])
            print("SUBJECT: " + rendered["subject"])
            print(rendered["text"].rstrip())
        else:
            mailer.send_mail(email, "outreach_funders", context)
            store.add_interaction(
                slug,
                f"{WAVE_LABEL} funder outreach email sent to {email}",
                type="email",
            )
            sent = sent + 1
            print(f">>> SENT {slug} -> {email}")
    if dry:
        print("=" * 70)
        print("DRY RUN - nothing was sent. Shown above for review.")
        print("Total targets: " + str(total))
    else:
        print("Completed sends today: " + str(sent) + " of " + str(total))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
