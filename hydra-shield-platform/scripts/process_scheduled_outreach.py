#!/usr/bin/env python3
"""Talaix scheduled outreach processor.

Polls the marketing_store scheduled_outreach table and sends any rows whose
send_at is due. Successful sends are logged as lead interactions and the lead
outreach_status is advanced to "contacted" when still in an early state.

Reliability rules:
- A lead that replied (or registered) has its pending rows *cancelled*, so
  nothing more goes out.
- A transient SMTP failure does not kill a row: it is rescheduled
  (+``OUTREACH_RETRY_MINUTES``, default 30) up to ``OUTREACH_MAX_ATTEMPTS``
  times (default 3) before it is marked failed.
- Sends only happen inside the optional UTC window
  ``OUTREACH_WINDOW_START``/``OUTREACH_WINDOW_END`` (hours 0-23; unset =
  always open). Use it to keep cold outreach inside business hours.
- Without SMTP configured, messages go to the dev outbox (never delivered);
  the processor says so loudly on every run.

Usage (from the platform directory):

    .venv/bin/python scripts/process_scheduled_outreach.py

# Cron line (run every 5 minutes):
# */5 * * * * cd /path/to/hydra-shield-platform && .venv/bin/python scripts/process_scheduled_outreach.py
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dashboard import mailer
from src.dashboard.mailer import send_mail
from src.dashboard.marketing_store import MarketingStore

_ADVANCE_FROM = {"researched", "qualified", "draft_prepared"}
_DAILY_SEND_CAP = int(os.environ.get("DAILY_SEND_CAP") or 20)
_MAX_ATTEMPTS = int(os.environ.get("OUTREACH_MAX_ATTEMPTS") or 3)
_RETRY_MINUTES = int(os.environ.get("OUTREACH_RETRY_MINUTES") or 30)

# Contact verification verdicts (Hunter.io) that must never be mailed.
_BAD_VERIFICATIONS = {"invalid", "disposable"}


def _window_open(now: datetime) -> bool:
    """True when the current UTC hour is inside the optional send window."""
    start = os.environ.get("OUTREACH_WINDOW_START")
    end = os.environ.get("OUTREACH_WINDOW_END")
    if not start or not end:
        return True
    try:
        start_h, end_h = int(start), int(end)
    except ValueError:
        return True
    if not (0 <= start_h <= 23 and 0 <= end_h <= 23):
        return True
    hour = now.hour
    if start_h <= end_h:
        return start_h <= hour < end_h
    return hour >= start_h or hour < end_h  # window crossing midnight


def _best_contact(contacts: list) -> dict:
    """Highest-confidence mailable contact: contacts are already ordered by
    confidence; skip addresses whose verification verdict is a hard fail."""
    for contact in contacts:
        if (contact.get("verification") or "").strip().lower() not in _BAD_VERIFICATIONS:
            return contact
    return contacts[0]


def _send_one(store: MarketingStore, lead_slug: str, to_email: str, template: str,
              context: dict, mark_sent, summary_prefix: str = "Scheduled outreach") -> tuple:
    """Send one email, log interaction and advance status. Returns (success, backend)."""
    try:
        result = send_mail(to_email, template, context)
        mark_sent()
        store.add_interaction(
            lead_slug,
            summary=f"{summary_prefix} email sent to {to_email}",
            type="email",
        )
        state = store.get_state(lead_slug)
        current = (state or {}).get("outreach_status") or "researched"
        if current in _ADVANCE_FROM:
            store.update_state(lead_slug, outreach_status="contacted")
        backend = result.get("backend", "unknown")
        return True, backend
    except Exception as exc:
        return False, str(exc)


def _handle_failure(store: MarketingStore, row: dict, detail: str) -> str:
    """Reschedule a due row after a transient failure, or fail it for good
    once the attempt budget is spent. Returns the resulting state string."""
    attempts = (row.get("attempts") or 0) + 1
    if attempts < _MAX_ATTEMPTS:
        retry_at = (datetime.utcnow() + timedelta(minutes=_RETRY_MINUTES)).isoformat()[:19]
        store.reschedule_scheduled(row["id"], retry_at, error=detail)
        return f"retry {attempts}/{_MAX_ATTEMPTS - 1} at {retry_at}: {detail}"
    store.mark_scheduled(row["id"], "failed", error=detail)
    return f"failed after {attempts} attempt(s): {detail}"


def _process_scheduled(store: MarketingStore) -> dict:
    due = store.list_scheduled(due_before=datetime.utcnow().isoformat())
    sent = failed = retried = skipped = cap_hits = 0
    for row in due:
        sid = row["id"]
        lead_slug = row["lead_slug"]

        if store.is_unsubscribed(lead_slug):
            store.mark_scheduled(sid, "skipped_unsubscribed")
            print(f"[scheduled {sid}] {lead_slug} -> skipped_unsubscribed")
            skipped += 1
            continue

        state = store.get_state(lead_slug)
        if state and state.get("outreach_status") == "replied":
            # Cancel for real — a row left "scheduled" would be retried
            # every cron run forever.
            store.cancel_scheduled(sid)
            print(f"[scheduled {sid}] {lead_slug} -> cancelled (replied)")
            skipped += 1
            continue

        if store.sent_today_count() >= _DAILY_SEND_CAP:
            print(f"[scheduled {sid}] {lead_slug} -> daily cap reached, leaving pending")
            cap_hits += 1
            break

        to_email = row["to_email"]
        template = row["template"]
        context = row.get("context") or {}
        success, detail = _send_one(
            store, lead_slug, to_email, template, context,
            mark_sent=lambda: store.mark_scheduled(sid, "sent"),
        )
        if success:
            print(f"[scheduled {sid}] {lead_slug} -> sent ({detail})")
            sent += 1
        else:
            outcome = _handle_failure(store, row, detail)
            if outcome.startswith("retry"):
                print(f"[scheduled {sid}] {lead_slug} -> {outcome}")
                retried += 1
            else:
                print(f"[scheduled {sid}] {lead_slug} -> {outcome}")
                failed += 1

    return {"sent": sent, "failed": failed, "retried": retried,
            "skipped": skipped, "cap_hits": cap_hits, "due": len(due)}


def _process_waves(store: MarketingStore) -> dict:
    due = store.pending_waves(due_before=datetime.utcnow().isoformat())
    sent = failed = skipped = cap_hits = 0
    for row in due:
        wid = row["id"]
        lead_slug = row["lead_slug"]
        campaign = row["campaign"]
        wave = row["wave"]

        if store.is_unsubscribed(lead_slug):
            store.mark_wave(wid, "skipped_unsubscribed")
            print(f"[wave {wid}] {lead_slug} -> skipped_unsubscribed")
            skipped += 1
            continue

        state = store.get_state(lead_slug)
        if state and state.get("outreach_status") == "replied":
            store.mark_wave(wid, "cancelled")
            print(f"[wave {wid}] {lead_slug} -> cancelled (replied)")
            continue

        if store.sent_today_count() >= _DAILY_SEND_CAP:
            print(f"[wave {wid}] {lead_slug} -> daily cap reached, leaving pending")
            cap_hits += 1
            break

        contacts = store.list_contacts(lead_slug)
        if not contacts:
            store.mark_wave(wid, "failed", error="no contacts")
            print(f"[wave {wid}] {lead_slug} -> failed: no contacts")
            failed += 1
            continue

        to_email = _best_contact(contacts)["email"]
        template = row["template"]
        context = row.get("context") or {}
        success, detail = _send_one(
            store, lead_slug, to_email, template, context,
            mark_sent=lambda: store.mark_wave(wid, "sent"),
            summary_prefix=f"Campaign {campaign} wave {wave}",
        )
        if success:
            print(f"[wave {wid}] {lead_slug} -> sent ({detail})")
            sent += 1
        else:
            store.mark_wave(wid, "failed", error=detail)
            print(f"[wave {wid}] {lead_slug} -> failed: {detail}")
            failed += 1

    return {"sent": sent, "failed": failed, "skipped": skipped, "cap_hits": cap_hits, "due": len(due)}


def main() -> int:
    now = datetime.utcnow()
    if not _window_open(now):
        print(f"{now.isoformat()} — outside send window "
              f"(OUTREACH_WINDOW_START/END); nothing processed")
        return 0

    if not mailer.smtp_configured():
        print("WARNING: SMTP is not configured — messages go to the dev "
              "outbox and are NOT delivered. Set SMTP_HOST/… to send for real.")

    store = MarketingStore()
    scheduled = _process_scheduled(store)
    waves = _process_waves(store)

    if scheduled["due"] == 0 and waves["due"] == 0:
        print(f"{now.isoformat()} — no scheduled outreach or campaign waves due")
        return 0

    print(
        f"Processed {scheduled['due']} scheduled row(s): "
        f"{scheduled['sent']} sent, {scheduled['failed']} failed, "
        f"{scheduled['retried']} rescheduled, "
        f"{scheduled['skipped']} skipped, {scheduled['cap_hits']} held by cap"
    )
    print(
        f"Processed {waves['due']} campaign wave row(s): "
        f"{waves['sent']} sent, {waves['failed']} failed, "
        f"{waves['skipped']} skipped, {waves['cap_hits']} held by cap"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
