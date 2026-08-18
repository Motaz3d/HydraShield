"""Tests for the hazard-first commercial radar
(src/dashboard/hazard_market.py).

Fixtures only — no real prospects or signals are fabricated into the
committed workspace; these use synthetic in-test records.
"""

import os
import sys

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)

from src.dashboard.hazard_market import (  # noqa: E402
    area_country_iso, build_opportunities)


def _lead(org, country, segment, hazards, priority="medium"):
    return {
        "organization": org, "country": country, "segment": segment,
        "relevant_hazards": hazards, "priority": priority,
        "status": "open",
        "identified_problem": f"{org} problem hypothesis",
        "recommended_product": "monitoring",
        "recommended_message": f"message for {org}",
        "next_action": "qualify",
        "source": "https://example.org", "date_checked": "2026-08-18",
    }


_AREAS = [{"name": "Andalusia (Huelva), Spain", "risk_class": "High"},
          {"name": "Sicily (Enna), Italy", "risk_class": "Extreme"}]


def test_area_country_extraction():
    assert area_country_iso("Andalusia (Huelva), Spain") == "ES"
    assert area_country_iso("Sicily (Enna), Italy") == "IT"
    assert area_country_iso("Provence (Var), France") == "FR"
    assert area_country_iso("Unknown Region") is None  # never guessed


def test_geographic_match_wins():
    leads = [
        _lead("Spain Insurer", "ES", "insurance", ["flood"]),
        _lead("Italy Consultant", "IT", "environmental_consulting", ["wildfire"]),
        _lead("France Investor", "FR", "investment", ["wildfire"]),
    ]
    opps = build_opportunities(leads, _AREAS)
    by_org = {o["organization"]: o for o in opps}
    # Spain Insurer: geographic match even though wildfire isn't its hazard
    assert by_org["Spain Insurer"]["match"] == "geographic"
    assert by_org["Spain Insurer"]["country"] == "ES"
    # France Investor: no FR area → hazard-interest match only
    assert by_org["France Investor"]["match"] == "hazard_interest"


def test_no_fabrication_when_nothing_matches():
    leads = [_lead("German Bank", "DE", "investment", ["flood"])]
    assert build_opportunities(leads, _AREAS) == []


def test_dedupe_per_organization():
    leads = [_lead("Italy Insurer", "IT", "insurance", ["wildfire"])]
    opps = build_opportunities(leads, _AREAS)
    assert len([o for o in opps if o["organization"] == "Italy Insurer"]) == 1


def test_opportunity_carries_full_evidence_chain():
    leads = [_lead("Spain Consultant", "ES", "environmental_consulting",
                   ["wildfire"], priority="high")]
    product_matching = {"environmental_consulting": ["hazard_analysis", "reports"]}
    opps = build_opportunities(leads, _AREAS, product_matching)
    o = opps[0]
    assert o["hazard"] == "wildfire"
    assert o["area"] == "Andalusia (Huelva), Spain"
    assert o["product_fit"] == ["hazard_analysis", "reports"]
    assert "live platform snapshot" in o["why_now"]
    assert o["evidence"]["lead_source"] == "https://example.org"
    assert o["evidence"]["date_checked"] == "2026-08-18"
    assert o["message"] and o["next_action"]


def test_won_lost_leads_excluded():
    leads = [_lead("Won Corp", "ES", "insurance", ["wildfire"])]
    leads[0]["status"] = "won"
    assert build_opportunities(leads, _AREAS) == []


def test_asia_country_mapping():
    """The radar's geography covers the Asia expansion countries."""
    assert area_country_iso("Henan Province, China") == "CN"
    assert area_country_iso("Kerala, India") == "IN"
    assert area_country_iso("Metro Manila, Philippines") == "PH"
    assert area_country_iso("Singapore") == "SG"
    assert area_country_iso("Ho Chi Minh City, Vietnam") == "VN"
    assert area_country_iso("Busan, South Korea") == "KR"
    assert area_country_iso("Kanto, Japan") == "JP"
