"""Session-aware CTA tests for the branded registry pages.

Design rule: the create-account / subscribe invitation on the human-facing
registry pages (/api/sources, /api/v2/hazards as text/html) is shown ONLY to
guests. A signed-in session must never see a registration or subscription
prompt — it sees a quiet link to its existing account instead.
"""

import email as email_lib
import os
import re

import pytest

os.environ["HYDRASHIELD_CACHE_DB"] = "/tmp/hydrashield_test_registry_cta_cache.sqlite3"
if os.path.exists(os.environ["HYDRASHIELD_CACHE_DB"]):
    os.remove(os.environ["HYDRASHIELD_CACHE_DB"])

from src.dashboard.api import create_app  # noqa: E402

GUEST_CTA = "Create an account / Subscribe"
ACCOUNT_LINK = "Open your account"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """Isolated DB + outbox per test."""
    db_path = tmp_path / "registry_cta.sqlite3"
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


def _register_and_verify(client, env, email="cta@example.org", password="correct horse battery"):
    resp = client.post(
        "/api/v2/auth/register",
        json={
            "email": email,
            "password": password,
            "display_name": "CTA Tester",
            "consent": True,
        },
    )
    assert resp.status_code == 201, resp.get_json()
    files = sorted(env["outbox"].glob("*_email_verification_*.eml"))
    assert files, "no verification email in outbox"
    msg = email_lib.message_from_string(files[-1].read_text(encoding="utf-8"))
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
    # The verify response sets the session cookie on the test client jar —
    # subsequent requests are authenticated.


def test_guest_sees_subscribe_cta_on_sources_page(client):
    resp = client.get("/api/sources", headers={"Accept": "text/html"})
    assert resp.status_code == 200
    assert resp.mimetype == "text/html"
    assert GUEST_CTA in resp.get_data(as_text=True)


def test_guest_sees_subscribe_cta_on_hazards_page(client):
    resp = client.get("/api/v2/hazards", headers={"Accept": "text/html"})
    assert resp.status_code == 200
    assert GUEST_CTA in resp.get_data(as_text=True)


def test_signed_in_user_never_sees_subscribe_cta(client, env):
    _register_and_verify(client, env)

    for path in ("/api/sources", "/api/v2/hazards"):
        resp = client.get(path, headers={"Accept": "text/html"})
        assert resp.status_code == 200, path
        html = resp.get_data(as_text=True)
        assert GUEST_CTA not in html, path
        assert "Create a free account and subscribe" not in html, path
        assert "Signed in as" in html, path
        assert "CTA Tester" in html, path
        assert ACCOUNT_LINK in html, path


def test_json_contract_unchanged_when_signed_in(client, env):
    _register_and_verify(client, env)
    resp = client.get("/api/sources", headers={"Accept": "application/json"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body and "sources" in body
