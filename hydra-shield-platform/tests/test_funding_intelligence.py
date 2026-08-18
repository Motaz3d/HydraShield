"""Offline tests for Funding & Sustainability Intelligence
(src/climate/funding.py, config/funding_knowledge.json,
config/sustainability_taxonomy.json, /api/v2/funding).

Covers: funding provenance (official URLs, date_checked), the
no-fabrication rules (amounts/rates/deadlines honestly unstated),
funding-type vocabulary, match gates and the jurisdiction rule,
explainability, taxonomy↔solutions-KB wiring, and marketing segment
vocabulary consistency.
"""

import json
import os

import pytest

os.environ["HYDRASHIELD_CACHE_DB"] = "/tmp/hydrashield_test_funding.sqlite3"
if os.path.exists(os.environ["HYDRASHIELD_CACHE_DB"]):
    os.remove(os.environ["HYDRASHIELD_CACHE_DB"])

from src.climate import funding as funding_module  # noqa: E402
from src.climate import solutions as sol_module  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")
UNSTATED = {"not stated", "not currently verified"}


@pytest.fixture()
def kb():
    return funding_module.load_funding_knowledge()


# ---------------------------------------------------------------------------
# Knowledge base honesty
# ---------------------------------------------------------------------------


def test_funding_kb_provenance(kb):
    programmes = kb["programmes"]
    assert len(programmes) >= 10
    for p in programmes:
        assert p["official_url"].startswith("https://"), p["id"]
        assert p["source"], p["id"]
        assert p["date_checked"], p["id"]
        assert p["evidence_type"] == "official_website", p["id"]
        assert p["confidence"] in ("high", "medium", "low")


def test_funding_kb_never_fabricates_volatile_facts(kb):
    """Amounts, rates and deadlines must be honestly unstated in this
    curation — no invented figures anywhere."""
    for p in kb["programmes"]:
        assert p["funding_amount"] in UNSTATED, p["id"]
        assert p["funding_rate"] in UNSTATED, p["id"]
        assert p["deadline"] in UNSTATED, p["id"]


def test_funding_types_are_distinguished(kb):
    declared = set(kb["funding_types"])
    for p in kb["programmes"]:
        assert p["funding_type"], p["id"]
        assert set(p["funding_type"]) <= declared, p["id"]
        # "Funding is not free money": a pure-loan programme must not
        # claim to be a grant.
        if p["id"] == "eib":
            assert "grant" not in p["funding_type"]


def test_funding_kb_hazards_and_sectors_valid(kb):
    segments = json.load(open(os.path.join(
        ROOT, "marketing", "segments", "segments.json")))["segments"]
    from src.climate.ontology import HazardType
    for p in kb["programmes"]:
        for h in p["hazards"]:
            HazardType(h)
        for s in p.get("sector") or []:
            assert s in segments, (p["id"], s)


# ---------------------------------------------------------------------------
# Match engine
# ---------------------------------------------------------------------------


def test_empty_query_is_honest_insufficient():
    out = funding_module.match_funding({})
    assert out["status"] == "insufficient_data"
    assert out["matches"] == []


def test_hazard_gate_excludes_unrelated():
    out = funding_module.match_funding({"hazards": ["coastal"]})
    kb = funding_module.load_funding_knowledge()
    by_id = {p["id"]: p for p in kb["programmes"]}
    for m in out["matches"]:
        # every returned match must actually list the hazard
        assert "coastal" in by_id[m["id"]]["hazards"], m["id"]
    # CAP (drought/heat/wildfire/flood/wind, no coastal) must not match.
    assert "cap_eafrd" not in {m["id"] for m in out["matches"]}


def test_beneficiary_gate():
    out = funding_module.match_funding(
        {"hazards": ["flood"], "beneficiary": "university"})
    for m in out["matches"]:
        kb = funding_module.load_funding_knowledge()
        prog = next(p for p in kb["programmes"] if p["id"] == m["id"])
        assert "university" in prog["beneficiary_types"]


def test_jurisdiction_rule_eu_vs_global():
    lu = funding_module.match_funding({"hazards": ["flood"], "country": "LU"})
    ids = {m["id"] for m in lu["matches"]}
    assert "life_programme" in ids
    assert "green_climate_fund" not in ids       # targets developing countries
    assert "world_bank_climate" not in ids
    ke = funding_module.match_funding({"hazards": ["flood"], "country": "KE"})
    ke_ids = {m["id"] for m in ke["matches"]}
    assert "green_climate_fund" in ke_ids
    assert "life_programme" not in ke_ids        # EU programme, honest rule


def test_match_output_contract():
    out = funding_module.match_funding(
        {"hazards": ["drought"], "sector": "agriculture", "country": "ES"})
    assert out["status"] == "ok"
    m = out["matches"][0]
    for key in ("why_it_matches", "what_is_supported", "who_may_apply",
                "eligibility", "not_verified", "deadline", "official_url",
                "recommended_action", "fit"):
        assert key in m, key
    assert "not financial advice" in out["disclaimer"]
    # CAP must rank first for EU agriculture + drought.
    assert m["id"] == "cap_eafrd"


def test_no_match_is_honest():
    out = funding_module.match_funding({"hazards": ["heat"],
                                        "beneficiary": "zzz_unknown"})
    assert out["status"] in ("no_match", "ok")
    if out["status"] == "no_match":
        assert out["matches"] == []


# ---------------------------------------------------------------------------
# Taxonomy wiring
# ---------------------------------------------------------------------------


def test_taxonomy_references_real_solutions():
    tax = json.load(open(os.path.join(
        ROOT, "config", "sustainability_taxonomy.json")))
    kb = sol_module.load_solutions_knowledge()
    solution_ids = {s["solution_id"] for s in kb["solutions"]}
    declared_classes = set(kb["solution_classes"])
    for entry in tax["classifications"]:
        assert entry["class"] in declared_classes
        for ref in entry["solution_refs"]:
            assert ref in solution_ids, (entry["class"], ref)
        assert entry["objectives"]
        assert set(entry["objectives"]) <= set(tax["objectives"])


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("HYDRASHIELD_CACHE_DB", str(tmp_path / "api.sqlite3"))
    import src.dashboard.cache as cache_mod
    monkeypatch.setattr(cache_mod, "_default_cache", None)
    from src.dashboard.api import create_app

    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def test_funding_endpoint_contract(client):
    resp = client.get("/api/v2/funding?hazards=flood&country=DE")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "ok"
    assert body["matches"]
    assert body["disclaimer"]
    assert body["provenance"]["limitations"]


def test_funding_endpoint_insufficient(client):
    resp = client.get("/api/v2/funding")
    assert resp.get_json()["status"] == "insufficient_data"


def test_funding_endpoint_unknown_hazard_tolerated(client):
    resp = client.get("/api/v2/funding?hazards=flood,tsunami")
    body = resp.get_json()
    assert body["query"]["unknown_hazards_requested"] == ["tsunami"]
    assert body["query"]["hazards"] == ["flood"]
