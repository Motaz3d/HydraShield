"""Tests for the CsrdTX XBRL / iXBRL output.

Covers mapping↔taxonomy sync, never-invent fact emission, document
well-formedness, determinism, and the /api/v2/csrd/assessment/xbrl
endpoint. Fully offline.
"""

import os
import xml.etree.ElementTree as ET

import pytest

os.environ["HYDRASHIELD_CACHE_DB"] = "/tmp/hydrashield_test_csrd_xbrl_cache.sqlite3"
if os.path.exists(os.environ["HYDRASHIELD_CACHE_DB"]):
    os.remove(os.environ["HYDRASHIELD_CACHE_DB"])

from src.climate import registry  # noqa: E402
from src.climate.csrd.engine import build_csrd_assessment  # noqa: E402
from src.climate.csrd.xbrl import (  # noqa: E402
    build_ixbrl_document,
    build_xbrl_instance,
    collect_facts,
    load_mapping,
)
from src.climate.hazards.base import HazardAnalysis, HazardLevel  # noqa: E402
from src.dashboard.api import create_app  # noqa: E402

_XSD_PATH = os.path.join(
    os.path.dirname(__file__), "..", "website", "xbrl", "csrd", "2026", "talaix-csrd.xsd"
)


@pytest.fixture(autouse=True)
def _fresh_registry(monkeypatch):
    registry.reset_for_tests()
    yield
    registry.reset_for_tests()


@pytest.fixture()
def env(tmp_path, monkeypatch):
    db_path = tmp_path / "csrd_xbrl.sqlite3"
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
                label="High", score=0.8, score_max=1.0,
                basis="modelled screening indicator", validated=False,
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


