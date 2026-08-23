"""Tests for the operator authorization model and server-side protection
of the Commercial Center.

Model: /admin.html is served by the API only after server-side auth
(Caddy routes it there). The operator role comes from the server env
(HYDRASHIELD_OPERATOR_EMAILS) at session resolution — there is no
endpoint or client path to set a role.
"""

import os
import sqlite3

import pytest

os.environ["HYDRASHIELD_CACHE_DB"] = "/tmp/hydrashield_test_adminaccess.sqlite3"
if os.path.exists(os.environ["HYDRASHIELD_CACHE_DB"]):
    os.remove(os.environ["HYDRASHIELD_CACHE_DB"])


@pytest.fixture()
def env(tmp_path, monkeypatch):
    db_path = tmp_path / "api.sqlite3"
    monkeypatch.setenv("HYDRASHIELD_CACHE_DB", str(db_path))
    monkeypatch.delenv("HYDRASHIELD_OPERATOR_EMAILS", raising=False)
    import src.dashboard.cache as cache_mod
    import src.dashboard.api as api_mod

    monkeypatch.setattr(cache_mod, "_default_cache", None)
    monkeypatch.setattr(api_mod, "_rate_limiter", api_mod._RateLimiter())
    return {"db": db_path}


@pytest.fixture()
def client(env):
    from src.dashboard.api import create_app

    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def _register_login(client, env, email):
    client.post("/api/v2/auth/register",
                json={"email": email, "password": "Correct-Horse-42!",
                      "consent": True})
    from src.dashboard.accounts import UserStore

    store = UserStore(str(env["db"]))
    user = store.get_user_by_email(email)
    store.mark_email_verified(user["id"])
    login = client.post("/api/v2/auth/login",
                        json={"email": email, "password": "Correct-Horse-42!"})
    return {"Authorization": f"Bearer {login.get_json()['session_token']}"}


# ---------------------------------------------------------------------------
# /admin.html server-side protection
# ---------------------------------------------------------------------------


def test_admin_html_anonymous_rejected(client):
    resp = client.get("/admin.html")
    assert resp.status_code == 401
    assert "text/html" not in resp.content_type


def test_admin_html_registered_user_rejected(client, env):
    headers = _register_login(client, env, "user@example.org")
    resp = client.get("/admin.html", headers=headers)
    assert resp.status_code == 403
    assert resp.get_json()["upgrade"]["required_role"] == "admin"


def test_admin_html_operator_succeeds(client, env, monkeypatch):
    monkeypatch.setenv("HYDRASHIELD_OPERATOR_EMAILS", "info@talaix.com")
    headers = _register_login(client, env, "info@talaix.com")
    resp = client.get("/admin.html", headers=headers)
    assert resp.status_code == 200
    assert "Commercial Center" in resp.get_data(as_text=True)
    assert resp.headers.get("X-Robots-Tag") == "noindex, nofollow"


def test_operator_promotion_is_env_driven_and_audited(client, env, monkeypatch):
    monkeypatch.setenv("HYDRASHIELD_OPERATOR_EMAILS", "info@talaix.com")
    headers = _register_login(client, env, "info@talaix.com")
    # Promotion happens when the session is resolved (an authenticated call).
    assert client.get("/api/v2/account", headers=headers).status_code == 200
    from src.dashboard.accounts import UserStore

    store = UserStore(str(env["db"]))
    user = store.get_user_by_email("info@talaix.com")
    assert user["role"] == "admin"
    audit = store.list_audit(user["id"])
    assert any(a["action"] == "operator_promotion" for a in audit)


def test_normal_user_never_promoted(client, env):
    _register_login(client, env, "regular@example.org")
    from src.dashboard.accounts import UserStore

    store = UserStore(str(env["db"]))
    user = store.get_user_by_email("regular@example.org")
    assert user["role"] == "registered"


def test_no_self_role_elevation_endpoint(client, env):
    headers = _register_login(client, env, "sneaky@example.org")
    resp = client.patch("/api/v2/account", json={"role": "admin"},
                        headers=headers)
    assert resp.status_code == 400  # only display_name is supported
    resp = client.post("/api/v2/auth/register",
                       json={"email": "s2@example.org",
                             "password": "Correct-Horse-42!",
                             "consent": True, "role": "admin"})
    from src.dashboard.accounts import UserStore

    store = UserStore(str(env["db"]))
    assert store.get_user_by_email("s2@example.org")["role"] == "registered"


# ---------------------------------------------------------------------------
# Commercial data stays behind authorization
# ---------------------------------------------------------------------------


def test_commercial_apis_reject_anonymous(client):
    for path in ("/api/v2/admin/intel", "/api/v2/admin/analytics/summary",
                 "/api/v2/admin/analytics/top", "/api/v2/admin/analytics/daily"):
        assert client.get(path).status_code == 401, path


def test_commercial_apis_reject_registered_user(client, env):
    headers = _register_login(client, env, "plain@example.org")
    for path in ("/api/v2/admin/intel", "/api/v2/admin/analytics/summary"):
        assert client.get(path, headers=headers).status_code == 403, path
