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
_DAILY_SEND_CAP = int(os.environ.get("DAILY_SEND_CAP") or 200)


def main() -> int:
    store = MarketingStore()
    due = store.list_scheduled(due_before=datetime.utcnow().isoformat())
    if not due:
        print(f"{datetime.utcnow().isoformat()} — no scheduled outreach due")
        return 0

    sent = failed = skipped = cap_hits = 0
    for row in due:
        sid = row["id"]
        lead_slug = row["lead_slug"]

        if store.is_unsubscribed(lead_slug):
            store.mark_scheduled(sid, "skipped_unsubscribed")
            print(f"[{sid}] {lead_slug} -> skipped_unsubscribed")
            skipped += 1
            continue

        if store.sent_today_count() >= _DAILY_SEND_CAP:
            print(f"[{sid}] {lead_slug} -> daily cap reached, leaving pending")
            cap_hits += 1
            break

        to_email = row["to_email"]
        template = row["template"]
        context = row.get("context") or {}
        try:
            result = send_mail(to_email, template, context)
            store.mark_scheduled(sid, "sent")
            store.add_interaction(
                lead_slug,
                summary=f"Scheduled outreach email sent to {to_email}",
                type="email",
            )
            state = store.get_state(lead_slug)
            current = (state or {}).get("outreach_status") or "researched"
            if current in _ADVANCE_FROM:
                store.update_state(lead_slug, outreach_status="contacted")
            backend = result.get("backend", "unknown")
            print(f"[{sid}] {lead_slug} -> sent ({backend})")
            sent += 1
        except Exception as exc:
            store.mark_scheduled(sid, "failed", error=str(exc))
            print(f"[{sid}] {lead_slug} -> failed: {exc}")
            failed += 1

    print(
        f"Processed {len(due)} scheduled outreach row(s): "
        f"{sent} sent, {failed} failed, {skipped} skipped, {cap_hits} held by cap"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
