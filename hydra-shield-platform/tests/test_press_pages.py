"""Content assertions for the Press sector presence (for-journalists page,
nav placement, sitemap coverage and cross-links)."""

import os

ROOT = os.path.dirname(__file__)


def _read(rel):
    with open(os.path.join(ROOT, "..", rel), encoding="utf-8") as fh:
        return fh.read()


def test_for_journalists_page_exists_and_links_the_tool():
    html = _read("website/for-journalists.html")
    assert 'data-page="for-journalists"' in html
    assert "press.html" in html
    assert "guest-only" in html
    assert "user-only" in html
    # The live RTL example is part of the page (real, dated example).
    assert "RTL.lu" in html
    assert "26 Aug 2026" in html


def test_journalists_in_nav_sector_column_and_footer():
    chrome = _read("website/js/chrome.js")
    assert "{ id: 'for-journalists', href: 'for-journalists.html', label: 'Journalists & media' }" in chrome
    assert '<li><a href="for-journalists.html">Journalists &amp; media</a></li>' in chrome


def test_sitemap_covers_press_surfaces():
    sitemap = _read("website/sitemap.xml")
    assert "https://talaix.com/press.html" in sitemap
    assert "https://talaix.com/for-journalists.html" in sitemap
    assert "https://talaix.com/sector.html" in sitemap
    assert "https://talaix.com/mapcheck.html" in sitemap
    assert "https://talaix.com/report-builder.html" in sitemap


def test_map_act_on_point_links_press_pack():
    mapjs = _read("website/js/map.js")
    assert "press.html?location=" in mapjs


def test_press_page_has_steps_example_and_pack_contents():
    html = _read("website/press.html")
    assert "pressExampleBtn" in html
    assert "problem-grid" in html
    assert "today.rtl.lu" in html
    assert "Satellite &amp; maps" in html


def test_press_js_wires_example_and_location_prefill():
    js = _read("website/js/press.js")
    assert "pressExampleBtn" in js
    assert "generatePack" in js
    assert "location.search" in js
    assert ".get('location')" in js
