"""Search assist: the unified on-focus dropdown model for search boxes.

Locks the contract: every covered page loads js/search-assist.js, the
component renders its sections (context / quick picks / searching-from /
tips / live), CONFIG keys match real data-page attributes, the Ctrl+K
palette opens with the same context strip, and the styles exist.
"""

import glob
import os
import re

ROOT = os.path.dirname(__file__)

PAGES = (
    "map.html", "intelligence.html",
    "academy.html", "industries.html",
    "index.html", "green-finance.html", "insurance.html", "forensics.html",
    "supplychain.html", "press.html", "reports.html", "licensing.html",
    "story.html",
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
    for page in ("map", "intelligence",
                 "academy", "industries", "home", "greenfinance",
                 "insurance", "forensics", "supplychain", "press",
                 "reports", "licensing", "about"):
        assert f"{page}:" in js or f"'{page}'" in js, page
    # The merged events/economy/siting panels keep their assist inside intelligence.
    assert "eventsLocInput" in js
    assert "locInput" in js
    assert "solLocInput" in js
    # Portal location inputs are covered too.
    assert "assetLocInput" in js
    assert "caseSiteInput" in js
    assert "pressLocInput" in js
    assert "legacyLocInput" in js
    assert "licSiteInput" in js


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


def test_component_has_quick_picks_and_context():
    js = _read("website/js/search-assist.js")
    assert "Quick picks" in js
    assert "sa-chip" in js
    assert "chipsHtml" in js
    assert "contextHtml" in js
    assert "activeHazard" in js
    # Tips stay compact — capped, never a wall of bullets.
    assert "MAX_TIPS" in js
    # Inputs without an id (e.g. the home hero) match by name.
    assert "getAttribute('name')" in js


def test_quick_pick_styles_exist():
    css = _read("website/css/style.css")
    assert ".sa-chips" in css
    assert ".sa-chip" in css
    assert ".sa-context" in css


def test_config_keys_match_real_data_pages():
    """Every CONFIG page key must correspond to a real data-page attribute —
    a mismatch silently disables the dropdown on that page."""
    js = _read("website/js/search-assist.js")
    block = js.split("var CONFIG = {", 1)[1].split("\n    };", 1)[0]
    keys = set(re.findall(r"^ {8}([A-Za-z_][A-Za-z0-9_]*): \{", block, re.M))
    assert keys, "no CONFIG page keys found"

    data_pages = set()
    for path in glob.glob(os.path.join(ROOT, "..", "website", "*.html")):
        with open(path, encoding="utf-8") as fh:
            data_pages.update(re.findall(r'data-page="([^"]+)"', fh.read()))

    missing = keys - data_pages
    assert not missing, f"CONFIG keys without a matching data-page: {missing}"


def test_every_field_gets_a_helper_dropdown():
    """Every text/number/textarea field on the covered pages gets a dropdown:
    targeted configs for the previously-uncovered fields, plus a generic
    fallback so no search box is ever left empty."""
    js = _read("website/js/search-assist.js")
    assert "EXTRA_CONFIG" in js
    assert "defaultConfig" in js
    assert "isLocationField" in js
    for key in ("radiusInput", "companySector", "assetsText", "draftTitle",
                "advCompareInput", "caseClaimText", "verifyCertId",
                "eventsRadius", "economyRadius"):
        assert key in js, key


def test_dropdown_reopens_on_every_focus_or_click():
    """Operator bug report 2026-09-15: the helper appeared only once. A click
    on an already-focused field fires no focusin, so the dropdown must also
    open on a mouse click — and skip a redundant rebuild when it is already
    open for that field (no flicker / re-fetch)."""
    js = _read("website/js/search-assist.js")
    # Focus and click both route through the same opener.
    assert "openInput(input)" in js
    # The click handler opens (not just closes) when the target is a field.
    assert "if (input) { openInput(input); return; }" in js
    # Guard against rebuilding an already-open dropdown for the same input.
    assert "dd && dd.classList.contains(OPEN_CLASS)" in js
