"""Tests for the Insurance & Environmental Risk feature.

Fully offline: hazard modules are stubbed via monkeypatch + registry reset.
"""

import os

import pytest

os.environ["HYDRASHIELD_CACHE_DB"] = "/tmp/hydrashield_test_insurance_cache.sqlite3"
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
    db_path = tmp_path / "insurance.sqlite3"
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
# Stub hazard modules with analyze() + events()
# -----------------------------------------------------------------------------


class _FakeOkEventsModule:
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

    def events(self, lat, lon, radius_km=50.0, year=None):
        return {
            "hazard": self.id,
            "status": "ok",
            "events": [
                {"id": "ev1", "date": "2020-06-15", "name": "Big event", "severity": "high"},
                {"id": "ev2", "date": "2019-07-22", "name": "Small event"},
            ],
        }

    def temporal_coverage(self):
        return {"default": {"start": "2000-01-01", "end": "2024-12-31"}}


class _FakeOkNoEventsModule:
    """Current level works, but events() raises — exercises declared events gap."""

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
                label="Moderate",
                score=0.5,
                score_max=1.0,
                basis="modelled screening indicator",
                validated=False,
            ),
            evidence=[{
                "evidence_class": "MODELLED",
                "claim_status": "MODELLED",
                "temporal": "OBSERVED",
                "source": "Fake source",
            }],
            provenance={"model": {"source": "Fake"}},
        )

    def events(self, lat, lon, radius_km=50.0, year=None):
        raise ValueError("events database offline")


def _stub_registry(monkeypatch):
    def fake_get(hazard_id: str):
        if hazard_id == "flood":
            return _FakeOkEventsModule(hazard_id)
        if hazard_id == "wind":
            return _FakeOkNoEventsModule(hazard_id)
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


def test_profile_requires_params(client):
    resp = client.get("/api/v2/insurance/profile")
    assert resp.status_code == 400


def test_profile_rejects_bad_coords_and_radius(client, monkeypatch):
    _stub_registry(monkeypatch)
    assert client.get("/api/v2/insurance/profile?lat=abc&lon=0&radius_km=50").status_code == 400
    assert client.get("/api/v2/insurance/profile?lat=10&lon=0&radius_km=0").status_code == 400
    assert client.get("/api/v2/insurance/profile?lat=10&lon=0&radius_km=9999").status_code == 400


def test_profile_with_stubs(client, monkeypatch):
    _stub_registry(monkeypatch)
    resp = client.get("/api/v2/insurance/profile?lat=1.0&lon=2.0&name=Asset&radius_km=25")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["profile_id"]
    assert data["loss_quantification"] == "not_quantified"
    assert data["disclaimer"]
    assert data["exposure_summary"]

    perils = {p["hazard"]: p for p in data["perils"]}
    assert "flood" in perils
    assert perils["flood"]["claim_status"] == "MODELLED"
    assert perils["flood"]["events_status"] == "ok"
    assert perils["flood"]["events_count"] == 2
    assert len(perils["flood"]["events_summary"]) == 2
    assert perils["flood"]["temporal_coverage"]

    assert "wind" in perils
    assert perils["wind"]["claim_status"] == "MODELLED"
    assert perils["wind"]["events_status"] == "unavailable"
    assert any(g["hazard"] == "wind" and g["type"] == "events" for g in data["declared_gaps"])


def test_portfolio_unauthenticated(client):
    resp = client.post("/api/v2/insurance/portfolio", json={"assets": []})
    assert resp.status_code in (401, 403)


def test_portfolio_authenticated(client, env, monkeypatch):
    _stub_registry(monkeypatch)
    user, token = _register_and_verify(client, env)

    payload = {
        "name": "Test portfolio",
        "assets": [
            {"name": "A", "lat": 1.0, "lon": 2.0},
            {"name": "B", "lat": 3.0, "lon": 4.0},
        ],
        "radius_km": 25,
    }
    resp = client.post("/api/v2/insurance/portfolio", json=payload, headers=_auth(token))
    assert resp.status_code == 200, resp.get_json()
    data = resp.get_json()
    assert data["portfolio_id"]
    assert data["count"] == 2
    assert data["ok_count"] == 2
    assert "level_distribution" in data["portfolio_summary"]
    assert len(data["results"]) == 2

    pid = data["portfolio_id"]
    resp2 = client.get(f"/api/v2/insurance/portfolio/{pid}", headers=_auth(token))
    assert resp2.status_code == 200
    record = resp2.get_json()
    assert record["portfolio_id"] == pid
    assert record["user_id"] == user["id"]


def test_portfolio_unknown_id(client, env):
    _, token = _register_and_verify(client, env)
    resp = client.get("/api/v2/insurance/portfolio/nosuchid", headers=_auth(token))
    assert resp.status_code == 404


def test_portfolio_over_limit(client, env, monkeypatch):
    _stub_registry(monkeypatch)
    _, token = _register_and_verify(client, env)
    assets = [{"name": f"A{i}", "lat": float(i), "lon": float(i)} for i in range(26)]
    resp = client.post(
        "/api/v2/insurance/portfolio",
        json={"assets": assets, "radius_km": 50},
        headers=_auth(token),
    )
    assert resp.status_code == 413, resp.get_json()
    body = resp.get_json()
    assert body["upgrade"]["required_role"] == "subscriber"


def test_profile_report_pdf(client, monkeypatch):
    pytest.importorskip("reportlab")
    _stub_registry(monkeypatch)
    resp = client.get("/api/v2/insurance/profile/report?lat=1.0&lon=2.0&name=Asset&radius_km=25")
    assert resp.status_code == 200
    assert resp.mimetype == "application/pdf"
    assert resp.data[:5] == b"%PDF-"
    assert 'inline; filename="talaix_insurance_Asset.pdf"' in resp.headers.get("Content-Disposition", "")
