#!/usr/bin/env python3
"""Generate static SEO pages for Knowledge Arm briefs + their sitemap block.

Reads ``config/briefs_registry.json`` and (re)writes:

- ``website/briefs/<id>.html`` for every published brief (stale pages removed)
- the generated BRIEFS block in ``website/sitemap.xml``

Output is a pure function of the registry — run it after editing briefs.
``tests/test_briefs_pages.py`` fails if committed pages drift from the
registry, so CI enforces the re-run.

Usage: ``python scripts/build_brief_pages.py``
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from src.climate.briefs import load_briefs  # noqa: E402
from src.climate import briefs_pages  # noqa: E402

_REPO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
WEBSITE_DIR = os.path.abspath(os.path.join(_REPO, "website"))
BRIEFS_DIR = os.path.join(WEBSITE_DIR, "briefs")
SITEMAP_PATH = os.path.join(WEBSITE_DIR, "sitemap.xml")


def published_briefs():
    registry = load_briefs()
    return [b for b in registry.get("briefs", []) if b.get("status") == "published"]


def main() -> int:
    published = published_briefs()
    expected = {b["id"] for b in published}

    os.makedirs(BRIEFS_DIR, exist_ok=True)
    removed = 0
    for fname in os.listdir(BRIEFS_DIR):
        if fname.endswith(".html") and fname[: -len(".html")] not in expected:
            os.remove(os.path.join(BRIEFS_DIR, fname))
            removed += 1

    for brief in published:
        path = os.path.join(BRIEFS_DIR, f"{brief['id']}.html")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(briefs_pages.render_brief_page(brief))

    with open(SITEMAP_PATH, "r", encoding="utf-8") as fh:
        xml = fh.read()
    updated = briefs_pages.update_sitemap(xml, published)
    if updated != xml:
        with open(SITEMAP_PATH, "w", encoding="utf-8") as fh:
            fh.write(updated)

    print(f"briefs: {len(published)} page(s) written, {removed} stale removed, sitemap updated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
