"""Offline tests for the Commercial Center surfaces added with the
marketing command center:

- /admin.html gate: humans (Accept: text/html) get a sign-in redirect or a
  branded 403 page; API clients keep the JSON 401/403 contracts.
- Contact-form persistence: POST /api/v2/contact stores the message; the
  admin-only /api/v2/admin/contacts endpoints list and re-status it.
- The prospect map payload: workspace leads surface as country-level,
  rule-scored markers in the intel payload.
- Wiring guards: admin.html carries the map mount; docker-compose mounts
  the marketing workspace into the api container (so production keeps
  showing the workspace — it is excluded from the image by .dockerignore).
"""

import os
import sqlite3

import pytest

os.environ["HYDRASHIELD_CACHE_DB"] = "/tmp/hydrashield_test_commercial.sqlite3"
if os.path.exists(os.environ["HYDRASHIELD_CACHE_DB"]):
    os.remove(os.environ["HYDRASHIELD_CACHE_DB"])


@pytest.fixture()
def env(tmp_path, monkeypatch):
    db_path = tmp_path / "api.sqlite3"
    monkeypatch.setenv("HYDRASHIELD_CACHE_DB", str(db_path))
    monkeypatch.setenv("HYDRASHIELD_OUTBOX_DIR", str(tmp_path / "outbox"))
    for var in ("SMTP_HOST", "SMTP_USER"):
        monkeypatch.delenv(var, raising=False)
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


def _make_user(client, env, email, role=None):
    resp = client.post("/api/v2/auth/register",
                       json={"email": email, "password": "Correct-Horse-42!",
                             "consent": True})
    assert resp.status_code == 201, resp.get_json()
    from src.dashboard.accounts import UserStore

    store = UserStore(str(env["db"]))
    user = store.get_user_by_email(email)
    store.mark_email_verified(user["id"])
    if role:
        with sqlite3.connect(store.db_path) as conn:
            conn.execute("UPDATE users SET role = ? WHERE id = ?",
                         (role, user["id"]))
    login = client.post("/api/v2/auth/login",
                        json={"email": email, "password": "Correct-Horse-42!"})
    return {"Authorization": f"Bearer {login.get_json()['session_token']}"}


_BROWSER = {"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9"}


# ---------------------------------------------------------------------------
# /admin.html gate
# ---------------------------------------------------------------------------

def test_admin_gate_anonymous_api_client_keeps_json_401(client):
    resp = client.get("/admin.html")
    assert resp.status_code == 401
    assert resp.get_json()["error"] == "Authentication required"


def test_admin_gate_redirects_anonymous_browsers_to_signin(client):
    resp = client.get("/admin.html", headers=_BROWSER)
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/account.html?next=/admin.html&reason=signin"


def test_admin_gate_branded_403_page_for_non_admin_browsers(client, env):
    headers = _make_user(client, env, "plain@example.org")
    resp = client.get("/admin.html", headers={**headers, **_BROWSER})
    assert resp.status_code == 403
    assert resp.content_type.startswith("text/html")
    page = resp.get_data(as_text=True)
    assert "Restricted area" in page and "plain@example.org" in page
    # The JSON contract is untouched for API clients.
    resp = client.get("/admin.html", headers=headers)
    assert resp.status_code == 403 and resp.get_json()["upgrade"]["required_role"] == "admin"


def test_admin_gate_serves_shell_to_admin_browsers(client, env):
    headers = _make_user(client, env, "op@example.org", role="admin")
    resp = client.get("/admin.html", headers={**headers, **_BROWSER})
    assert resp.status_code == 200
    assert resp.content_type.startswith("text/html")
    assert resp.headers["X-Robots-Tag"] == "noindex, nofollow"


# ---------------------------------------------------------------------------
# Contact-form persistence + admin contacts API
# ---------------------------------------------------------------------------

def _post_contact(client, email="lead@acme.example"):
    return client.post("/api/v2/contact", json={
        "email": email, "name": "Ada Lovelace", "organization": "Acme Bank",
        "interest": "banking",
        "message": "We need wildfire risk screening for our portfolio."})


def test_contact_message_is_persisted_and_admin_listed(client, env):
    assert _post_contact(client).status_code == 201
    admin = _make_user(client, env, "op@example.org", role="admin")
    resp = client.get("/api/v2/admin/contacts", headers=admin)
    assert resp.status_code == 200
    contacts = resp.get_json()["contacts"]
    assert len(contacts) == 1
    c = contacts[0]
    assert c["organization"] == "Acme Bank" and c["status"] == "new"
    assert c["interest"] == "banking"


def test_contacts_endpoints_are_admin_only(client, env):
    assert client.get("/api/v2/admin/contacts").status_code == 401
    plain = _make_user(client, env, "plain@example.org")
    assert client.get("/api/v2/admin/contacts", headers=plain).status_code == 403
    assert client.patch("/api/v2/admin/contacts/1",
                        headers=plain, json={"status": "closed"}).status_code == 403


def test_contact_status_pipeline(client, env):
    _post_contact(client)
    admin = _make_user(client, env, "op@example.org", role="admin")
    mid = client.get("/api/v2/admin/contacts", headers=admin) \
        .get_json()["contacts"][0]["id"]
    resp = client.patch(f"/api/v2/admin/contacts/{mid}",
                        headers=admin, json={"status": "qualified"})
    assert resp.status_code == 200 and resp.get_json()["status"] == "qualified"
    # Invalid status and unknown id are honest 404s.
    assert client.patch(f"/api/v2/admin/contacts/{mid}",
                        headers=admin, json={"status": "bogus"}).status_code == 404
    assert client.patch("/api/v2/admin/contacts/9999",
                        headers=admin, json={"status": "closed"}).status_code == 404


# ---------------------------------------------------------------------------
# Prospect map payload
# ---------------------------------------------------------------------------

def test_intel_carries_rule_scored_country_level_leads_map(client, env):
    admin = _make_user(client, env, "op@example.org", role="admin")
    resp = client.get("/api/v2/admin/intel", headers=admin)
    assert resp.status_code == 200
    body = resp.get_json()
    markers = body["leads_map"]
    assert markers, "workspace leads should produce map markers"
    for m in markers:
        assert -90 <= m["lat"] <= 90 and -180 <= m["lon"] <= 180
        assert 0 <= m["score"] <= 100
        assert m["organization"] and m["country"]
    assert [m["score"] for m in markers] == sorted(
        [m["score"] for m in markers], reverse=True)
    assert "Country-level" in body["leads_map_note"]


# ---------------------------------------------------------------------------
# Wiring guards (regression nets)
# ---------------------------------------------------------------------------

def test_admin_page_carries_command_center_mounts():
    path = os.path.join(os.path.dirname(__file__), "..", "website", "admin.html")
    with open(path, encoding="utf-8") as fh:
        html = fh.read()
    for mount in ("boardBlock", "leadsMap", "contactsBlock"):
        assert f'id="{mount}"' in html, mount
    js = os.path.join(os.path.dirname(__file__), "..", "website", "js", "admin.js")
    with open(js, encoding="utf-8") as fh:
        admin_js = fh.read()
    assert "/v2/admin/contacts" in admin_js
    assert "leads_map" in admin_js


def test_docker_compose_mounts_marketing_workspace_read_only():
    """The workspace is excluded from the image (.dockerignore); without the
    bind mount the production Commercial Center silently goes empty."""
    path = os.path.join(os.path.dirname(__file__), "..", "docker-compose.yml")
    with open(path, encoding="utf-8") as fh:
        compose = fh.read()
    assert "./marketing:/code/marketing:ro" in compose
