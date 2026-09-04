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
    # The footer's "By sector" column lists every industry (into the
    # consolidated hub); journalists land on the press tool via "Learn &
    # company".
    assert "{ id: 'for-banks', href: 'industries.html?sector=banks', label: 'Banks & lenders' }" in chrome
    assert "{ id: 'press', href: 'press.html', label: 'Press' }" in chrome
    # Footer renders a "By sector" column with the industries hub links.
    assert "heading: 'By sector'" in chrome
    assert "industries.html?sector=government" in chrome


def test_sitemap_covers_press_surfaces():
    sitemap = _read("website/sitemap.xml")
    assert "https://talaix.com/press.html" in sitemap
    assert "https://talaix.com/industries.html" in sitemap
    assert "https://talaix.com/intelligence.html" in sitemap
    # Retired URLs: merged into hubs (redirect only), so they must not stay
    # in the sitemap.
    assert "https://talaix.com/sector.html" not in sitemap
    assert "https://talaix.com/solutions.html" not in sitemap
    assert "https://talaix.com/report-builder.html" not in sitemap


def test_siting_funding_merged_into_intelligence_hub():
    """Where to Invest merged into intelligence.html as the Siting and
    Funding tabs: the old URL permanently redirects (Caddyfile), the static
    stub covers non-Caddy previews, and the nav carries one merged entry."""
    caddy = _read("Caddyfile")
    assert "redir /solutions.html /intelligence.html" in caddy
    stub = _read("website/solutions.html")
    assert "intelligence.html" in stub
    chrome = _read("website/js/chrome.js")
    assert "href: 'solutions.html'" not in chrome
    assert "Investment & Siting" in chrome
    hub = _read("website/intelligence.html")
    assert 'id="sitingPanel"' in hub and 'id="fundingPanel"' in hub
    js = _read("website/js/intelligence.js")
    assert "{ id: 'siting', name: 'Siting' }" in js
    assert "{ id: 'funding', name: 'Funding' }" in js


def test_report_builder_merged_into_reports_portal():
    """Report Builder merged into reports.html as the #builder section: the
    old URL permanently redirects (Caddyfile + static stub)."""
    caddy = _read("Caddyfile")
    assert "redir /report-builder.html /reports.html#builder" in caddy
    stub = _read("website/report-builder.html")
    assert "reports.html#builder" in stub
    portal = _read("website/reports.html")
    assert 'id="builder"' in portal
    assert "js/report-builder.js" in portal


def test_sector_exposure_merged_into_intelligence_hub():
    """Sector Exposure merged into intelligence.html as a hub tab: the old
    URL permanently redirects (Caddyfile), the static stub covers non-Caddy
    previews, and the primary nav drops the standalone entry (6 -> 5)."""
    caddy = _read("Caddyfile")
    assert "redir /sector.html /intelligence.html?mode=sector" in caddy
    stub = _read("website/sector.html")
    assert "intelligence.html" in stub and "#sector" in stub
    chrome = _read("website/js/chrome.js")
    assert "href: 'sector.html'" not in chrome
    hub = _read("website/intelligence.html")
    assert 'id="sectorPanel"' in hub
    js = _read("website/js/intelligence.js")
    assert "{ id: 'sector', name: 'Sector Exposure' }" in js


def test_sign_out_lives_in_account_page_not_nav():
    """Design rule: the top nav never renders a permanent sign-out prompt —
    an always-visible exit is an indirect invitation to leave. Signing out
    happens from the Profile panel inside the Account page."""
    chrome = _read("website/js/chrome.js")
    assert "navSignOut" not in chrome
    assert "Sign out" not in chrome
    acct = _read("website/account.html")
    assert 'id="logoutBtn"' in acct


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
