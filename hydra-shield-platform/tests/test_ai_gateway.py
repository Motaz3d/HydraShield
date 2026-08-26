"""Tests for the AI gateway and Report Builder AI-polish integration."""

from __future__ import annotations

import email as email_lib
import io
import os
import re
from typing import Any, Dict

import pytest

os.environ["HYDRASHIELD_CACHE_DB"] = "/tmp/hydrashield_test_ai_gateway_cache.sqlite3"
if os.path.exists(os.environ["HYDRASHIELD_CACHE_DB"]):
    os.remove(os.environ["HYDRASHIELD_CACHE_DB"])

from src.ai import gateway  # noqa: E402
from src.climate.report_builder import prepare_sections  # noqa: E402
from src.dashboard.api import create_app  # noqa: E402


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_gateway_db(monkeypatch):
    """Reset the shared cache instance so every test gets a fresh database."""
    import src.dashboard.cache as cache_mod
    import src.dashboard.api as api_module

    monkeypatch.setattr(cache_mod, "_default_cache", None)
    api_module._rate_limiter._hits.clear()


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """Isolated DB + outbox per test."""
    db_path = tmp_path / "ai_gateway.sqlite3"
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
# Helpers
# -----------------------------------------------------------------------------


def _ok_response(text: str = "polished text", prompt_tokens: int = 10, completion_tokens: int = 5) -> Dict[str, Any]:
    return {
        "choices": [{"message": {"content": text}}],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
        },
    }


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
# Gateway unit tests
# -----------------------------------------------------------------------------


def test_configured_false_when_key_missing(monkeypatch):
    monkeypatch.delenv("KIMI_API_KEY", raising=False)
    assert gateway.configured() is False


def test_complete_raises_when_not_configured(monkeypatch):
    monkeypatch.delenv("KIMI_API_KEY", raising=False)
    with pytest.raises(gateway.AIUnavailable):
        gateway.complete("polish", "some text")


def test_tier_routing_uses_cheap_model_for_polish(monkeypatch):
    monkeypatch.setenv("KIMI_API_KEY", "test-key")
    captured: Dict[str, Any] = {}

    def fake_post(url, headers, payload, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["payload"] = payload
        return _ok_response("polished")

    monkeypatch.setattr(gateway, "_post", fake_post)

    result = gateway.complete("polish", "draft prose")
    assert result == "polished"
    assert captured["payload"]["model"] == "kimi-for-coding"
    assert captured["headers"]["Authorization"] == "Bearer test-key"


def test_tier_routing_uses_deep_model_for_deep_analysis(monkeypatch):
    monkeypatch.setenv("KIMI_API_KEY", "test-key")
    captured: Dict[str, Any] = {}

    def fake_post(url, headers, payload, timeout):
        captured["payload"] = payload
        return _ok_response("analysis")

    monkeypatch.setattr(gateway, "_post", fake_post)
    gateway.complete("deep_analysis", "long prompt")
    assert captured["payload"]["model"] == "k3-256k"


def test_unknown_task_kind_raises(monkeypatch):
    monkeypatch.setenv("KIMI_API_KEY", "test-key")
    with pytest.raises(gateway.AIUnavailable, match="unknown task kind"):
        gateway.complete("not_a_task", "text")


def test_daily_cap_blocks_calls(monkeypatch, env):
    monkeypatch.setenv("KIMI_API_KEY", "test-key")
    monkeypatch.setenv("AI_DAILY_CALL_CAP", "2")
    monkeypatch.setattr(gateway, "_post", lambda *a, **k: _ok_response())

    gateway.complete("polish", "one")
    gateway.complete("polish", "two")
    with pytest.raises(gateway.AIUnavailable, match="cap reached"):
        gateway.complete("polish", "three")


def test_non_200_error_does_not_leak_key(monkeypatch, env):
    monkeypatch.setenv("KIMI_API_KEY", "super-secret-key-123")

    def fake_post(*args, **kwargs):
        raise gateway.AIUnavailable("upstream returned HTTP 401")

    monkeypatch.setattr(gateway, "_post", fake_post)

    with pytest.raises(gateway.AIUnavailable) as exc_info:
        gateway.complete("polish", "text")
    message = str(exc_info.value)
    assert "super-secret-key-123" not in message
    assert "401" in message


def test_usage_is_logged(monkeypatch, env):
    monkeypatch.setenv("KIMI_API_KEY", "test-key")
    monkeypatch.setattr(
        gateway,
        "_post",
        lambda *a, **k: _ok_response("result", prompt_tokens=12, completion_tokens=7),
    )

    before = gateway.calls_today()
    gateway.complete("polish", "polish this")
    after = gateway.calls_today()

    assert after == before + 1


# -----------------------------------------------------------------------------
# Report Builder integration tests
# -----------------------------------------------------------------------------


def test_polish_endpoint_requires_auth(client):
    resp = client.post("/api/v2/report-builder/polish", json={"text": "hello"})
    assert resp.status_code in (401, 403)


def test_polish_endpoint_returns_503_when_not_configured(client, env, monkeypatch):
    monkeypatch.delenv("KIMI_API_KEY", raising=False)
    user, token = _register_and_verify(client, env)
    resp = client.post(
        "/api/v2/report-builder/polish",
        json={"heading": "H", "text": "hello"},
        headers=_auth(token),
    )
    assert resp.status_code == 503
    assert "not configured" in resp.get_json()["error"].lower()


def test_polish_endpoint_polishes_text(client, env, monkeypatch):
    monkeypatch.setenv("KIMI_API_KEY", "test-key")
    monkeypatch.setattr(
        gateway,
        "_post",
        lambda *a, **k: _ok_response("Polished result."),
    )
    user, token = _register_and_verify(client, env)
    resp = client.post(
        "/api/v2/report-builder/polish",
        json={"heading": "Introduction", "text": "this is draft text"},
        headers=_auth(token),
    )
    assert resp.status_code == 200
    assert resp.get_json()["text"] == "Polished result."


def test_polish_endpoint_validates_empty_text(client, env, monkeypatch):
    monkeypatch.setenv("KIMI_API_KEY", "test-key")
    user, token = _register_and_verify(client, env)
    resp = client.post(
        "/api/v2/report-builder/polish",
        json={"heading": "Introduction", "text": "   "},
        headers=_auth(token),
    )
    assert resp.status_code == 400


def test_prepare_sections_preserves_ai_polished():
    sections = [
        {"heading": "Intro", "text": "Hello", "kind": "introduction", "edited": False, "ai_polished": True},
        {"heading": "Body", "text": "Changed", "kind": "body", "edited": True, "ai_polished": False},
    ]
    cleaned, edited_count = prepare_sections(sections)
    assert cleaned[0]["ai_polished"] is True
    assert cleaned[1]["ai_polished"] is False
    assert cleaned[0]["edited"] is False
    assert edited_count == 1


def test_pdf_renders_ai_polished_marker(client, env):
    pypdf = pytest.importorskip("pypdf")
    reportlab = pytest.importorskip("reportlab")
    user, token = _register_and_verify(client, env)
    resp = client.post("/api/v2/report-builder/pdf", json={
        "title": "AI Polish Report",
        "sections": [
            {"heading": "Introduction", "text": "Original intro.", "kind": "introduction", "edited": False, "ai_polished": False},
            {"heading": "Body", "text": "Polished by AI.", "kind": "body", "edited": True, "ai_polished": True},
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

    reader = pypdf.PdfReader(io.BytesIO(resp.data))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert "[AI-polished]" in text
    assert "[edited by user]" in text


