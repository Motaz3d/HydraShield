"""Tests for the CsrdTX regulatory intelligence engine.

Unit tests cover the deterministic math (applicability, double
materiality, readiness) directly; API tests run fully offline with
stubbed hazard modules, mirroring tests/test_sustainability.py.
"""

import os

import pytest

os.environ["HYDRASHIELD_CACHE_DB"] = "/tmp/hydrashield_test_csrd_cache.sqlite3"
if os.path.exists(os.environ["HYDRASHIELD_CACHE_DB"]):
    os.remove(os.environ["HYDRASHIELD_CACHE_DB"])

from src.climate import registry  # noqa: E402
from src.climate.csrd.applicability import assess_applicability  # noqa: E402
from src.climate.csrd.engine import build_csrd_assessment  # noqa: E402
from src.climate.csrd.materiality import (  # noqa: E402
    assess_topic,
    hazard_exposure_seed,
    score_financial,
    score_impact,
)
from src.climate.csrd.readiness import compute_readiness  # noqa: E402
from src.climate.csrd.regulations import (  # noqa: E402
    esrs_version,
    esrs_versions,
    load_changelog,
    rule_set_for_year,
)
from src.climate.hazards.base import HazardAnalysis, HazardLevel  # noqa: E402
from src.dashboard.api import create_app  # noqa: E402


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _fresh_registry(monkeypatch):
    registry.reset_for_tests()
    yield
    registry.reset_for_tests()


@pytest.fixture()
def env(tmp_path, monkeypatch):
    db_path = tmp_path / "csrd.sqlite3"
    monkeypatch.setenv("HYDRASHIELD_CACHE_DB", str(db_path))
    monkeypatch.setenv("HYDRASHIELD_OUTBOX_DIR", str(tmp_path / "outbox"))
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.delenv("SMTP_USER", raising=False)
    import src.dashboard.cache as cache_mod
    import src.dashboard.api as api_module

    monkeypatch.setattr(cache_mod, "_default_cache", None)
    api_module._rate_limiter._hits.clear()
    return {"db": db_path, "outbox": tmp_path / "outbox"}


@pytest.fixture()
def client(env):
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


class _FakeOkModule:
    def __init__(self, hazard_id: str):
        self.id = hazard_id

    def availability(self):
        return True, None

    def analyze(self, lat, lon, name=None):
        return HazardAnalysis(
            hazard=self.id,
            location={"lat": lat, "lon": lon, "name": name},
            status="ok",
            summary=f"{self.id} screening ok",
            level=HazardLevel(
                label="High",
                score=0.8,
                score_max=1.0,
                basis="modelled screening indicator",
                validated=False,
            ),
            evidence=[{
                "evidence_class": "MODELLED",
                "claim_status": "MODELLED",
                "temporal": "OBSERVED",
                "source": "Fake source",
                "dataset": "Fake dataset",
            }],
            provenance={"model": {"source": "Fake"}},
        )


def _stub_registry(monkeypatch, ok=("flood", "heat")):
    def fake_get(hazard_id: str):
        if hazard_id in ok:
            return _FakeOkModule(hazard_id)
        return None

    monkeypatch.setattr(registry, "get", fake_get)


def _register(client, email="user@example.org", password="correct horse battery"):
    resp = client.post(
        "/api/v2/auth/register",
        json={
            "email": email,
            "password": password,
            "display_name": "Test User",
            "consent": True,
        },
    )
    assert resp.status_code == 201, resp.get_json()
    return resp


def _verification_token(outbox_dir):
    import email as email_lib
    import re

    files = sorted(outbox_dir.glob("*_email_verification_*.eml"))
    assert files, "no verification email in outbox"
    raw = files[-1].read_text(encoding="utf-8")
    msg = email_lib.message_from_string(raw)
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                body = part.get_payload(decode=True).decode("utf-8", errors="ignore")
                break
    else:
        body = msg.get_payload(decode=True).decode("utf-8", errors="ignore")
    match = re.search(r"token=([A-Za-z0-9_\-]+)", body)
    assert match, "no verification token in email"
    return match.group(1)


