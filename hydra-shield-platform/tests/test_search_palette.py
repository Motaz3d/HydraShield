"""Tests for the site-wide command-palette quick search.

A Node harness exercises the DOM-free filterIndex logic, and static file
assertions verify that the palette, nav button and styles are wired together.
"""

import json
import os
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(__file__)
WEBSITE = os.path.join(ROOT, "..", "website")
JS = os.path.join(WEBSITE, "js")


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


# -----------------------------------------------------------------------------
# Node harness
# -----------------------------------------------------------------------------


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_harness_filter_index():
    result = subprocess.run(
        ["node", os.path.join(ROOT, "harness_search.js")],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)

    # Empty query returns entries in group order.
    groups = [e["group"] for e in out["empty"]]
    assert groups == ["Navigation", "Navigation", "Navigation", "Actions", "Actions", "Location", "Glossary", "Briefs"]

    # Substring filtering across label + keywords.
    verify_labels = [e["label"] for e in out["verify"]]
    assert "Verify an asset" in verify_labels
    assert "Verify Venice" in verify_labels

    map_labels = [e["label"] for e in out["map"]]
    assert "Map" in map_labels
    assert "Map Check" in map_labels

    # Fallback actions for unmatched queries.
    assert len(out["fallback"]) == 2
    assert out["fallback"][0]["label"] == "Search map for 'Ljubljana'"
    assert out["fallback"][1]["label"] == "Verify 'Ljubljana'"
    no_match_labels = [e["label"] for e in out["no_match"]]
    assert "Search map for 'Ljubljana'" in no_match_labels
    assert "Verify 'Ljubljana'" in no_match_labels

    # Cap of 7 per group.
    assert len(out["capped"]) == 7

    # Location actions from stubbed HS.lastLocation().
    loc_labels = [e["label"] for e in out["location_actions"]]
    assert "Verify Venice" in loc_labels
    assert "Map Check Venice" in loc_labels
    assert "Profile Venice (insurance)" in loc_labels

    # Static Actions list contains the required portals.
    actions = out["action_labels"]
    assert "Verify an asset" in actions
    assert "Build a CSRD evidence report" in actions
    assert "Profile an insured asset" in actions
    assert "Screen an origin claim (EUDR)" in actions
    assert "Open a forensic case" in actions
    assert "Compose a report" in actions
    assert "Map-vs-satellite check" in actions
    assert "Take the Academy course" in actions
    assert "Read evidence briefs" in actions


# -----------------------------------------------------------------------------
# Static file assertions
# -----------------------------------------------------------------------------


def test_search_js_exports_filter_index_and_api():
    js = _read(os.path.join(JS, "search.js"))
    assert "window.HSSearch = {" in js
    assert "filterIndex: filterIndex" in js
    assert "open: open" in js
    assert "close: close" in js


def test_search_js_contains_required_actions():
    js = _read(os.path.join(JS, "search.js"))
    assert "green-finance.html" in js
    assert "sustainability.html" in js
    assert "insurance.html" in js
    assert "supplychain.html" in js
    assert "forensics.html" in js
    assert "report-builder.html" in js
    assert "map.html?mode=check" in js
    assert "academy.html" in js
    assert "briefs.html" in js


def test_search_js_lazy_fetches_glossary_and_briefs():
    js = _read(os.path.join(JS, "search.js"))
    assert "/v2/academy/glossary" in js
    assert "/v2/briefs" in js


def test_chrome_js_has_search_button_and_nav_links_export():
    js = _read(os.path.join(JS, "chrome.js"))
    assert "navSearchBtn" in js
    assert "HS_NAV_LINKS = ALL_LINKS" in js
    assert "js/search.js" in js
    assert "window.HSSearch" in js
    assert "window.HSSearch.open" in js


def test_style_css_has_search_classes():
    css = _read(os.path.join(WEBSITE, "css", "style.css"))
    assert ".search-overlay" in css
    assert ".search-dialog" in css
    assert ".search-input" in css
    assert ".search-results" in css
    assert ".search-item" in css
    assert ".search-item.active" in css
    assert ".search-footer" in css
    assert ".nav-search" in css
