#!/usr/bin/env python3
"""Re-stagger existing EU insurance scheduled rows to enforce the send plan.

- Rows 1-12  -> today 2026-09-03 12:04, 12:09, ..., 12:59 UTC
- Rows 13-24 -> 2026-09-04 07:05, 07:10, ..., 08:00 UTC
- Rows 25-31 -> 2026-09-05 07:05, 07:10, ..., 07:35 UTC
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from typing import List

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src.dashboard.marketing_store import MarketingStore  # noqa: E402


def main() -> int:
    store = MarketingStore()
    rows = store.list_scheduled(status="scheduled")
    insurance = sorted(
        [r for r in rows if r.get("template") == "outreach_insurance"],
        key=lambda r: r["send_at"],
    )
    if len(insurance) != 31:
        print(f"WARNING: expected 31 insurance rows, found {len(insurance)}", file=sys.stderr)

    def _dt(day: str, hour: int, minute: int) -> str:
        # normalize overflow minutes into the next hour
        hour += minute // 60
        minute = minute % 60
        return f"{day}T{hour:02d}:{minute:02d}:00"

    updates: List[str] = []
    for i, row in enumerate(insurance):
        idx = i + 1
        if idx <= 12:
            send_at = _dt("2026-09-03", 12, 4 + 5 * i)
        elif idx <= 24:
            j = i - 12
            send_at = _dt("2026-09-04", 7, 5 + 5 * j)
        else:
            j = i - 24
            send_at = _dt("2026-09-05", 7, 5 + 5 * j)
        updated = store.reschedule_scheduled(row["id"], send_at)
        if updated is None:
            print(f"FAILED to reschedule {row['lead_slug']}", file=sys.stderr)
            continue
        updates.append(f"{send_at} | {row['lead_slug']}")

    for u in updates:
        print(u)
    print(f"Re-staggered {len(updates)} insurance rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
