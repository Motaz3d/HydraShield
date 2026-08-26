#!/usr/bin/env python3
"""Import external-research contacts into the Marketing CRM.

Reads JSON seed files from marketing/imports/*.json (ordered by filename),
creates missing lead files in marketing/leads/, and stores contacts via
MarketingStore.add_contacts. Re-running is idempotent: contacts are
 deduplicated by (lead_slug, email).

Usage:
    python scripts/import_contacts.py
    python scripts/import_contacts.py --dir marketing/imports
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dashboard.marketing_store import MarketingStore  # noqa: E402

LEADS_DIR = ROOT / "marketing" / "leads"
IMPORTS_DIR = ROOT / "marketing" / "imports"

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,120}$")


def _slugify(text: str) -> str:
    """Normalize an organization name to a lead slug."""
    slug = text.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    if not _SLUG_RE.match(slug):
        slug = re.sub(r"[^a-z0-9.-]+", "-", slug).strip("-") or "unknown"
    return slug[:120]


def _confidence(email_type: str) -> Optional[int]:
    return {"personal": 85, "department": 70, "general": 50}.get(email_type)


def _find_lead_file(slug: str, organization: str) -> Optional[Path]:
    """Return the matching lead file path, or None if not found."""
    # Exact slug match.
    exact = LEADS_DIR / f"{slug}.json"
    if exact.exists():
        return exact
    # Case-insensitive organization match.
    org_lower = organization.lower()
    for path in LEADS_DIR.glob("*.json"):
        if path.name == "schema.json":
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if (data.get("organization") or "").lower() == org_lower:
            return path
    return None


def _create_lead(contact: Dict[str, str]) -> str:
    """Create a minimal lead file and return its slug."""
    LEADS_DIR.mkdir(parents=True, exist_ok=True)
    organization = contact["organization"]
    slug = _slugify(organization)
    lead = {
        "organization": organization,
        "segment": contact.get("segment", "unknown"),
        "country": contact.get("country", ""),
        "website": contact.get("website", ""),
        "priority": contact.get("priority", "medium"),
        "urgency": "medium",
        "outreach_status": "researched",
        "recommended_product": contact.get("recommended_product", ""),
        "next_action": "Qualify: verify current public signal and select contact route",
        "identified_problem": contact.get("identified_problem", ""),
        "relevant_capability": contact.get("relevant_capability", ""),
        "status": "open",
        "interactions": [
            {
                "date": contact.get("imported_at", ""),
                "type": "discovered",
                "summary": f"Imported via {contact.get('batch', 'external-research')} batch.",
                "source": contact.get("source_url", ""),
            }
        ],
        "source": contact.get("source_url", ""),
        "date_checked": contact.get("imported_at", ""),
    }
    path = LEADS_DIR / f"{slug}.json"
    path.write_text(json.dumps(lead, indent=2, ensure_ascii=False), encoding="utf-8")
    return slug


def _load_seed(path: Path) -> Dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def import_batch(store: MarketingStore, seed: Dict) -> Dict:
    """Import one seed file. Returns counts."""
    batch = seed.get("batch") or "unnamed"
    imported_at = seed.get("imported_at", "")
    counts = {"created": 0, "contacts_added": 0, "skipped": 0}

    for contact in seed.get("contacts", []):
        organization = (contact.get("organization") or "").strip()
        email = (contact.get("email") or "").strip().lower()
        if not organization or not email:
            counts["skipped"] += 1
            continue

        slug = _slugify(organization)
        existing = _find_lead_file(slug, organization)
        if existing is None:
            slug = _create_lead({**contact, "batch": batch, "imported_at": imported_at})
            counts["created"] += 1
        else:
            slug = existing.stem

        confidence = _confidence(contact.get("email_type", ""))
        added = store.add_contacts(
            slug,
            [{
                "email": email,
                "name": (contact.get("person") or "").strip() or None,
                "position": (contact.get("role") or "").strip() or None,
                "confidence": confidence,
                "verification": (contact.get("verification") or "").strip() or None,
            }],
            source="external-research",
        )
        if added:
            counts["contacts_added"] += added
        else:
            counts["skipped"] += 1

    return counts


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Import contacts from marketing/imports/*.json")
    parser.add_argument("--dir", default=str(IMPORTS_DIR), help="Directory containing seed JSON files")
    args = parser.parse_args(argv)

    imports_dir = Path(args.dir)
    if not imports_dir.exists():
        print(f"Import directory does not exist: {imports_dir}")
        return 1

    store = MarketingStore()
    total = {"created": 0, "contacts_added": 0, "skipped": 0}

    for path in sorted(imports_dir.glob("*.json")):
        try:
            seed = _load_seed(path)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"[skip] {path.name}: {exc}")
            continue
        counts = import_batch(store, seed)
        print(
            f"{path.name}: created {counts['created']} leads, "
            f"added {counts['contacts_added']} contacts, skipped {counts['skipped']}"
        )
        for k in total:
            total[k] += counts[k]

    print(
        f"Total: created {total['created']} leads, "
        f"added {total['contacts_added']} contacts, skipped {total['skipped']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