def _register_and_verify(client, env, email="user@example.org", password="correct horse battery"):
    import email as email_lib
    import re

    resp = client.post(
        "/api/v2/auth/register",
        json={"email": email, "password": password, "display_name": "Test User", "consent": True},
    )
    assert resp.status_code == 201, resp.get_json()
    files = sorted(env["outbox"].glob("*_email_verification_*.eml"))
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
    token = re.search(r"token=([A-Za-z0-9_\-]+)", body).group(1)
    resp = client.get(f"/api/v2/auth/verify?token={token}")
    assert resp.status_code == 200, resp.get_json()
    return resp.get_json()["session_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _assessment(**overrides):
    company = {
        "name": "XbrlCo SA", "country": "Luxembourg", "sector": "manufacturing",
        "employees": 600, "net_turnover_eur": 90000000,
        "balance_sheet_total_eur": 40000000, "listed": False,
    }
    company.update(overrides)
    return build_csrd_assessment(company, verify_sites=False)


# -----------------------------------------------------------------------------
# Mapping ↔ served taxonomy sync
# -----------------------------------------------------------------------------


def test_served_taxonomy_matches_mapping():
    mapping = load_mapping()
    expected = {e["name"] for e in mapping["elements"]}
    tp = mapping["topic_elements"]
    for topic in tp["topics"]:
        for s in tp["suffixes"]:
            expected.add(tp["pattern"].replace("{ID}", topic).replace("{Suffix}", s["suffix"]))

    tree = ET.parse(_XSD_PATH)
    ns = {"xsd": "http://www.w3.org/2001/XMLSchema"}
    declared = {el.get("name") for el in tree.getroot().findall("xsd:element", ns)}
    assert declared == expected


# -----------------------------------------------------------------------------
# Fact collection — never invent
# -----------------------------------------------------------------------------


def test_missing_values_emit_no_fact_and_are_noted():
    assessment = build_csrd_assessment({"name": "SparseCo"}, verify_sites=False)
    facts, notes = collect_facts(assessment)
    names = {f["name"] for f in facts}
    assert "EntityName" in names
    assert "Employees" not in names
    assert "NetTurnoverEUR" not in names
    assert any("Employees" in n for n in notes)
    # No site data → E1 not assessed → no topic facts at all.
    assert not any(n.startswith("Topic") for n in names)
    assert any("E1" in n for n in notes)


def test_fact_types_rendered():
    facts, _ = collect_facts(_assessment())
    by_name = {f["name"]: f for f in facts}
    assert by_name["Employees"]["value"] == "600"
    assert by_name["Employees"]["unit"] == "u-pure"
    assert by_name["NetTurnoverEUR"]["value"] == "90000000"
    assert by_name["NetTurnoverEUR"]["unit"] == "u-eur"
    assert by_name["Listed"]["value"] == "false"
    assert by_name["ApplicabilityDetermination"]["value"] == "in_scope"
    assert by_name["ReportingYear"]["value"].isdigit()


# -----------------------------------------------------------------------------
# Instance document
# -----------------------------------------------------------------------------


def test_instance_well_formed():
    doc = build_xbrl_instance(_assessment())
    root = ET.fromstring(doc)
    assert root.tag == "{http://www.xbrl.org/2003/instance}xbrl"
    ns_uri = load_mapping()["namespace"]
    name_fact = root.find(f"{{{ns_uri}}}EntityName")
    assert name_fact is not None and name_fact.text == "XbrlCo SA"
    employees = root.find(f"{{{ns_uri}}}Employees")
    assert employees.get("unitRef") == "u-pure"
    assert employees.get("decimals") is not None
    turnover = root.find(f"{{{ns_uri}}}NetTurnoverEUR")
    assert turnover.get("unitRef") == "u-eur"


def test_instance_declares_taxonomy_ref_and_units():
    doc = build_xbrl_instance(_assessment())
    assert load_mapping()["taxonomy_url"] in doc
    assert "iso4217:EUR" in doc
    assert "xbrli:pure" in doc


def test_instance_deterministic():
    assessment = _assessment()
    a = build_xbrl_instance(assessment)
    b = build_xbrl_instance(assessment)
    assert a == b


def test_lei_becomes_entity_identifier():
    doc = build_xbrl_instance(_assessment(lei="529900T8BM49AURSDO55"))
    assert "http://standards.iso.org/iso/17442" in doc
    assert "529900T8BM49AURSDO55" in doc


def test_ixbrl_well_formed_and_tagged():
    doc = build_ixbrl_document(_assessment())
    assert "ix:header" in doc
    assert "ix:nonFraction" in doc
    assert "ix:nonNumeric" in doc
    ET.fromstring(doc)  # must parse as XML


# -----------------------------------------------------------------------------
# API endpoint
# -----------------------------------------------------------------------------


def test_xbrl_unauthenticated(client):
    resp = client.post("/api/v2/csrd/assessment/xbrl", json={"company": {"name": "X"}})
    assert resp.status_code in (401, 403)


def test_xbrl_download(client, env, monkeypatch):
    _stub_registry(monkeypatch, ok=("flood", "heat"))
    token = _register_and_verify(client, env)
    resp = client.post(
        "/api/v2/csrd/assessment/xbrl",
        json={
            "company": {"name": "Acme SA", "country": "Luxembourg", "employees": 600,
                        "net_turnover_eur": 90000000, "balance_sheet_total_eur": 40000000},
            "assets": [{"name": "Trier", "lat": 49.75, "lon": 6.64}],
        },
        headers=_auth(token),
    )
    assert resp.status_code == 200
    assert resp.mimetype == "application/xml"
    assert "talaix_csrd_Acme_SA.xbrl" in resp.headers.get("Content-Disposition", "")
    root = ET.fromstring(resp.data.decode("utf-8"))
    ns_uri = load_mapping()["namespace"]
    # E1 was seeded from the stubbed site verification → topic facts exist.
    assert root.find(f"{{{ns_uri}}}TopicE1CombinedScore") is not None
    assert root.find(f"{{{ns_uri}}}TopicE1Material") is not None


def test_ixbrl_download(client, env):
    token = _register_and_verify(client, env)
    resp = client.post(
        "/api/v2/csrd/assessment/xbrl",
        json={"company": {"name": "Acme SA"}, "format": "ixbrl"},
        headers=_auth(token),
    )
    assert resp.status_code == 200
    assert resp.mimetype == "application/xhtml+xml"
    assert b"ix:nonNumeric" in resp.data


def test_xbrl_bad_format(client, env):
    token = _register_and_verify(client, env)
    resp = client.post(
        "/api/v2/csrd/assessment/xbrl",
        json={"company": {"name": "Acme SA"}, "format": "pdf"},
        headers=_auth(token),
    )
    assert resp.status_code == 400


def test_xbrl_over_limit(client, env):
    token = _register_and_verify(client, env)
    assets = [{"name": f"A{i}", "lat": float(i), "lon": float(i)} for i in range(26)]
    resp = client.post(
        "/api/v2/csrd/assessment/xbrl",
        json={"company": {"name": "BigCo"}, "assets": assets},
        headers=_auth(token),
    )
    assert resp.status_code == 413
