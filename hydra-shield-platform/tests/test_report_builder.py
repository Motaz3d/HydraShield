"""Tests for the Visual Report Builder.

Stubs the hazard registry so the engine payloads are deterministic and fast;
PDF tests skip when reportlab is unavailable.
"""

import email as email_lib
import os
import re
from types import SimpleNamespace

import pytest

os.environ["HYDRASHIELD_CACHE_DB"] = "/tmp/hydrashield_test_report_builder_cache.sqlite3"
if os.path.exists(os.environ["HYDRASHIELD_CACHE_DB"]):
    os.remove(os.environ["HYDRASHIELD_CACHE_DB"])

from src.climate.insurance import INSURANCE_PERILS  # noqa: E402
from src.climate.report_builder import prepare_sections  # noqa: E402
from src.climate.verification import VERIFICATION_HAZARDS  # noqa: E402
from src.dashboard.api import create_app  # noqa: E402


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """Isolated DB + outbox per test."""
    db_path = tmp_path / "report_builder.sqlite3"
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


class _StubLevel:
    def __init__(self, label="Low", validated=False, basis="modelled indicator"):
        self.label = label
        self.validated = validated
        self.basis = basis

    def to_dict(self):
        return {"label": self.label, "validated": self.validated, "basis": self.basis}


class _StubModule:
    def __init__(self, hazard_id: str):
        self.id = hazard_id

    def availability(self):
        return True, None

    def analyze(self, lat, lon, name=None):
        return SimpleNamespace(
            status="ok",
            level=_StubLevel(label="Low", validated=False, basis=f"{self.id} model basis"),
            summary=f"{self.id} hazard summary for the asset.",
            evidence=[{"evidence_id": "ev-1", "claim_status": "MODELLED"}],
            unavailable_reason=None,
        )

    def events(self, lat, lon, radius_km=50.0):
        return {
            "status": "ok",
            "events": [{"id": "evt-1", "date": "2020-06-01"}],
        }

    def temporal_coverage(self):
        return {"start": "2000-01-01", "end": "2024-12-31"}


@pytest.fixture()
def stub_registry(env, monkeypatch):
    """Replace the hazard registry with deterministic stubs."""
    import src.climate.registry as registry_mod

    registry_mod.reset_for_tests()
    hazard_ids = set(VERIFICATION_HAZARDS.keys()) | set(INSURANCE_PERILS.keys())
    stubs = {hazard_id: _StubModule(hazard_id) for hazard_id in hazard_ids}
    monkeypatch.setattr(registry_mod, "_modules", stubs)
    return stubs


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


def test_draft_requires_auth(client):
    resp = client.post("/api/v2/report-builder/draft", json={
        "kind": "verification",
        "params": {"lat": 49.6116, "lon": 6.1319},
    })
    assert resp.status_code in (401, 403)


def test_draft_verification(client, env, stub_registry):
    user, token = _register_and_verify(client, env)
    resp = client.post("/api/v2/report-builder/draft", json={
        "kind": "verification",
        "params": {"lat": 49.6116, "lon": 6.1319, "name": "Test site"},
    }, headers=_auth(token))
    assert resp.status_code == 200, resp.get_json()

    draft = resp.get_json()["draft"]
    assert draft["kind"] == "verification"
    assert draft["draft_id"]
    assert draft["title"]
    assert draft["interconnection_note"]
    assert draft["honesty_note"]

    kinds = [s["kind"] for s in draft["sections"]]
    assert "introduction" in kinds
    assert "gaps" in kinds
    assert "conclusion" in kinds
    body_count = sum(1 for s in draft["sections"] if s["kind"] == "body")
    assert body_count == len(VERIFICATION_HAZARDS)

    for s in draft["sections"]:
        assert s["heading"]
        assert s["text"]
        assert s["why"]
        assert isinstance(s["source_refs"], list)
        assert s["edited"] is False


def test_draft_insurance(client, env, stub_registry):
    user, token = _register_and_verify(client, env)
    resp = client.post("/api/v2/report-builder/draft", json={
        "kind": "insurance",
        "params": {"lat": 49.6116, "lon": 6.1319, "name": "Test site", "radius_km": 25},
    }, headers=_auth(token))
    assert resp.status_code == 200, resp.get_json()
    draft = resp.get_json()["draft"]
    assert draft["kind"] == "insurance"
    body_count = sum(1 for s in draft["sections"] if s["kind"] == "body")
    assert body_count == len(INSURANCE_PERILS)


