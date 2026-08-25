"""Tests for the Green Finance Verification feature.

Fully offline: hazard modules are stubbed via monkeypatch + registry reset,
so no network calls are made.
"""

import os

import pytest

os.environ["HYDRASHIELD_CACHE_DB"] = "/tmp/hydrashield_test_verification_cache.sqlite3"
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
    """Isolated DB + outbox per test; dev email backend guaranteed."""
    db_path = tmp_path / "verification.sqlite3"
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


class _FakeUnavailableModule:
    def __init__(self, hazard_id: str):
        self.id = hazard_id

    def availability(self):
        return False, "No real data for this hazard"

    def analyze(self, lat, lon, name=None):
        return HazardAnalysis(
            hazard=self.id,
            location={"lat": lat, "lon": lon, "name": name},
            status="unavailable",
            summary=f"{self.id} unavailable",
            unavailable_reason="No real data for this hazard",
        )


def _stub_registry(monkeypatch, ok=("flood",), boom=("wind",), unavailable=()):
    def fake_get(hazard_id: str):
        if hazard_id in ok:
            return _FakeOkModule(hazard_id)
        if hazard_id in boom:
            return _FakeBoomModule(hazard_id)
        if hazard_id in unavailable:
            return _FakeUnavailableModule(hazard_id)
        return None

    monkeypatch.setattr(registry, "get", fake_get)


# -----------------------------------------------------------------------------
# Auth helpers (mirroring tests/test_accounts.py)
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


def test_asset_requires_params(client):
    resp = client.get("/api/v2/verification/asset")
    assert resp.status_code == 400
    body = resp.get_json()
    assert "error" in body
    assert body["status"] == 400


def test_asset_rejects_bad_coords(client):
    resp = client.get("/api/v2/verification/asset?lat=abc&lon=6")
    assert resp.status_code == 400
    resp = client.get("/api/v2/verification/asset?lat=95&lon=6")
    assert resp.status_code == 400


def test_asset_with_stubs(client, monkeypatch):
    _stub_registry(monkeypatch, ok=("flood",), boom=("wind",))
    resp = client.get("/api/v2/verification/asset?lat=1.0&lon=2.0&name=Test")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "verification_id" in data
    assert data["disclaimer"]
    assert data["honesty_contract"]

    checks = {c["hazard"]: c for c in data["hazard_checks"]}
    assert "flood" in checks
    assert checks["flood"]["claim_status"] == "MODELLED"
    assert checks["flood"]["confidence"] == "medium"
    assert checks["flood"]["level"]["label"] == "High"

    assert "wind" in checks
    assert checks["wind"]["claim_status"] == "UNKNOWN"
    assert checks["wind"]["confidence"] == "low"

    assert any(g["hazard"] == "wind" for g in data["declared_gaps"])
    assert len(data["declared_gaps"]) >= 1


def test_portfolio_unauthenticated(client):
    resp = client.post("/api/v2/verification/portfolio", json={"assets": []})
    assert resp.status_code in (401, 403)


def test_portfolio_authenticated(client, env, monkeypatch):
    _stub_registry(monkeypatch, ok=("flood", "heat"), boom=("wind",))
    user, token = _register_and_verify(client, env)

    payload = {
        "name": "Test portfolio",
        "assets": [
            {"name": "A", "lat": 1.0, "lon": 2.0},
            {"name": "B", "lat": 3.0, "lon": 4.0},
            {"name": "Bad", "lat": 999.0, "lon": 0.0},
        ],
    }
    resp = client.post("/api/v2/verification/portfolio", json=payload, headers=_auth(token))
    assert resp.status_code == 200, resp.get_json()
    data = resp.get_json()
    assert data["count"] == 3
    assert data["ok_count"] == 2
    assert data["portfolio_id"]
    assert len(data["results"]) == 3
    assert data["results"][0]["ok"] is True
    assert data["results"][2]["ok"] is False
    assert data["results"][0]["verification_id"]

    # Owner can fetch the full record
    pid = data["portfolio_id"]
    resp2 = client.get(f"/api/v2/verification/portfolio/{pid}", headers=_auth(token))
    assert resp2.status_code == 200
    full = resp2.get_json()
    assert full["portfolio_id"] == pid
    assert full["user_id"] == user["id"]
    assert full["name"] == "Test portfolio"
    assert len(full["results"]) == 3


def test_portfolio_unknown_id(client, env):
    _, token = _register_and_verify(client, env)
    resp = client.get("/api/v2/verification/portfolio/nosuchid", headers=_auth(token))
    assert resp.status_code == 404
    body = resp.get_json()
    assert "error" in body
    assert body["status"] == 404


def test_portfolio_over_limit(client, env, monkeypatch):
    _stub_registry(monkeypatch, ok=("flood",))
    _, token = _register_and_verify(client, env)

    assets = [{"name": f"A{i}", "lat": float(i), "lon": float(i)} for i in range(26)]
    resp = client.post(
        "/api/v2/verification/portfolio",
        json={"assets": assets},
        headers=_auth(token),
    )
    assert resp.status_code == 413, resp.get_json()
    body = resp.get_json()
    assert "upgrade" in body
    assert body["upgrade"]["required_role"] == "subscriber"


def test_report_endpoint_returns_pdf(client, monkeypatch):
    pytest.importorskip("reportlab")
    _stub_registry(monkeypatch, ok=("flood",), boom=("wind",))
    resp = client.get("/api/v2/verification/report?lat=1.0&lon=2.0&name=Test")
    assert resp.status_code == 200
    assert resp.mimetype == "application/pdf"
    assert resp.data[:5] == b"%PDF-"
    assert 'inline; filename="talaix_verification_Test.pdf"' in resp.headers.get("Content-Disposition", "")
