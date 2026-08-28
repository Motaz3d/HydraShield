#!/usr/bin/env python3
"""Bulk contact discovery over the marketing leads workspace.

Runs the Talaix email-discovery engine (src/dashboard/email_discovery.py)
over leads that have an official website but no stored contacts yet, and
stores what it finds — every contact carries its source page and claim
status (OBSERVED / INFERRED; inferred addresses are labelled, never
presented as verified).

Honesty contract: no address is invented, robots.txt is honored by the
engine, free-mail and junk localparts are filtered, and leads without a
usable domain are skipped with a count — never padded.

When AUTO_OUTREACH_ON_CONTACT=1, genuinely new contacts are auto-queued for
a scheduled outreach email (same rule as scripts/import_contacts.py).

Usage:
    .venv/bin/python scripts/discover_contacts.py [options]

Options:
    --segment SEGMENT   only leads of this segment (e.g. consultants)
    --country CC        only leads of this country (ISO alpha-2)
    --max N             max domains to crawl this run (default: 50)
    --sleep SECONDS     pause between domains (default: 2.0)
    --refresh           also re-crawl leads that already have contacts
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dashboard.email_discovery import discover_emails  # noqa: E402
from src.dashboard.marketing_store import MarketingStore  # noqa: E402

LEADS_DIR = ROOT / "marketing" / "leads"


def _iter_leads(segment: Optional[str], country: Optional[str]) -> List[Dict]:
    leads = []
    for path in sorted(glob.glob(str(LEADS_DIR / "*.json"))):
        if path.endswith("schema.json"):
            continue
        try:
            lead = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if segment and (lead.get("segment") or "") != segment:
            continue
        if country and (lead.get("country") or "").upper() != country.upper():
            continue
        lead["_slug"] = Path(path).stem
        leads.append(lead)
    return leads


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--segment", default=None)
    parser.add_argument("--country", default=None)
    parser.add_argument("--max", type=int, default=50)
    parser.add_argument("--sleep", type=float, default=2.0)
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args(argv)

    store = MarketingStore()
    leads = _iter_leads(args.segment, args.country)
    stats = {"crawled": 0, "with_contacts": 0, "contacts": 0,
             "no_domain": 0, "empty": 0, "skipped_existing": 0}

    for lead in leads:
        if stats["crawled"] >= args.max:
            break
        slug = lead["_slug"]
        website = (lead.get("website") or "").strip()
        if not website:
            stats["no_domain"] += 1
            continue
        if not args.refresh and store.list_contacts(slug):
            stats["skipped_existing"] += 1
            continue

        result = discover_emails(website)
        stats["crawled"] += 1
        contacts = result.get("contacts") or []
        if not contacts:
            stats["empty"] += 1
        else:
            stats["with_contacts"] += 1

        added = 0
        new_contacts = []
        for c in contacts:
            confidence = c.get("confidence")
            try:
                confidence = int(round(float(confidence) * 100)) if confidence is not None else None
            except (TypeError, ValueError):
                confidence = None
            n = store.add_contacts(
                slug,
                [{
                    "email": c.get("email"),
                    "verification": (c.get("claim_status") or "").strip() or None,
                    "confidence": confidence,
                }],
                source="talaix-discovery",
            )
            if n:
                added += n
                new_contacts.append({"email": c.get("email"), "name": None})
        stats["contacts"] += added

        if new_contacts:
            from src.dashboard.marketing_automation import queue_outreach_for_new_contacts

            queue_outreach_for_new_contacts(store, slug, new_contacts)

        print(f"[{stats['crawled']:>4}/{args.max}] {slug}: "
              f"{len(contacts)} found, {added} new")
        time.sleep(args.sleep)

    print(
        f"Done: crawled {stats['crawled']} domains ({stats['with_contacts']} with contacts), "
        f"{stats['contacts']} new contacts stored; "
        f"skipped: {stats['skipped_existing']} already-had, "
        f"{stats['no_domain']} no-domain, {stats['empty']} empty"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
