"""
Tests for the self-service subscription system (recorded, never charged —
docs/USER_AND_SUBSCRIPTION_ARCHITECTURE.md §7).

Covers: initial state, activation (role promotion + confirmation email +
audit), idempotency of subscribe/unsubscribe, the subscriber tier actually
unlocking API-key creation, cancellation restoring the free tier, operator
roles never being demoted, and the auth requirement on every endpoint.

ALL tests are offline: email runs on the dev outbox backend (SMTP unset).
"""

import email as email_lib
import email.policy
import re
import sqlite3

import pytest

from src.dashboard.accounts import UserStore
from src.dashboard.api import create_app


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """Isolated DB + outbox per test; dev email backend guaranteed."""
    db_path = tmp_path / "subscriptions.sqlite3"
    monkeypatch.setenv("HYDRASHIELD_CACHE_DB", str(db_path))
    monkeypatch.setenv("HYDRASHIELD_OUTBOX_DIR", str(tmp_path / "outbox"))
    for var in ("SMTP_HOST", "SMTP_USER"):
        monkeypatch.delenv(var, raising=False)
    import src.dashboard.cache as cache_mod
    import src.dashboard.api as api_module

    monkeypatch.setattr(cache_mod, "_default_cache", None)
    api_module._rate_limiter._hits.clear()
    yield {"db": db_path, "outbox": tmp_path / "outbox"}
    api_module._rate_limiter._hits.clear()


@pytest.fixture()
def client(env):
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _auth_headers(client, env, email="user@example.org"):
    """Register + verify a user through the real auth flow; Bearer headers."""
    resp = client.post("/api/v2/auth/register",
                       json={"email": email, "password": "correct horse battery",
                             "consent": True})
    assert resp.status_code == 201, resp.get_json()
    files = sorted(env["outbox"].glob("*_email_verification_*.eml"))
    msg = email_lib.message_from_string(
        files[-1].read_text(encoding="utf-8"), policy=email_lib.policy.default)
    token = re.search(r"token=([A-Za-z0-9_\-]+)",
                      msg.get_body(("plain",)).get_content()).group(1)
    resp = client.get(f"/api/v2/auth/verify?token={token}")
    assert resp.status_code == 200, resp.get_json()
    return {"Authorization": f"Bearer {resp.get_json()['session_token']}"}


def _role(env, email):
    conn = sqlite3.connect(str(env["db"]))
    row = conn.execute("SELECT role FROM users WHERE email = ?", (email,)).fetchone()
    conn.close()
    return row[0]


def _set_role(env, email, role):
    conn = sqlite3.connect(str(env["db"]))
    conn.execute("UPDATE users SET role = ? WHERE email = ?", (role, email))
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Initial state + auth
# ---------------------------------------------------------------------------

def test_subscription_endpoints_require_auth(client):
    assert client.get("/api/v2/account/subscription").status_code == 401
    assert client.post("/api/v2/account/subscribe").status_code == 401
    assert client.post("/api/v2/account/unsubscribe").status_code == 401


def test_subscription_initially_none(client, env):
    headers = _auth_headers(client, env)
    resp = client.get("/api/v2/account/subscription", headers=headers)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["role"] == "registered"
    assert body["subscription"] is None
    assert body["subscriber_unlocks"]


# ---------------------------------------------------------------------------
# Subscribe
# ---------------------------------------------------------------------------

def test_subscribe_activates_tier_emails_and_audits(client, env):
    headers = _auth_headers(client, env)
    resp = client.post("/api/v2/account/subscribe", headers=headers)
    assert resp.status_code == 201, resp.get_json()
    body = resp.get_json()
    assert body["already_active"] is False
    sub = body["subscription"]
    assert sub["tier"] == "subscriber" and sub["status"] == "active"
    assert sub["started_at"]
    assert _role(env, "user@example.org") == "subscriber"

    # Exactly one confirmation email, carrying the tier facts.
    files = sorted(env["outbox"].glob("*subscription_confirmation*.eml"))
    assert len(files) == 1
    msg = email_lib.message_from_string(
        files[-1].read_text(encoding="utf-8"), policy=email_lib.policy.default)
    plain = msg.get_body(("plain",)).get_content()
    assert "subscriber" in plain and "never charges" in plain

    # Audited (never with secrets).
    actions = [r["action"] for r in UserStore(str(env["db"])).list_audit()]
    assert "subscribe" in actions


def test_subscribe_is_idempotent(client, env):
    headers = _auth_headers(client, env)
    assert client.post("/api/v2/account/subscribe", headers=headers).status_code == 201
    resp = client.post("/api/v2/account/subscribe", headers=headers)
    assert resp.status_code == 200
    assert resp.get_json()["already_active"] is True
    # No second subscription row, no second email.
    conn = sqlite3.connect(str(env["db"]))
    count = conn.execute(
        "SELECT COUNT(*) FROM subscriptions WHERE status = 'active'").fetchone()[0]
    conn.close()
    assert count == 1
    assert len(sorted(env["outbox"].glob("*subscription_confirmation*.eml"))) == 1


def test_subscribe_unlocks_api_key_creation(client, env):
    headers = _auth_headers(client, env)
    resp = client.post("/api/v2/account/api-keys", headers=headers, json={})
    assert resp.status_code == 403
    assert resp.get_json()["upgrade"]["required_role"] == "subscriber"

    client.post("/api/v2/account/subscribe", headers=headers)
    resp = client.post("/api/v2/account/api-keys", headers=headers,
                       json={"label": "gis-integration"})
    assert resp.status_code == 201, resp.get_json()
    assert resp.get_json()["api_key"]["key"].startswith("hs_")


# ---------------------------------------------------------------------------
# Unsubscribe
# ---------------------------------------------------------------------------

def test_unsubscribe_restores_free_tier(client, env):
    headers = _auth_headers(client, env)
    client.post("/api/v2/account/subscribe", headers=headers)
    resp = client.post("/api/v2/account/unsubscribe", headers=headers)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["active"] is False
    assert body["subscription"]["status"] == "cancelled"
    assert body["subscription"]["ends_at"]
    assert _role(env, "user@example.org") == "registered"

    # The subscriber-gated feature closes again…
    resp = client.post("/api/v2/account/api-keys", headers=headers, json={})
    assert resp.status_code == 403
    # …and re-subscribing reopens it (the full cycle works).
    assert client.post("/api/v2/account/subscribe", headers=headers).status_code == 201
    assert client.post("/api/v2/account/api-keys",
                       headers=headers, json={}).status_code == 201


def test_unsubscribe_is_idempotent(client, env):
    headers = _auth_headers(client, env)
    resp = client.post("/api/v2/account/unsubscribe", headers=headers)
    assert resp.status_code == 200
    assert resp.get_json()["subscription"] is None


def test_unsubscribe_never_demotes_operator_roles(client, env):
    """An admin (operator-promoted) who holds a subscription keeps the admin
    role on cancel — self-service cancellation touches only the exact
    self-service 'subscriber' tier."""
    headers = _auth_headers(client, env, email="ops@example.org")
    _set_role(env, "ops@example.org", "admin")
    assert client.post("/api/v2/account/subscribe", headers=headers).status_code == 201
    assert _role(env, "ops@example.org") == "admin"
    assert client.post("/api/v2/account/unsubscribe", headers=headers).status_code == 200
    assert _role(env, "ops@example.org") == "admin"