def _register_and_verify(client, env, email="user@example.org", password="correct horse battery"):
    _register(client, email, password)
    token = _verification_token(env["outbox"])
    resp = client.get(f"/api/v2/auth/verify?token={token}")
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    return body["user"], body["session_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


# -----------------------------------------------------------------------------
# Regulatory knowledge base
# -----------------------------------------------------------------------------


def test_esrs_default_is_in_force():
    doc = esrs_version()
    assert doc["version_id"] == "esrs_2023"
    assert doc["status"] == "in_force"
    assert doc["topics"]


def test_esrs_2026_inherits_topics_and_keeps_status():
    doc = esrs_version("esrs_2026_simplified")
    assert doc["status"] == "adopted_pending_application"
    assert doc["topics_inherited_from"] == "esrs_2023"
    assert doc["topics"]  # inherited, not empty


def test_esrs_unknown_version_rejected():
    with pytest.raises(ValueError):
        esrs_version("esrs_2099")


def test_rule_set_excludes_proposed_by_default():
    rs = rule_set_for_year(2027)
    assert rs["status"] == "in_force"
    proposed = rule_set_for_year(2027, statuses=("proposed",))
    assert proposed["id"] == "omnibus_2025_proposal"


def test_changelog_loads_events_with_status():
    log = load_changelog()
    assert log["events"]
    assert all(e.get("status") for e in log["events"])
    assert any(e["id"] == "esrs-2026-simplified" for e in log["events"])


# -----------------------------------------------------------------------------
# Applicability engine
# -----------------------------------------------------------------------------


def test_large_eu_company_in_scope_wave2():
    result = assess_applicability({
        "name": "BigCo SA",
        "country": "Luxembourg",
        "employees": 600,
        "net_turnover_eur": 90000000,
        "balance_sheet_total_eur": 40000000,
        "listed": False,
        "reporting_year": 2027,
    })
    assert result["determination"] == "in_scope"
    assert result["wave"]["wave"] == 2
    assert result["wave"]["first_reporting_year"] == 2027
    assert result["rule_set"]["id"] == "csrd_2023_original"
    # Omnibus outlook: 600 employees < 1000 → would leave scope if adopted.
    assert result["forward_outlook"]["rule_set_status"] == "proposed"
    assert result["forward_outlook"]["determination_if_adopted"] == "out_of_scope"


def test_small_eu_company_out_of_scope_gets_vsme_route():
    result = assess_applicability({
        "name": "SmallCo SARL",
        "country": "Germany",
        "employees": 20,
        "net_turnover_eur": 3000000,
        "balance_sheet_total_eur": 1000000,
        "listed": False,
    })
    assert result["determination"] == "out_of_scope"
    assert result["voluntary_route"]["route"] == "vsme_voluntary"


def test_wave1_public_interest_company():
    result = assess_applicability({
        "name": "ListedBank SA",
        "country": "France",
        "employees": 900,
        "net_turnover_eur": 500000000,
        "balance_sheet_total_eur": 900000000,
        "listed": True,
        "public_interest": True,
        "previously_nfrd": True,
        "reporting_year": 2024,
    })
    assert result["determination"] == "in_scope"
    assert result["wave"]["wave"] == 1


def test_non_eu_above_threshold_with_subsidiary_wave4():
    result = assess_applicability({
        "name": "USCorp Inc",
        "country": "United States",
        "non_eu_eu_turnover_eur": 200000000,
        "has_eu_branch_or_subsidiary": True,
    })
    assert result["determination"] == "in_scope"
    assert result["wave"]["wave"] == 4


def test_non_eu_above_threshold_without_presence_potential():
    result = assess_applicability({
        "name": "USCorp Inc",
        "country": "United States",
        "non_eu_eu_turnover_eur": 200000000,
    })
    assert result["determination"] == "potentially_in_scope"


def test_missing_facts_never_guessed():
    result = assess_applicability({"name": "MysteryCo"})
    assert result["determination"] in (
        "potentially_in_scope",
        "requires_legal_confirmation",
    )
    assert result["size_evaluation"]["criteria"]["employees"] == "unknown"


def test_undetermined_size_is_potentially_in_scope():
    result = assess_applicability({
        "name": "HalfKnown SA",
        "country": "Spain",
        "employees": 800,
        "net_turnover_eur": 60000000,
        # balance sheet unknown: 2 of 3 met already → large → in scope
    })
    assert result["determination"] == "in_scope"

    result2 = assess_applicability({
        "name": "QuarterKnown SA",
        "country": "Spain",
        "employees": 800,
        # turnover and balance sheet unknown → undetermined
    })
    assert result2["determination"] == "potentially_in_scope"


def test_numeric_validation():
    with pytest.raises(ValueError):
        assess_applicability({"name": "X", "employees": "many"})
    with pytest.raises(ValueError):
        assess_applicability({"name": ""})


# -----------------------------------------------------------------------------
# Double materiality math
# -----------------------------------------------------------------------------


def test_impact_score_actual_vs_potential():
    assert score_impact(4, 4, 4, actual=True) == 4.0
    assert score_impact(4, 4, 4, likelihood=0.5) == 2.0
    assert score_impact(0, 0, 0, actual=True) == 0.0


def test_financial_score():
    assert score_financial(4, 0.5) == 2.0
    assert score_financial(5, 1.0) == 5.0


def test_score_bounds_enforced():
    with pytest.raises(ValueError):
        score_impact(6, 1, 1)
    with pytest.raises(ValueError):
        score_financial(1, 1.5)


def test_assess_topic_union_semantics():
    # Impact below threshold, financial above → material on financial basis.
    result = assess_topic(
        "E1",
        impact={"scale": 1, "scope": 1, "irremediability": 1, "likelihood": 1.0, "evidence_grade": "B"},
        financial={"magnitude": 4.5, "likelihood": 0.9, "evidence_grade": "B"},
    )
    assert result["material"] is True
    assert result["basis"] == "financial"
    assert result["combined_score"] == max(result["impact_score"], result["financial_score"])

    none = assess_topic(
        "E5",
        impact={"scale": 1, "scope": 1, "irremediability": 1, "likelihood": 0.5, "evidence_grade": "D"},
    )
    assert none["material"] is False
    assert none["basis"] == "none"


def test_confidence_tracks_evidence_grades():
    strong = assess_topic(
        "E1",
        financial={"magnitude": 4, "likelihood": 1.0, "evidence_grade": "A"},
    )
    weak = assess_topic(
        "E1",
        financial={"magnitude": 4, "likelihood": 1.0, "evidence_grade": "E"},
    )
    assert strong["confidence"] > weak["confidence"]
    assert strong["confidence_label"] == "high"
    assert weak["confidence_label"] == "low"


def test_hazard_seed_from_site_results():
    sites = [
        {"ok": True, "hazard_levels": {"flood": "High", "heat": "Moderate"}},
        {"ok": True, "hazard_levels": {"flood": "Low"}},
    ]
    seed = hazard_exposure_seed(sites)
    assert seed is not None
    assert seed["magnitude"] == 3.5  # "High" maps to 3.5
    assert 0.0 < seed["likelihood"] <= 1.0
    assert seed["evidence_grade"] == "B"

    assert hazard_exposure_seed([]) is None
    assert hazard_exposure_seed([{"ok": True, "hazard_levels": {}}]) is None


# -----------------------------------------------------------------------------
# Readiness composite
# -----------------------------------------------------------------------------


def test_readiness_weights_sum_to_one():
    from src.climate.csrd.readiness import WEIGHTS

    assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9


def test_readiness_deterministic_and_bounded():
    applicability = assess_applicability({
        "name": "BigCo SA", "country": "Luxembourg", "employees": 600,
        "net_turnover_eur": 90000000, "balance_sheet_total_eur": 40000000,
    })
    esrs_doc = esrs_version()
    profile = {"name": "BigCo SA", "country": "Luxembourg", "sector": None,
               "employees": 600, "net_turnover_eur": 90000000,
               "balance_sheet_total_eur": 40000000, "listed": False}
    materiality = [assess_topic(
        "E1", financial={"magnitude": 3.5, "likelihood": 0.8, "evidence_grade": "B"}
    )]
    r1 = compute_readiness(applicability, esrs_doc, profile, [], materiality)
    r2 = compute_readiness(applicability, esrs_doc, profile, [], materiality)
    assert r1 == r2
    assert 0 <= r1["overall"] <= 100
    assert set(r1["components"]) == set(r1["weights"])


# -----------------------------------------------------------------------------
# Full assessment — never invent, determinism
# -----------------------------------------------------------------------------


def test_assessment_never_invents_missing_topics():
    result = build_csrd_assessment(
        {"name": "EmptyCo", "country": "Luxembourg"},
        verify_sites=False,
    )
    assert result["assessment_id"]
    by_topic = {m["topic"]: m for m in result["materiality"]}
    # E1 has no sites → no seed → NOT_ASSESSED, never a fabricated score.
    assert by_topic["E1"]["status"] == "NOT_ASSESSED"
    assert by_topic["E1"]["combined_score"] is None
    assert by_topic["S1"]["status"] == "NOT_ASSESSED"
    assert by_topic["S1"]["reason"]
    assert result["readiness"]["overall"] < 100
    assert result["gap_analysis"]
    assert result["authenticity"]["code"].startswith("TX-")


def test_assessment_deterministic_id():
    company = {"name": "DetCo", "country": "Luxembourg", "employees": 600,
               "net_turnover_eur": 90000000, "balance_sheet_total_eur": 40000000}
    r1 = build_csrd_assessment(company, verify_sites=False)
    r2 = build_csrd_assessment(company, verify_sites=False)
    assert r1["assessment_id"] == r2["assessment_id"]
    assert r1["readiness"] == r2["readiness"]


def test_assessment_e1_seeded_from_sites(monkeypatch):
    _stub_registry(monkeypatch, ok=("flood", "heat"))
    result = build_csrd_assessment(
        {"name": "SiteCo", "country": "Luxembourg"},
        assets=[{"name": "Trier", "lat": 49.75, "lon": 6.64}],
    )
    by_topic = {m["topic"]: m for m in result["materiality"]}
    assert by_topic["E1"]["status"] == "ASSESSED"
    assert by_topic["E1"]["financial_score"] is not None
    assert by_topic["E1"]["confidence"] > 0
    assert result["site_results"][0]["verification_id"]


# -----------------------------------------------------------------------------
# API endpoints
# -----------------------------------------------------------------------------


def test_regulations_public(client):
    resp = client.get("/api/v2/csrd/regulations")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["esrs_versions"]
    assert any(v["id"] == "esrs_2026_simplified" for v in data["esrs_versions"])
    assert data["wave_calendar"]
    assert data["changelog"]
    assert data["status_vocabulary"]


def test_applicability_unauthenticated(client):
    resp = client.post("/api/v2/csrd/applicability", json={"company": {"name": "X"}})
    assert resp.status_code in (401, 403)


def test_applicability_authenticated(client, env):
    _, token = _register_and_verify(client, env)
    resp = client.post(
        "/api/v2/csrd/applicability",
        json={"company": {
            "name": "BigCo SA", "country": "Luxembourg", "employees": 600,
            "net_turnover_eur": 90000000, "balance_sheet_total_eur": 40000000,
        }},
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.get_json()
    data = resp.get_json()
    assert data["determination"] == "in_scope"
    assert data["wave"]["wave"] == 2


def test_assessment_endpoint(client, env, monkeypatch):
    _stub_registry(monkeypatch, ok=("flood", "heat"))
    _, token = _register_and_verify(client, env)
    resp = client.post(
        "/api/v2/csrd/assessment",
        json={
            "company": {"name": "Acme SA", "country": "Luxembourg", "employees": 600,
                        "net_turnover_eur": 90000000, "balance_sheet_total_eur": 40000000},
            "assets": [{"name": "Trier", "lat": 49.75, "lon": 6.64}],
        },
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.get_json()
    data = resp.get_json()
    assert data["engine"] == "CsrdTX"
    assert data["assessment_id"]
    assert data["applicability"]["determination"] == "in_scope"
    assert data["readiness"]["overall"] > 0
    assert data["coverage_matrix"]
    assert data["esrs"]["version_id"] == "esrs_2023"


def test_assessment_requires_name(client, env):
    _, token = _register_and_verify(client, env)
    resp = client.post(
        "/api/v2/csrd/assessment",
        json={"company": {"sector": "x"}},
        headers=_auth(token),
    )
    assert resp.status_code == 400


def test_assessment_over_limit(client, env):
    _, token = _register_and_verify(client, env)
    assets = [{"name": f"A{i}", "lat": float(i), "lon": float(i)} for i in range(26)]
    resp = client.post(
        "/api/v2/csrd/assessment",
        json={"company": {"name": "BigCo"}, "assets": assets},
        headers=_auth(token),
    )
    assert resp.status_code == 413, resp.get_json()
    assert resp.get_json()["upgrade"]["required_role"] == "subscriber"