def test_draft_sustainability(client, env, stub_registry):
    user, token = _register_and_verify(client, env)
    resp = client.post("/api/v2/report-builder/draft", json={
        "kind": "sustainability",
        "params": {
            "company": {"name": "Acme SA", "sector": "Manufacturing"},
            "assets": [{"name": "HQ", "lat": 49.6116, "lon": 6.1319}],
        },
    }, headers=_auth(token))
    assert resp.status_code == 200, resp.get_json()
    draft = resp.get_json()["draft"]
    assert draft["kind"] == "sustainability"

    headings = [s["heading"] for s in draft["sections"]]
    assert any("Disclosure coverage map" in h for h in headings)
    assert any(h.startswith("Site:") for h in headings)


def test_draft_invalid_kind(client, env):
    user, token = _register_and_verify(client, env)
    resp = client.post("/api/v2/report-builder/draft", json={
        "kind": "not_a_kind",
        "params": {"lat": 49.6116, "lon": 6.1319},
    }, headers=_auth(token))
    assert resp.status_code == 400
    assert "allowed_kinds" in resp.get_json()


# -----------------------------------------------------------------------------
# Section preparation tests
# -----------------------------------------------------------------------------


def test_prepare_sections_cleans_and_counts_edits():
    sections = [
        {"heading": "Intro", "text": "Hello", "kind": "introduction", "edited": False, "source_refs": ["a"]},
        {"heading": "", "text": "", "kind": "body"},
        {"heading": "Body", "text": "Changed", "kind": "body", "edited": True},
        {"heading": "Empty body", "text": "   ", "kind": "body"},
    ]
    cleaned, edited_count = prepare_sections(sections)
    assert len(cleaned) == 2
    assert edited_count == 1
    assert cleaned[0]["edited"] is False
    assert cleaned[1]["edited"] is True


def test_prepare_sections_enforces_limits():
    with pytest.raises(ValueError, match="heading"):
        prepare_sections([{"heading": "x" * 201, "text": "body"}])
    with pytest.raises(ValueError, match="text"):
        prepare_sections([{"heading": "OK", "text": "x" * 5001}])
    with pytest.raises(ValueError, match="60"):
        prepare_sections([{"heading": "s", "text": "t"} for _ in range(61)])
    with pytest.raises(ValueError, match="kind"):
        prepare_sections([{"heading": "s", "text": "t", "kind": "invalid"}])


# -----------------------------------------------------------------------------
# PDF export tests
# -----------------------------------------------------------------------------


def test_pdf_malformed_section(client, env):
    pytest.importorskip("reportlab")
    user, token = _register_and_verify(client, env)
    resp = client.post("/api/v2/report-builder/pdf", json={
        "title": "Test",
        "sections": [{"text": "missing heading"}],
        "draft_id": "abc",
        "generated_at": "2026-08-25T00:00:00Z",
        "kind": "verification",
        "engine_version": "1.0.0",
    }, headers=_auth(token))
    assert resp.status_code == 400


def test_pdf_over_limit_sections(client, env):
    user, token = _register_and_verify(client, env)
    sections = [{"heading": f"s{i}", "text": "t"} for i in range(61)]
    resp = client.post("/api/v2/report-builder/pdf", json={
        "title": "Test",
        "sections": sections,
        "draft_id": "abc",
        "generated_at": "2026-08-25T00:00:00Z",
        "kind": "verification",
        "engine_version": "1.0.0",
    }, headers=_auth(token))
    assert resp.status_code == 400


def test_pdf_with_edited_section(client, env):
    pytest.importorskip("reportlab")
    user, token = _register_and_verify(client, env)
    resp = client.post("/api/v2/report-builder/pdf", json={
        "title": "Edited Report",
        "sections": [
            {"heading": "Introduction", "text": "Original intro.", "kind": "introduction", "edited": False},
            {"heading": "Body", "text": "User changed this.", "kind": "body", "edited": True},
            {"heading": "Conclusion", "text": "The end.", "kind": "conclusion", "edited": False},
        ],
        "draft_id": "abc123",
        "generated_at": "2026-08-25T00:00:00Z",
        "kind": "verification",
        "engine_version": "1.0.0",
        "honesty_note": "Engine text only.",
        "disclaimer": "Not advice.",
    }, headers=_auth(token))
    assert resp.status_code == 200
    assert resp.mimetype == "application/pdf"
    assert resp.data[:5] == b"%PDF-"
