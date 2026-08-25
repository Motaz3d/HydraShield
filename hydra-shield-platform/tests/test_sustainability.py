"""Tests for the Sustainability & CSRD Reporting feature.

Fully offline: hazard modules are stubbed via monkeypatch + registry reset.
"""

import os

import pytest

os.environ["HYDRASHIELD_CACHE_DB"] = "/tmp/hydrashield_test_sustainability_cache.sqlite3"
if os.path.exists(os.environ["HYDRASHIELD_CACHE_DB"]):
    os.remove(os.environ["HYDRASHIELD_CACHE_DB"])

from src.climate import registry  # noqa: E402
from src.climate.hazards.base import HazardAnalysis, HazardLevel  # noqa: E402
from src.dashboard.api import create_app  # noqa: E402


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _fresh_registry(monkeypatch):
    """Drop the cached registry before/after each test."""
    registry.reset_for_tests()
    yield
    registry.reset_for_tests()


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """Isolated DB + outbox per test."""
    db_path = tmp_path / "sustainability.sqlite3"
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


# -----------------------------------------------------------------------------
# Stub hazard modules
# -----------------------------------------------------------------------------


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


class _FakeBoomModule:
    def __init__(self, hazard_id: str):
        self.id = hazard_id

    def availability(self):
        return True, None

    def analyze(self, lat, lon, name=None):
        raise ValueError("boom")


def _stub_registry(monkeypatch, ok=("flood",), boom=("wind",)):
    def fake_get(hazard_id: str):
        if hazard_id in ok:
            return _FakeOkModule(hazard_id)
        if hazard_id in boom:
            return _FakeBoomModule(hazard_id)
        return None

    monkeypatch.setattr(registry, "get", fake_get)


# -----------------------------------------------------------------------------
# Auth helpers
# -----------------------------------------------------------------------------


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
# Endpoint tests
# -----------------------------------------------------------------------------


def test_frameworks_public(client):
    resp = client.get("/api/v2/sustainability/frameworks")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["frameworks"]
    assert any("CSRD" in f.get("name", "") for f in data["frameworks"])
    assert any("SB 253" in f.get("name", "") for f in data["frameworks"])
    assert data["coverage_map"]
    assert any(c.get("coverage") == "not_covered" for c in data["coverage_map"])
    assert data["evidence_standard"]
    assert data["disclaimer"]


def test_report_unauthenticated(client):
    resp = client.post("/api/v2/sustainability/report", json={"company": {"name": "X"}, "assets": []})
    assert resp.status_code in (401, 403)


def test_report_authenticated(client, env, monkeypatch):
    _stub_registry(monkeypatch, ok=("flood", "heat"), boom=("wind",))
    user, token = _register_and_verify(client, env)

    payload = {
        "company": {
            "name": "Acme SA",
            "sector": "renewables",
            "country": "Luxembourg",
        },
        "assets": [
            {"name": "Trier", "lat": 49.75, "lon": 6.64},
            {"name": "A Coruña", "lat": 43.3, "lon": -8.4},
        ],
    }
    resp = client.post("/api/v2/sustainability/report", json=payload, headers=_auth(token))
    assert resp.status_code == 200, resp.get_json()
    data = resp.get_json()
    assert data["report_id"]
    assert data["generated_at"]
    assert data["company"]["declared_by_company"] is True
    assert data["company"]["fields"]["name"] == "Acme SA"
    assert len(data["coverage_map"]) >= 3
    assert len(data["site_results"]) == 2
    assert data["portfolio_summary"]["site_count"] == 2

    # Persisted record accessible to owner
    rid = data["report_id"]
    resp2 = client.get(f"/api/v2/sustainability/report/{rid}", headers=_auth(token))
    assert resp2.status_code == 200
    record = resp2.get_json()
    assert record["report_id"] == rid
    assert record["user_id"] == user["id"]
    assert record["payload"]["report_id"] == rid


def test_report_requires_company_name(client, env):
    _, token = _register_and_verify(client, env)
    resp = client.post(
        "/api/v2/sustainability/report",
        json={"company": {"sector": "x"}, "assets": [{"lat": 1, "lon": 2}]},
        headers=_auth(token),
    )
    assert resp.status_code == 400
    body = resp.get_json()
    assert "company.name" in body["error"]


def test_report_over_limit(client, env, monkeypatch):
    _stub_registry(monkeypatch, ok=("flood",))
    _, token = _register_and_verify(client, env)
    assets = [{"name": f"A{i}", "lat": float(i), "lon": float(i)} for i in range(26)]
    resp = client.post(
        "/api/v2/sustainability/report",
        json={"company": {"name": "BigCo"}, "assets": assets},
        headers=_auth(token),
    )
    assert resp.status_code == 413, resp.get_json()
    body = resp.get_json()
    assert body["upgrade"]["required_role"] == "subscriber"


def test_report_pdf(client, env, monkeypatch):
    pytest.importorskip("reportlab")
    _stub_registry(monkeypatch, ok=("flood",), boom=("wind",))
    _, token = _register_and_verify(client, env)
    payload = {
        "company": {"name": "PDFCo"},
        "assets": [{"name": "Site", "lat": 1, "lon": 2}],
    }
    resp = client.post("/api/v2/sustainability/report/pdf", json=payload, headers=_auth(token))
    assert resp.status_code == 200, resp.get_json() if not resp.ok else ""
    assert resp.mimetype == "application/pdf"
    assert resp.data[:5] == b"%PDF-"
    assert 'inline; filename="talaix_sustainability_PDFCo.pdf"' in resp.headers.get("Content-Disposition", "")


def test_report_unknown_id(client, env):
    _, token = _register_and_verify(client, env)
    resp = client.get("/api/v2/sustainability/report/nosuchid", headers=_auth(token))
    assert resp.status_code == 404


def test_report_other_user_denied(client, env, monkeypatch):
    _stub_registry(monkeypatch, ok=("flood",))
    user1, token1 = _register_and_verify(client, env, email="a@example.org")
    user2, token2 = _register_and_verify(client, env, email="b@example.org")

    payload = {"company": {"name": "PrivateCo"}, "assets": [{"lat": 1, "lon": 2}]}
    resp = client.post("/api/v2/sustainability/report", json=payload, headers=_auth(token1))
    assert resp.status_code == 200
    rid = resp.get_json()["report_id"]

    resp2 = client.get(f"/api/v2/sustainability/report/{rid}", headers=_auth(token2))
    assert resp2.status_code == 403
