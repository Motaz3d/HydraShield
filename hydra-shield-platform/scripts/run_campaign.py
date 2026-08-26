#!/usr/bin/env python3
"""Enqueue a campaign wave for matching leads.

Usage:
    python scripts/run_campaign.py --campaign q4-2026 --wave 2 --template followup_1
    python scripts/run_campaign.py --campaign q4-2026 --wave 2 --template followup_1 \
        --filter segment=banking --filter country=US --delay-days 1

Enqueued rows are pending until scripts/process_scheduled_outreach.py sends
them. The daily send cap provides natural pacing.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Dict

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dashboard.campaigns import ALLOWED_TEMPLATES, start_campaign  # noqa: E402


def _parse_filter(text: str) -> tuple:
    if "=" not in text:
        raise argparse.ArgumentTypeError(f"filter must be key=value: {text}")
    key, value = text.split("=", 1)
    return key.strip(), value.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="Enqueue a campaign wave")
    parser.add_argument("--campaign", required=True, help="Campaign name")
    parser.add_argument("--wave", required=True, type=int, help="Wave number (1/2/3)")
    parser.add_argument(
        "--template",
        required=True,
        choices=sorted(ALLOWED_TEMPLATES),
        help="Follow-up template",
    )
    parser.add_argument(
        "--filter",
        action="append",
        default=[],
        type=_parse_filter,
        help="Filter as key=value (segment, country); repeatable",
    )
    parser.add_argument(
        "--delay-days",
        type=float,
        default=0.0,
        help="Delay the first send by this many days (default 0)",
    )
    args = parser.parse_args()

    if args.wave < 1:
        print("wave must be >= 1")
        return 1

    filters: Dict[str, str] = {}
    for key, value in args.filter:
        if key not in ("segment", "country"):
            print(f"Unknown filter key: {key}")
            return 1
        filters[key] = value

    result = start_campaign(
        campaign=args.campaign,
        wave=args.wave,
        template=args.template,
        filters=filters,
        delay_days=args.delay_days,
    )
    print(
        f"Campaign {result['campaign']} wave {result['wave']}: "
        f"enqueued {result['enqueued']}, skipped {result['skipped']}"
    )
    if result["leads"]:
        print("Leads:", ", ".join(result["leads"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
