#!/usr/bin/env python3
"""Talaix scheduled outreach processor.

Polls the marketing_store scheduled_outreach table and sends any rows whose
send_at is due. Successful sends are logged as lead interactions and the lead
outreach_status is advanced to "contacted" when still in an early state.

Usage (from the platform directory):

    .venv/bin/python scripts/process_scheduled_outreach.py

# Cron line (run every 5 minutes):
# */5 * * * * cd /path/to/hydra-shield-platform && .venv/bin/python scripts/process_scheduled_outreach.py
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dashboard.mailer import send_mail
from src.dashboard.marketing_store import MarketingStore

_ADVANCE_FROM = {"researched", "qualified", "draft_prepared"}
_DAILY_SEND_CAP = int(os.environ.get("DAILY_SEND_CAP") or 20)


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


def _process_scheduled(store: MarketingStore) -> dict:
    due = store.list_scheduled(due_before=datetime.utcnow().isoformat())
    sent = failed = skipped = cap_hits = 0
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
            store.mark_scheduled(sid, "cancelled")
            print(f"[scheduled {sid}] {lead_slug} -> cancelled (replied)")
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
            store.mark_scheduled(sid, "failed", error=detail)
            print(f"[scheduled {sid}] {lead_slug} -> failed: {detail}")
            failed += 1

    return {"sent": sent, "failed": failed, "skipped": skipped, "cap_hits": cap_hits, "due": len(due)}


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

        to_email = contacts[0]["email"]
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
    store = MarketingStore()
    scheduled = _process_scheduled(store)
    waves = _process_waves(store)

    if scheduled["due"] == 0 and waves["due"] == 0:
        print(f"{datetime.utcnow().isoformat()} — no scheduled outreach or campaign waves due")
        return 0

    print(
        f"Processed {scheduled['due']} scheduled row(s): "
        f"{scheduled['sent']} sent, {scheduled['failed']} failed, "
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
