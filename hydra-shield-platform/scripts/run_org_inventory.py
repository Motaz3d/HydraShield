#!/usr/bin/env python3
"""Run the Wikidata-based organization inventory and feed marketing/leads.

Honesty contract:
    - Websites come ONLY from Wikidata P856.
    - Rows without a website go to marketing/imports/inventory_pending.json
      and are never written as leads.
    - Existing leads are merged by normalised organisation name, never
      overwritten.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dashboard.org_inventory import (
    COUNTRIES,
    TARGETS,
    TODAY,
    run_inventory,
    to_lead,
)
from src.dashboard.signatories import normalise_org

LEADS_DIR = ROOT / "marketing" / "leads"
IMPORTS_DIR = ROOT / "marketing" / "imports"
REPORTS_DIR = ROOT / "marketing" / "reports"

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,120}$")


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


def _write_lead(path: Path, lead: Dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(lead, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


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


def _merge_inventory(
    lead_json: Dict[str, Any],
    row: Dict[str, Any],
) -> Dict[str, Any]:
    """Merge an inventory hit into an existing lead."""
    source_url = row.get("source_url", "")
    wikidata_id = row.get("wikidata_id", "")
    concepts = row.get("concepts", [])

    inventory_of: List[str] = lead_json.setdefault("inventory_of", [])
    if source_url and source_url not in inventory_of:
        inventory_of.append(source_url)

    lead_concepts: List[str] = lead_json.setdefault("concepts", [])
    for concept in concepts:
        if concept not in lead_concepts:
            lead_concepts.append(concept)

    if wikidata_id and not lead_json.get("wikidata_id"):
        lead_json["wikidata_id"] = wikidata_id

    meta = lead_json.setdefault("inventory_meta", {})
    meta.setdefault("concept_label", concepts[0] if concepts else "")
    meta.setdefault("wikidata_id", wikidata_id)
    meta.setdefault("source_url", source_url)

    interactions = lead_json.setdefault("interactions", [])
    already_logged = any(
        "Wikidata organization inventory" in (ix.get("summary") or "")
        for ix in interactions
    )
    if not already_logged:
        interactions.append(
            {
                "date": TODAY,
                "type": "discovered",
                "summary": (
                    "Updated via Wikidata organization inventory "
                    f"({', '.join(concepts)})."
                ),
                "source": source_url,
            }
        )

    return lead_json


def _write_pending_file(rows: List[Dict[str, Any]], dry_run: bool = False) -> None:
    if dry_run:
        return
    IMPORTS_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "batch": f"inventory-{datetime.now().astimezone().isoformat()}",
        "source": "wikidata_org_inventory",
        "imported_at": datetime.now().astimezone().isoformat(),
        "rows": rows,
    }
    path = IMPORTS_DIR / "inventory_pending.json"
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


def _write_report(report: Dict[str, Any], dry_run: bool = False) -> None:
    if dry_run:
        return
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORTS_DIR / "inventory_latest.json"
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


def _print_summary(report: Dict[str, Any]) -> None:
    print("Organization inventory sweep complete")
    print("-" * 70)
    per_concept = report.get("per_concept", {})
    if per_concept:
        print(f"{'Concept':<35} {'Queries':>8} {'Hits':>8} {'Unique':>8} {'With site':>10}")
        for label, counts in sorted(per_concept.items()):
            print(
                f"{label:<35} {counts['queries']:>8} {counts['hits']:>8} "
                f"{counts['unique']:>8} {counts['with_website']:>10}"
            )
    print("-" * 70)
    totals = report.get("totals", {})
    print(
        f"Totals: queries={totals.get('queries', 0)}, hits={totals.get('hits', 0)}, "
        f"unique={totals.get('unique_orgs', 0)}, with_website={totals.get('with_website', 0)}, "
        f"without_website={totals.get('without_website', 0)}"
    )
    skipped = report.get("skipped", [])
    if skipped:
        print(f"Skipped: {len(skipped)} (unresolvable concepts/countries)")
    capped = report.get("capped_queries", [])
    if capped:
        print(f"Capped queries: {len(capped)} (hit LIMIT)")
    if report.get("created") is not None:
        print(f"Leads created: {report['created']}, merged: {report['merged']}, pending: {report['pending']}")


def _concept_countries_for_target(target: Dict[str, Any]) -> Set[str]:
    apply_to = target.get("apply_to", "ALL")
    if apply_to == "ALL":
        return set(COUNTRIES.keys())
    return set(apply_to)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the Wikidata organization inventory and feed marketing/leads"
    )
    parser.add_argument(
        "--countries",
        default="ALL",
        help="Comma-separated ISO country codes (default: ALL)",
    )
    parser.add_argument(
        "--concepts",
        default="ALL",
        help="Comma-separated concept labels (default: ALL)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=200,
        help="Max rows per SPARQL query (default: 200)",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=1.0,
        help="Seconds to sleep between SPARQL calls (default: 1.0)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be written without writing",
    )
    parser.add_argument(
        "--dir",
        default=str(LEADS_DIR),
        help="Path to the marketing/leads directory",
    )
    args = parser.parse_args(argv)

    leads_dir = Path(args.dir)

    countries = None if args.countries == "ALL" else [c.strip() for c in args.countries.split(",") if c.strip()]
    concepts = None if args.concepts == "ALL" else [c.strip() for c in args.concepts.split(",") if c.strip()]

    print("Resolving Wikidata concepts and countries…")
    result = run_inventory(
        countries=countries,
        concepts=concepts,
        limit_per_query=args.limit,
        sleep_s=args.sleep,
    )

    rows = result["rows"]
    counts = result["counts"]
    skipped = result["skipped"]
    capped_queries = result["capped_queries"]

    # Per-concept counts (post-dedupe by concept membership).
    per_concept: Dict[str, Dict[str, int]] = {}
    for target in TARGETS:
        label = target["concept_label"]
        if concepts and label not in concepts:
            continue
        concept_rows = [r for r in rows if label in r.get("concepts", [])]
        per_concept[label] = {
            "queries": len(_concept_countries_for_target(target) & (set(countries) if countries else set(COUNTRIES.keys()))),
            "hits": len(concept_rows),  # approximate; real hits may include cross-concept dupes
            "unique": len(concept_rows),
            "with_website": sum(1 for r in concept_rows if r.get("website")),
        }

    by_norm, by_slug = _build_lead_index(leads_dir)

    created = 0
    merged = 0
    pending_rows: List[Dict[str, Any]] = []

    for row in rows:
        if not row.get("website"):
            pending_rows.append(
                {
                    "organization": row["organization"],
                    "country_code": row["country_code"],
                    "segment": row["segment"],
                    "concepts": row.get("concepts", []),
                    "wikidata_id": row.get("wikidata_id"),
                    "source_url": row.get("source_url"),
                    "pending_reason": "no official website found (Wikidata P856 missing)",
                }
            )
            continue

        norm = normalise_org(row["organization"])
        existing_path = by_norm.get(norm) if norm else None

        if existing_path:
            if not args.dry_run:
                lead = _load_lead(existing_path) or {}
                _merge_inventory(lead, row)
                _write_lead(existing_path, lead)
                by_norm[normalise_org(lead.get("organization", ""))] = existing_path
            merged += 1
            continue

        slug = _slugify(row["organization"])
        if by_slug.get(slug):
            base_slug = slug
            counter = 2
            while by_slug.get(slug):
                slug = f"{base_slug}-{counter}"
                counter += 1

        if not args.dry_run:
            lead = to_lead(row)
            path = leads_dir / f"{slug}.json"
            _write_lead(path, lead)
            by_slug[slug] = path
            by_norm[normalise_org(lead["organization"])] = path
        created += 1

    _write_pending_file(pending_rows, dry_run=args.dry_run)

    report = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "parameters": {
            "countries": countries if countries else "ALL",
            "concepts": concepts if concepts else "ALL",
            "limit_per_query": args.limit,
        },
        "totals": counts,
        "per_concept": per_concept,
        "skipped": skipped,
        "capped_queries": capped_queries,
        "created": created,
        "merged": merged,
        "pending": len(pending_rows),
    }
    _write_report(report, dry_run=args.dry_run)

    _print_summary(report)

    if args.dry_run:
        print("Dry run — no files written.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
