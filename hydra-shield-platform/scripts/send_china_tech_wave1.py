#!/usr/bin/env python3
"""ChinaTechWave1 — independent outreach wave to Chinese climate/EO technology vendors.

Standalone campaign: its own data file, its own daily ceiling (default 22/day) and its
own pacing (a randomised gap between messages). It is NOT part of any other wave, and
per operator instruction it is not governed by the other campaigns' window/cap rails
(use --independent to state that explicitly; the default stays conservative).

Safety design:
  * DRY RUN by default — nothing is sent unless --send is passed AND SMTP is configured.
  * Idempotent — a message already logged for a slug/email is never re-sent.
  * Honours unsubscribes and prior replies.
  * Paces sends: random gap between messages so the wave does not burst.

Usage:
    python scripts/send_china_tech_wave1.py                          # dry run, prints everything
    python scripts/send_china_tech_wave1.py --send --independent     # live, 22/day, paced
    python scripts/send_china_tech_wave1.py --send --max-per-day 5 --gap-min 5 --gap-max 9
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from datetime import date, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from src.dashboard import mailer  # noqa: E402
from src.dashboard.marketing_store import MarketingStore  # noqa: E402

DATA_PATH = BASE / "marketing" / "outreach" / "china_tech_wave1.json"
LEADS_DIR = BASE / "marketing" / "leads"

WAVE_LABEL = "ChinaTechWave1"
TEMPLATE = "outreach_china_tech"
FOLLOWUP_DAYS = 7

DEFAULT_WAVE_CAP = 22          # this campaign's own ceiling: max 22 messages per day
DEFAULT_GAP_MIN = 6.0          # minutes between messages (paced, not bursty)
DEFAULT_GAP_MAX = 13.0


def load_env() -> None:
    """Load .env from the platform dir and its parent (does not overwrite real env)."""
    for candidate in (BASE / ".env", BASE.parent / ".env"):
        if not candidate.exists():
            continue
        for raw in candidate.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def already_sent(store: MarketingStore, slug: str, email: str) -> bool:
    marker = f"{WAVE_LABEL} outreach email sent to {email}"
    return any(marker in (row.get("summary") or "") for row in store.list_interactions(slug))


def _lead_context(slug: str, entry: dict) -> dict:
    """Build the template context: campaign copy first, lead record as fallback."""
    context = {
        "organization": entry.get("org", ""),
        "contact_name": entry.get("contact_name", ""),
        "subject_line": entry.get("subject", ""),
        "opening": entry.get("opening", ""),
        "requested_items": entry.get("requested_items", ""),
        "technical_questions": entry.get("technical_questions", ""),
        "custom_message": entry.get("custom_message", ""),
        "unsubscribe_url": mailer.unsubscribe_mailto(),
    }
    lead_path = LEADS_DIR / f"{slug}.json"
    if lead_path.exists():
        try:
            lead = json.loads(lead_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            lead = {}
        for key in ("organization", "contact_name"):
            if not context.get(key) and lead.get(key):
                context[key] = lead[key]
    return context


def _in_window(now: time.struct_time) -> bool:
    start = os.environ.get("OUTREACH_WINDOW_START", "07:00")
    end = os.environ.get("OUTREACH_WINDOW_END", "17:00")
    try:
        sh, sm = (int(x) for x in start.split(":"))
        eh, em = (int(x) for x in end.split(":"))
    except ValueError:
        return True
    minutes = now.tm_hour * 60 + now.tm_min
    return sh * 60 + sm <= minutes <= eh * 60 + em


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--send", action="store_true", help="actually send (default: dry run)")
    parser.add_argument("--max-per-day", type=int, default=DEFAULT_WAVE_CAP,
                        help="ceiling for this campaign per day (default 22)")
    parser.add_argument("--gap-min", type=float, default=DEFAULT_GAP_MIN, help="min minutes between sends")
    parser.add_argument("--gap-max", type=float, default=DEFAULT_GAP_MAX, help="max minutes between sends")
    parser.add_argument("--only", default="", help="send only this slug (dry run preview helper)")
    parser.add_argument("--independent", action="store_true",
                        help="campaign-specific rails: ignore OUTREACH_WINDOW and the platform DAILY_SEND_CAP")
    parser.add_argument("--ignore-window", action="store_true", help="ignore OUTREACH_WINDOW_* only")
    args = parser.parse_args()

    load_env()
    dry = not args.send
    if args.send and not mailer.smtp_configured():
        print("WARNING: --send given but SMTP_HOST is not set; falling back to dry run.")
        dry = True

    entries = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    if args.only:
        entries = [e for e in entries if e["slug"] == args.only]

    wave_cap = args.max_per_day
    platform_cap = int(os.environ.get("DAILY_SEND_CAP", "15") or 15)

    today = date.today()
    followup = (today + timedelta(days=FOLLOWUP_DAYS)).isoformat()
    store = MarketingStore()

    if not dry and not (args.independent or args.ignore_window) and not _in_window(time.localtime()):
        print("Outside OUTREACH_WINDOW (UTC) — stopping. Use --independent or --ignore-window to override.")
        return 0

    sent = 0
    skipped = 0
    total = len(entries)
    for index, entry in enumerate(entries):
        slug = entry["slug"]
        email = entry["email"]
        if store.is_unsubscribed(slug):
            print(f"[skipped — unsubscribed] {slug}")
            skipped += 1
            continue
        state = store.get_state(slug)
        if state and state.get("outreach_status") == "replied":
            print(f"[skipped — already replied] {slug}")
            skipped += 1
            continue
        if already_sent(store, slug, email):
            print(f"[skipped — already sent] {slug} -> {email}")
            skipped += 1
            continue
        if sent >= wave_cap:
            print(f"[campaign cap reached — {total - index} entries stay for the next run]")
            break
        if not args.independent and store.sent_today_count() >= platform_cap:
            print(f"[platform cap reached — {total - index} entries stay for the next run]")
            break

        context = _lead_context(slug, entry)
        if dry:
            rendered = mailer.render_template(TEMPLATE, context)
            print("=" * 70)
            print(f"TO: {email} — {entry['org']} ({entry.get('segment', '')}, {entry.get('city', 'CN')})")
            print("SUBJECT: " + (entry.get("subject") or rendered["subject"]))
            print(rendered["text"].rstrip())
            continue

        mailer.send_mail(email, TEMPLATE, context, subject_override=entry.get("subject") or None)
        store.add_interaction(slug, f"{WAVE_LABEL} outreach email sent to {email}", type="email")
        store.update_state(slug, outreach_status="contacted", next_followup=followup)
        sent += 1
        print(f">>> SENT {sent}/{wave_cap}  {slug} -> {email}", flush=True)
        if sent < wave_cap and index < total - 1:
            gap = random.uniform(args.gap_min, args.gap_max) * 60
            print(f"    pacing: waiting {gap / 60:.1f} min before the next message…", flush=True)
            time.sleep(gap)

    print("=" * 70)
    if dry:
        print("DRY RUN — nothing was sent. Shown above for review.")
        print(f"Total targets: {total} (skipped: {skipped})")
    else:
        print(f"Completed sends today: {sent} of {total} (skipped: {skipped}, cap: {wave_cap}/day)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
