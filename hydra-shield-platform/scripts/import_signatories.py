#!/usr/bin/env python3
"""Import official climate-finance signatory lists into the Marketing CRM.

Only live sources are fetched. Pending sources are listed in the source
registry with their stated reason and are never scraped.

Usage:
    python scripts/import_signatories.py
    python scripts/import_signatories.py --source pcaf
    python scripts/import_signatories.py --dry-run
    python scripts/import_signatories.py --dir /path/to/marketing/leads
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dashboard.signatories import (  # noqa: E402
    SOURCES,
    SignatorySourceError,
    build_lead,
    category_to_segment,
    merge_signatory,
    normalise_org,
    resolve_websites,
)

LEADS_DIR = ROOT / "marketing" / "leads"
IMPORTS_DIR = ROOT / "marketing" / "imports"
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,120}$")
_BAD_WEBSITE = "https://carbonaccountingfinancials.com"


def _slugify(text: str) -> str:
    slug = text.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    if not _SLUG_RE.match(slug):
        slug = re.sub(r"[^a-z0-9.-]+", "-", slug).strip("-") or "unknown"
    return slug[:120]


def _load_lead(path: Path) -> Optional[Dict]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None


def _build_lead_index(leads_dir: Path) -> Tuple[Dict[str, Path], Dict[str, Path]]:
    """Return (normalised_name -> path, slug -> path) for existing leads."""
    by_norm: Dict[str, Path] = {}
    by_slug: Dict[str, Path] = {}
    if not leads_dir.exists():
        return by_norm, by_slug
    for path in leads_dir.glob("*.json"):
        if path.name == "schema.json":
            continue
        lead = _load_lead(path)
        if not lead:
            continue
        by_slug[path.stem] = path
        org = lead.get("organization", "")
        if org:
            norm = normalise_org(org)
            if norm:
                by_norm[norm] = path
    return by_norm, by_slug


def _write_lead(path: Path, lead: Dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(lead, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


def _is_signatory_import_bad_lead(lead: Dict) -> bool:
    """Detect leads created by the earlier bug: PCAF domain used as organisation website."""
    if lead.get("website") != _BAD_WEBSITE:
        return False
    interactions = lead.get("interactions", [])
    if not interactions:
        return False
    summary = interactions[0].get("summary", "")
    return "signatory-list import" in summary


def _purge_bad_leads(leads_dir: Path, dry_run: bool = False) -> int:
    """Delete leads whose website was wrongly set to the PCAF domain."""
    removed = 0
    if not leads_dir.exists():
        return 0
    for path in leads_dir.glob("*.json"):
        if path.name == "schema.json":
            continue
        lead = _load_lead(path)
        if lead and _is_signatory_import_bad_lead(lead):
            if not dry_run:
                path.unlink()
            removed += 1
    return removed


def _summary(
    source_id: str,
    parsed: int,
    resolved: int,
    self_disclosed: int,
    wikidata: int,
    pending: int,
    created: int,
    merged: int,
    skipped: int,
    segment_counts: Dict[str, int],
) -> str:
    parts = [
        f"{source_id}: parsed {parsed}",
        f"resolved {resolved} (self={self_disclosed}, wikidata={wikidata})",
        f"pending {pending}",
        f"created {created}",
        f"merged {merged}",
        f"skipped {skipped}",
    ]
    if segment_counts:
        seg_part = ", ".join(f"{k}={v}" for k, v in sorted(segment_counts.items()))
        parts.append(f"segments ({seg_part})")
    return " · ".join(parts)


def _write_pending_file(source_id: str, pending_rows: List[Dict], dry_run: bool = False) -> None:
    """Overwrite the staging snapshot of unresolved signatory rows."""
    if dry_run:
        return
    IMPORTS_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "batch": f"{source_id}-{date.today().isoformat()}",
        "source": source_id,
        "imported_at": datetime.now().astimezone().isoformat(),
        "rows": pending_rows,
    }
    path = IMPORTS_DIR / "signatory_pending.json"
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


def import_source(
    source: Dict[str, object],
    leads_dir: Path,
    *,
    dry_run: bool = False,
    fetch: Optional[Callable[[str, float], Any]] = None,
    sleep_s: float = 0.3,
) -> Tuple[List[Dict], List[Dict], int, int, int, Dict[str, int]]:
    """
    Import one live source.

    Returns ``(parsed_rows, resolved_rows, created, merged, skipped, segment_counts)``.
    Raises SignatorySourceError on failure so the caller can abort this source cleanly.
    """
    adapter = source.get("adapter")
    if not callable(adapter):
        raise SignatorySourceError(f"{source['id']} has no callable adapter")

    parsed_rows = adapter()
    resolved_rows, pending_rows = resolve_websites(parsed_rows, fetch=fetch, sleep_s=sleep_s)

    by_norm, by_slug = _build_lead_index(leads_dir)

    created = 0
    merged = 0
    skipped = 0
    segment_counts: Dict[str, int] = {}

    for row in resolved_rows:
        org = row.get("organization", "").strip()
        norm = normalise_org(org)
        if not norm:
            skipped += 1
            continue

        website = row.get("website")
        if not website:
            skipped += 1
            continue

        fields = {
            "status": row.get("status", ""),
            "assets_usd_m": row.get("assets_usd_m"),
            "date_joined": row.get("date_joined", ""),
            "first_disclosure": row.get("first_disclosure", ""),
            "most_recent_disclosure": row.get("most_recent_disclosure", ""),
            "disclosure_url": row.get("disclosure_url"),
            "category": row.get("category", ""),
            "source_url": row.get("source_url", ""),
        }
        segment = category_to_segment(row.get("category", ""))
        segment_counts[segment] = segment_counts.get(segment, 0) + 1

        existing_path = by_norm.get(norm)
        if existing_path:
            if dry_run:
                merged += 1
                continue
            lead = _load_lead(existing_path) or {}
            merge_signatory(lead, source["id"], fields)
            _write_lead(existing_path, lead)
            merged += 1
            by_norm[normalise_org(lead.get("organization", ""))] = existing_path
            continue

        slug = _slugify(org)
        if by_slug.get(slug):
            base_slug = slug
            counter = 2
            while by_slug.get(slug):
                slug = f"{base_slug}-{counter}"
                counter += 1

        if dry_run:
            created += 1
            by_slug[slug] = Path("/dev/null")
            continue

        lead = build_lead(row, source["id"])
        path = leads_dir / f"{slug}.json"
        _write_lead(path, lead)
        by_slug[slug] = path
        by_norm[normalise_org(lead["organization"])] = path
        created += 1

    _write_pending_file(source["id"], pending_rows, dry_run=dry_run)

    return parsed_rows, resolved_rows, created, merged, skipped, segment_counts


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Import official climate-finance signatory lists into marketing/leads"
    )
    parser.add_argument("--source", default=None, help="Import only this source id (default: all live sources)")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be written without writing")
    parser.add_argument("--dir", default=str(LEADS_DIR), help="Path to the marketing/leads directory")
    parser.add_argument(
        "--purge-bad",
        action="store_true",
        dest="purge_bad",
        help="Delete leads created with the buggy PCAF-domain website before re-importing",
    )
    args = parser.parse_args(argv)

    leads_dir = Path(args.dir)
    sources = [s for s in SOURCES if s.get("live")]
    if args.source:
        sources = [s for s in sources if s["id"] == args.source]
        if not sources:
            print(f"Unknown or non-live source: {args.source}")
            print("Live sources: " + ", ".join(s["id"] for s in SOURCES if s.get("live")))
            return 2

    if not sources:
        print("No live signatory sources configured.")
        return 0

    if args.purge_bad:
        removed = _purge_bad_leads(leads_dir, dry_run=args.dry_run)
        action = "would remove" if args.dry_run else "removed"
        print(f"[{action}] {removed} leads with buggy PCAF-domain website")

    any_failed = False
    for source in sources:
        try:
            parsed_rows, resolved_rows, created, merged, skipped, segment_counts = import_source(
                source, leads_dir, dry_run=args.dry_run
            )
        except SignatorySourceError as exc:
            print(f"[ABORTED] {exc}")
            any_failed = True
            continue
        self_disclosed = sum(1 for r in resolved_rows if r.get("website_source") == "self-disclosure")
        wikidata_resolved = sum(1 for r in resolved_rows if r.get("website_source") == "wikidata")
        print(
            _summary(
                source["id"],
                len(parsed_rows),
                len(resolved_rows),
                self_disclosed,
                wikidata_resolved,
                len(parsed_rows) - len(resolved_rows),
                created,
                merged,
                skipped,
                segment_counts,
            )
        )

    if args.dry_run:
        print("Dry run — no files written.")
    if any_failed:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
