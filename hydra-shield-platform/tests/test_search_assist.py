"""Search assist: the unified on-focus dropdown model for search boxes.

Locks the contract: every covered page loads js/search-assist.js, the
component renders the three sections (searching-from / tips / live), the
Ctrl+K palette opens with the same context strip, and the styles exist.
"""

import os

ROOT = os.path.dirname(__file__)

PAGES = (
    "map.html", "intelligence.html", "economy.html", "events.html",
    "solutions.html", "report-builder.html", "academy.html", "industries.html",
)


def _read(rel):
    with open(os.path.join(ROOT, "..", rel), encoding="utf-8") as fh:
        return fh.read()


def test_component_has_three_sections_and_location_contract():
    js = _read("website/js/search-assist.js")
    assert "Searching from" in js
    assert "Tips" in js
    assert "Live now" in js
    assert "HS.lastLocation" in js or "lastLocation()" in js
    # Live context uses the real risk snapshot with an honest fallback.
    assert "/risk-snapshot" in js
    assert "temporarily unavailable" in js


def test_component_covers_the_search_pages():
    js = _read("website/js/search-assist.js")
    for page in ("map", "intelligence", "economy", "events",
                 "solutions", "report-builder", "academy", "industries"):
        assert f"{page}:" in js or f"'{page}'" in js, page


def test_pages_load_the_component():
    for page in PAGES:
        html = _read(f"website/{page}")
        assert "js/search-assist.js" in html, page


def test_palette_opens_with_context_strip():
    js = _read("website/js/search.js")
    assert "Searching from:" in js
    assert "contextHtml" in js


def test_styles_exist():
    css = _read("website/css/style.css")
    assert ".sa-dropdown" in css
    assert ".search-context" in css
