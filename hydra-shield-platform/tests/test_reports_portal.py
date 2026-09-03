"""Offline content tests for the Phase 10 "Portals, not buttons" presentation pass.

These tests only read static files; they do not start the Flask app or make
network calls.
"""

import os

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")
WEBSITE = os.path.join(ROOT, "website")
JS = os.path.join(WEBSITE, "js")

PRODUCT_PAGES = [
    "green-finance.html",
    "sustainability.html",
    "insurance.html",
    "supplychain.html",
    "forensics.html",
]


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


# -----------------------------------------------------------------------------
# Reports portal
# -----------------------------------------------------------------------------


def test_reports_portal_has_three_family_cards():
    html = _read(os.path.join(WEBSITE, "reports.html"))
    assert "Reports &amp; Evidence Packs" in html
    assert "Green Finance Verification Report" in html
    assert "Sustainability Evidence Report (CSRD/ESRS)" in html
    assert "Insurance Environmental Risk Profile" in html
    assert "Interactive Report Builder" in html


def test_reports_portal_links_to_product_pages():
    html = _read(os.path.join(WEBSITE, "reports.html"))
    assert 'href="green-finance.html"' in html
    assert 'href="sustainability.html"' in html
    assert 'href="insurance.html"' in html
    assert 'href="report-builder.html"' in html


def test_reports_portal_has_real_examples():
    html = _read(os.path.join(WEBSITE, "reports.html"))
    assert "Clervaux, Luxembourg, 2026-08-25" in html
    assert "6 of 6 hazards assessed" in html
    assert "Demo Estates SA" in html
    assert "ESRS E1 physical risk" in html


def test_reports_portal_preserves_legacy_section():
    html = _read(os.path.join(WEBSITE, "reports.html"))
    assert "Classic wildfire reports (archive)" in html
    assert "legacy" in html.lower()
    assert 'id="legacyLocInput"' in html
    assert 'id="legacyReportActions"' in html


def test_reports_portal_has_anonymized_case_studies():
    html = _read(os.path.join(WEBSITE, "reports.html"))
    assert "How the reports were used in real decisions" in html
    assert "Credit decision" in html
    assert "underwriting referral" in html
    assert "CSRD / ESRS E1" in html
    assert html.count("Anonymized") >= 3
    assert "customer's written approval" in html


def test_reports_js_targets_legacy_dom_ids():
    js = _read(os.path.join(JS, "reports.js"))
    assert "legacyLocInput" in js
    assert "legacyReportActions" in js
    assert "legacyReportStatus" in js
    assert "/report?" in js


# -----------------------------------------------------------------------------
# Product-page real-example expanders
# -----------------------------------------------------------------------------


@pytest.mark.parametrize("page", PRODUCT_PAGES)
def test_product_page_has_real_example_expander(page):
    html = _read(os.path.join(WEBSITE, page))
    assert '<details class="expander">' in html
    assert "See a real example" in html
    assert "Real engine output" in html


def test_green_finance_example_content():
    html = _read(os.path.join(WEBSITE, "green-finance.html"))
    assert "Clervaux, Luxembourg, 2026-08-25" in html
    assert "6 of 6 hazards assessed" in html
    assert "Drought" in html and "Severe" in html


def test_sustainability_example_content():
    html = _read(os.path.join(WEBSITE, "sustainability.html"))
    assert "Demo Estates SA" in html
    assert "covered_by_evidence" in html


def test_insurance_example_content():
    html = _read(os.path.join(WEBSITE, "insurance.html"))
    assert "6 of 6 perils" in html
    assert "FIRMS key not configured" in html


def test_supplychain_example_content():
    html = _read(os.path.join(WEBSITE, "supplychain.html"))
    assert "Mato Grosso soy farm" in html
    assert "Hansen/UMD GFC" in html
    assert "no_inconsistency_detected_with_current_evidence" in html


def test_forensics_example_content():
    html = _read(os.path.join(WEBSITE, "forensics.html"))
    assert "Mato Grosso soy farm" in html
    assert "site_forested" in html
    assert "cannot_assess" in html


# -----------------------------------------------------------------------------
# Map → tools cross-links
# -----------------------------------------------------------------------------


def test_map_js_has_act_on_point_panel():
    js = _read(os.path.join(JS, "map.js"))
    assert "Act on this point" in js
    assert "green-finance.html?location=" in js
    assert "insurance.html?location=" in js
    assert "forensics.html?location=" in js
    assert "sustainability.html" in js


def test_insurance_js_has_location_prefill():
    js = _read(os.path.join(JS, "insurance.js"))
    assert "params.get('location')" in js
    assert "assetLocInput" in js


def test_forensics_js_has_location_prefill():
    js = _read(os.path.join(JS, "forensics.js"))
    assert "params.get('location')" in js
    assert "caseSiteInput" in js


def test_intelligence_js_has_forensics_cross_link():
    js = _read(os.path.join(JS, "intelligence.js"))
    assert "forensics.html?location=" in js
    assert "Open a forensic case at this location" in js
