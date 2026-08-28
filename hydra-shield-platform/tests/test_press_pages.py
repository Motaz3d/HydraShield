"""Content assertions for the Press sector presence (journalists portal —
consolidated into press.html + the industries hub — nav placement, sitemap
coverage and cross-links)."""

import os

ROOT = os.path.dirname(__file__)


def _read(rel):
    with open(os.path.join(ROOT, "..", rel), encoding="utf-8") as fh:
        return fh.read()


def test_for_journalists_redirects_into_press():
    """The for-journalists landing page merged into press.html: the old URL
    permanently redirects (Caddyfile), and the press tool page itself is the
    journalists portal (live RTL example, pack contents)."""
    caddy = _read("Caddyfile")
    assert "redir /for-journalists.html /press.html permanent" in caddy
    html = _read("website/press.html")
    # The live RTL example is part of the page (real, dated example).
    assert "RTL.lu" in html
    assert "26 Aug 2026" in html


def test_industries_hub_in_nav_sector_column_and_footer():
    chrome = _read("website/js/chrome.js")
    # The sector column lists every industry (into the consolidated hub);
    # journalists land on the press tool directly.
    assert "{ id: 'for-banks', href: 'industries.html?sector=banks', label: 'Banks & lenders' }" in chrome
    assert "{ id: 'for-journalists', href: 'press.html', label: 'Journalists & media' }" in chrome
    # Footer renders its "By sector" column from the same PRIMARY structure.
    assert "heading: 'By sector'" in chrome
    assert "PRIMARY[2].columns[1].children" in chrome


def test_sitemap_covers_press_surfaces():
    sitemap = _read("website/sitemap.xml")
    assert "https://talaix.com/press.html" in sitemap
    assert "https://talaix.com/industries.html" in sitemap
    assert "https://talaix.com/sector.html" in sitemap
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
