"""Tests for the Talaix Knowledge Arm (public briefs API).

Uses the real config JSON registry and verifies read-only endpoints,
honest 404s, light list payloads and sourcing discipline.
"""

import json
import os

import pytest

os.environ["HYDRASHIELD_CACHE_DB"] = "/tmp/hydrashield_test_briefs_cache.sqlite3"
if os.path.exists(os.environ["HYDRASHIELD_CACHE_DB"]):
    os.remove(os.environ["HYDRASHIELD_CACHE_DB"])

from src.climate.briefs import load_briefs  # noqa: E402
from src.dashboard.api import create_app  # noqa: E402


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """Isolated DB + outbox per test."""
    db_path = tmp_path / "briefs.sqlite3"
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


@pytest.fixture()
def registry():
    return load_briefs()


# -----------------------------------------------------------------------------
# Endpoint tests
# -----------------------------------------------------------------------------


def test_list_briefs(client, registry):
    resp = client.get("/api/v2/briefs")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "briefs" in data
    assert "note" in data
    assert len(data["briefs"]) >= 2

    # Entries are light and sorted by date descending.
    prev_date = None
    for b in data["briefs"]:
        assert "id" in b
        assert "kind" in b
        assert "title" in b
        assert "date" in b
        assert "summary" in b
        assert "source_count" in b
        assert "sections" not in b
        if prev_date is not None:
            assert b["date"] <= prev_date
        prev_date = b["date"]


def test_list_briefs_kind_filter(client, registry):
    resp = client.get("/api/v2/briefs?kind=framework_explainer")
    assert resp.status_code == 200
    data = resp.get_json()
    assert all(b["kind"] == "framework_explainer" for b in data["briefs"])
    assert any(b["id"] == "explainer-eu-taxonomy-dnsh-adaptation" for b in data["briefs"])

    resp_evidence = client.get("/api/v2/briefs?kind=evidence_brief")
    assert resp_evidence.status_code == 200
    evidence = resp_evidence.get_json()["briefs"]
    assert all(b["kind"] == "evidence_brief" for b in evidence)


def test_get_framework_explainer(client):
    resp = client.get("/api/v2/briefs/explainer-eu-taxonomy-dnsh-adaptation")
    assert resp.status_code == 200
    brief = resp.get_json()["brief"]
    assert brief["id"] == "explainer-eu-taxonomy-dnsh-adaptation"
    assert brief["kind"] == "framework_explainer"
    assert len(brief.get("sections", [])) > 0

    sources = brief.get("sources", [])
    assert sources
    for s in sources:
        assert s.get("name")
        assert s.get("url")
        assert s.get("claim_status") in {"REPORTED", "DOCUMENTED"}
    assert any(s["claim_status"] == "DOCUMENTED" for s in sources)


def test_get_evidence_brief(client):
    resp = client.get("/api/v2/briefs/evidence-brief-2026-08-pilot")
    assert resp.status_code == 200
    brief = resp.get_json()["brief"]
    assert brief["id"] == "evidence-brief-2026-08-pilot"
    assert brief["kind"] == "evidence_brief"
    assert len(brief.get("sections", [])) > 0

    sources = brief.get("sources", [])
    assert sources
    assert any(s["claim_status"] == "REPORTED" for s in sources)


def test_unknown_brief(client):
    resp = client.get("/api/v2/briefs/nosuchbrief")
    assert resp.status_code == 404
    assert "error" in resp.get_json()


# -----------------------------------------------------------------------------
# Honesty structural test
# -----------------------------------------------------------------------------


def test_registry_sources_are_honest(registry):
    """Every published brief must have open, labelled sources."""
    published = [b for b in registry.get("briefs", []) if b.get("status") == "published"]
    assert published, "expected at least one published brief"

    allowed_statuses = {"REPORTED", "DOCUMENTED"}
    for brief in published:
        sources = brief.get("sources")
        assert sources, f"{brief['id']}: published brief has no sources"
        for s in sources:
            assert s.get("url"), f"{brief['id']}: source missing url"
            assert s.get("claim_status") in allowed_statuses, (
                f"{brief['id']}: invalid claim_status {s.get('claim_status')}"
            )
