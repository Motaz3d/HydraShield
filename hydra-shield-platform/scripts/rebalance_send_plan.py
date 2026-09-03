#!/usr/bin/env python3
"""Rebalance pending scheduled_outreach rows to enforce the daily sector mix."""

from __future__ import annotations

import glob
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src.dashboard.marketing_store import MarketingStore  # noqa: E402


def _sector(template: str) -> str:
    if template == "outreach_insurance":
        return "insurance"
    if template == "outreach_banking":
        return "banking"
    if template in ("outreach_investment", "outreach_environmental_consulting"):
        return "investment/consulting"
    return template


def _lead_country(lead_slug: str) -> str:
    path = Path(ROOT) / "marketing" / "leads" / f"{lead_slug}.json"
    if not path.exists():
        return ""
    try:
        lead = json.loads(path.read_text(encoding="utf-8"))
        return lead.get("country") or ""
    except (OSError, ValueError):
        return ""


def main() -> int:
    store = MarketingStore()
    pending = sorted(
        [r for r in store.list_scheduled(status="scheduled")],
        key=lambda r: r["send_at"],
    )

    # Split by day.
    today = [r for r in pending if r["send_at"].startswith("2026-09-03")]
    tomorrow_candidates = [r for r in pending if r["send_at"].startswith("2026-09-04")]
    day_after_candidates = [r for r in pending if r["send_at"].startswith("2026-09-05")]

    # Sort tomorrow candidates by sector, then DE-first for insurance, then current send_at.
    def _insurance_sort_key(r):
        cc = _lead_country(r["lead_slug"]) if r["template"] == "outreach_insurance" else ""
        return (0 if cc == "DE" else 1, r["send_at"])

    ins_candidates = sorted(
        [r for r in tomorrow_candidates if _sector(r["template"]) == "insurance"],
        key=_insurance_sort_key,
    )
    bank_candidates = sorted(
        [r for r in tomorrow_candidates if _sector(r["template"]) == "banking"],
        key=lambda r: r["send_at"],
    )
    inv_candidates = sorted(
        [r for r in tomorrow_candidates if _sector(r["template"]) == "investment/consulting"],
        key=lambda r: r["send_at"],
    )

    # Pick tomorrow's rows.
    tomorrow_ins = ins_candidates[:12]
    tomorrow_bank = bank_candidates[:5]
    tomorrow_inv = inv_candidates[:3]

    # The rest go to day after, grouped by sector with insurance first.
    day_after_ins = sorted(
        ins_candidates[12:] + [r for r in day_after_candidates if _sector(r["template"]) == "insurance"],
        key=lambda r: r["send_at"],
    )
    day_after_bank = sorted(
        bank_candidates[5:] + [r for r in day_after_candidates if _sector(r["template"]) == "banking"],
        key=lambda r: r["send_at"],
    )
    day_after_inv = sorted(
        inv_candidates[3:] + [r for r in day_after_candidates if _sector(r["template"]) == "investment/consulting"],
        key=lambda r: r["send_at"],
    )

    # Reschedule in order.
    def _stagger(rows: List[Dict], day: str, start_hour: int, start_min: int) -> None:
        base = datetime.strptime(f"{day}T{start_hour:02d}:{start_min:02d}:00", "%Y-%m-%dT%H:%M:%S")
        for i, row in enumerate(rows):
            new_send_at = (base + timedelta(minutes=5 * i)).strftime("%Y-%m-%dT%H:%M:%S")
            if row["send_at"] != new_send_at:
                store.reschedule_scheduled(row["id"], new_send_at)

    # Today: leave as is.
    # Tomorrow: insurance 07:05, banking after insurance, investment after banking.
    tomorrow_rows = tomorrow_ins + tomorrow_bank + tomorrow_inv
    _stagger(tomorrow_rows, "2026-09-04", 7, 5)

    # Day after: insurance first, then banking, then investment.
    day_after_rows = day_after_ins + day_after_bank + day_after_inv
    _stagger(day_after_rows, "2026-09-05", 7, 5)

    print(f"Today (unchanged): {len(today)} rows")
    print(f"Tomorrow: {len(tomorrow_rows)} rows = {len(tomorrow_ins)} ins + {len(tomorrow_bank)} bank + {len(tomorrow_inv)} inv")
    print(f"Day after: {len(day_after_rows)} rows = {len(day_after_ins)} ins + {len(day_after_bank)} bank + {len(day_after_inv)} inv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
