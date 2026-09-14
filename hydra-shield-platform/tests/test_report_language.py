"""Regression tests: customer-facing documents must use business language.

Internal identifiers (``covered_by_evidence``, ``hazard_match_only``, …) are
machine contracts. A PDF report, a website page or a generated brief must never
print one. These tests pin the business-language label layer and scan the
shipped artefacts for identifier leaks.
"""

import io
import os
import re

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")
WEBSITE = os.path.join(ROOT, "website")

#: A snake_case identifier — the shape that must never reach a report.
_IDENTIFIER = re.compile(r"\b[a-z][a-z0-9]*_[a-z0-9_]+\b")


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _pdf_text(blob):
    pypdf = pytest.importorskip("pypdf")
    reader = pypdf.PdfReader(io.BytesIO(blob))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


# -----------------------------------------------------------------------------
# The label layer
# -----------------------------------------------------------------------------

def test_coverage_label_is_business_language():
    from src.climate.sustainability import COVERAGE_LABELS, coverage_label

    assert coverage_label("covered_by_evidence") == "Covered by evidence"
    assert coverage_label("partial") == "Partially covered"
    assert coverage_label("not_covered") == "Not covered — declared boundary"
    assert coverage_label(None) == "Not assessed"
    for label in COVERAGE_LABELS.values():
        assert "_" not in label
    # An unknown status must still read as prose, never as an identifier.
    assert "_" not in coverage_label("some_new_status")


def test_fit_band_label_is_business_language():
    from src.climate.solutions import FIT_BAND_LABELS, fit_band_label

    assert fit_band_label("hazard_match_only") == "Hazard match only"
    assert fit_band_label("high") == "High"
    assert fit_band_label(None) == "Not assessed"
    for label in FIT_BAND_LABELS.values():
        assert "_" not in label


def test_component_label_is_business_language():
    from src.dashboard.ignition import COMPONENT_LABELS, component_label

    assert component_label("fire_weather") == "Fire weather"
    assert component_label("human_presence") == "Human presence"
    assert component_label("fuel_dryness") == "Fuel dryness"
    for label in COMPONENT_LABELS.values():
        assert "_" not in label


def test_human_label_never_leaks_an_identifier():
    from src.dashboard.report_language import human_label

    assert human_label("fire_stations") == "Fire stations"
    assert human_label("landcover") == "Land cover"
    assert human_label("some_unmapped_key") == "Some unmapped key"
    assert human_label(None) == "—"


# -----------------------------------------------------------------------------
# Shipped artefacts
# -----------------------------------------------------------------------------

def test_sample_pack_source_uses_business_language():
    md = _read(os.path.join(WEBSITE, "assets", "samples",
                            "talaix-sample-evidence-pack.md"))
    assert "covered_by_evidence" not in md
    assert "not_covered" not in md
    assert "Covered by evidence" in md
    assert "Not covered — declared boundary" in md
    assert not _IDENTIFIER.search(md), _IDENTIFIER.findall(md)


def test_sample_pack_pdf_has_no_identifier():
    path = os.path.join(WEBSITE, "assets", "samples",
                        "talaix-sample-evidence-pack.pdf")
    text = _pdf_text(open(path, "rb").read())
    assert "Covered by evidence" in text
    assert "declared boundary" in text
    assert not _IDENTIFIER.search(text), _IDENTIFIER.findall(text)


def test_sustainability_pdf_has_no_identifier():
    from src.climate.sustainability import ESRS_COVERAGE
    from src.dashboard.sustainability_report import build_sustainability_pdf

    payload = {
        "report_id": "abc123",
        "generated_at": "2026-09-14T00:00:00Z",
        "engine_version": "1.0.0",
        "company": {"fields": {"name": "Acme SA", "sector": "renewables",
                               "country": "Luxembourg", "website": "",
                               "description": ""}},
        "coverage_map": ESRS_COVERAGE,
        "frameworks": [],
        "evidence_standard": {"name": "Talaix Evidence Standard",
                              "criteria": ["Every claim carries a claim status."],
                              "not_accreditation": "Not an accreditation."},
        "portfolio_summary": {"site_count": 0, "ok_count": 0,
                              "total_declared_gaps": 0, "highest_levels": {}},
        "site_results": [],
        "declared_gaps": [],
        "disclaimer": "Not assurance.",
        "honesty_contract": "Nothing is invented.",
        "authenticity": {"code": "XYZ"},
    }
    text = _pdf_text(build_sustainability_pdf(payload))
    assert "covered_by_evidence" not in text
    assert "not_covered" not in text
    assert "Covered by evidence" in text
    assert "Not covered — declared boundary" in text
    # Escaped markup must be interpreted, not printed (ESRS E3 holds a real "&").
    assert "&amp;" not in text
    assert "ESRS E3 — Water & marine resources" in text
    assert not _IDENTIFIER.search(text), _IDENTIFIER.findall(text)


def test_website_pages_have_no_internal_coverage_tokens():
    for page in ("reports.html", "sustainability.html", "sample.html"):
        html = _read(os.path.join(WEBSITE, page))
        assert "covered_by_evidence" not in html, page
        assert "not_covered" not in html, page


def test_generated_briefs_and_configs_use_business_language():
    brief = _read(os.path.join(WEBSITE, "briefs",
                               "explainer-esrs-e1-physical-risk.html"))
    assert "covered_by_evidence" not in brief
    for cfg in ("academy_course.json", "academy_knowledge.json",
                "briefs_registry.json"):
        text = _read(os.path.join(ROOT, "config", cfg))
        assert "covered_by_evidence" not in text, cfg
        assert "not_covered" not in text, cfg
