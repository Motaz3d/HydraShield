"""Offline tests for first-party product analytics
(src/dashboard/analytics.py + website/js/analytics.js beacon).

Covers: event whitelist enforcement, field dropping, coordinate rounding
(privacy), session pseudonym hashing, account-event user linkage
(server-side only), retention purge, session erasure, ingest endpoint
(contract, batch, rate limit), and admin-only aggregate access.
"""

import os
import sqlite3

import pytest

os.environ["HYDRASHIELD_CACHE_DB"] = "/tmp/hydrashield_test_analytics_cache.sqlite3"
if os.path.exists(os.environ["HYDRASHIELD_CACHE_DB"]):
    os.remove(os.environ["HYDRASHIELD_CACHE_DB"])

from src.dashboard.analytics import AnalyticsStore  # noqa: E402
from src.dashboard.accounts import hash_token  # noqa: E402


@pytest.fixture()
def store(tmp_path):
    return AnalyticsStore(str(tmp_path / "analytics.sqlite3"))


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """Isolated DB per test; reset the process-wide cache singleton so the
    app and direct stores share the same file (test_accounts convention)."""
    db_path = tmp_path / "api.sqlite3"
    monkeypatch.setenv("HYDRASHIELD_CACHE_DB", str(db_path))
    import src.dashboard.cache as cache_mod

    monkeypatch.setattr(cache_mod, "_default_cache", None)
    # The rate limiter is process-global; reset it so the test is
    # independent of how many registrations earlier modules consumed.
    import src.dashboard.api as api_mod

    monkeypatch.setattr(api_mod, "_rate_limiter", api_mod._RateLimiter())
    return {"db": db_path}


@pytest.fixture()
def client(env):
    from src.dashboard.api import create_app

    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


# ---------------------------------------------------------------------------
# Store: validation + privacy
# ---------------------------------------------------------------------------


def test_record_accepts_whitelisted_event(store):
    result = store.record({"event": "page_view", "page": "map.html",
                           "session_id": "abc123"})
    assert result == {"recorded": True}
    assert store.count() == 1


def test_record_rejects_unknown_event(store):
    assert "error" in store.record({"event": "keystroke_logged"})
    assert "error" in store.record({"event": ""})
    assert store.count() == 0


def test_unexpected_fields_never_stored(store):
    """The whitelist is the privacy guarantee: name/email/password-style
    fields must not persist even if a client sends them."""
    store.record({"event": "page_view", "page": "index.html"})
    with sqlite3.connect(store.db_path) as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(analytics_events)")]
    for forbidden in ("email", "name", "password", "ip", "user_agent", "message"):
        assert forbidden not in cols


def test_coordinates_rounded_to_coarse_resolution(store):
    store.record({"event": "location_analyzed", "lat": 37.389213, "lon": -5.984512})
    with sqlite3.connect(store.db_path) as conn:
        row = conn.execute("SELECT lat, lon FROM analytics_events").fetchone()
    assert row == (37.4, -6.0)  # ~11 km resolution, never precise


def test_non_numeric_coordinates_become_null(store):
    store.record({"event": "location_analyzed", "lat": "north", "lon": None})
    with sqlite3.connect(store.db_path) as conn:
        row = conn.execute("SELECT lat, lon FROM analytics_events").fetchone()
    assert row == (None, None)


def test_session_id_stored_only_as_hash(store):
    store.record({"event": "page_view", "session_id": "raw-session-123"})
    with sqlite3.connect(store.db_path) as conn:
        digest = conn.execute(
            "SELECT session_hash FROM analytics_events").fetchone()[0]
    assert digest == hash_token("raw-session-123")
    assert digest != "raw-session-123"


def test_user_id_only_on_account_events(store):
    store.record({"event": "page_view"}, user_id=42)
    store.record({"event": "account_created"}, user_id=42)
    with sqlite3.connect(store.db_path) as conn:
        rows = conn.execute(
            "SELECT event, user_id FROM analytics_events ORDER BY id").fetchall()
    assert rows[0] == ("page_view", None)      # browsing never links identity
    assert rows[1] == ("account_created", 42)  # explicit account event may


def test_retention_purge(store):
    store.record({"event": "page_view"})
    with sqlite3.connect(store.db_path) as conn:
        conn.execute("UPDATE analytics_events SET ts = '2000-01-01T00:00:00Z'")
    assert store.purge_older_than(365) == 1
    assert store.count() == 0


def test_delete_session_erasure(store):
    store.record({"event": "page_view", "session_id": "s1"})
    store.record({"event": "map_opened", "session_id": "s1"})
    store.record({"event": "page_view", "session_id": "s2"})
    assert store.delete_session("s1") == 2
    assert store.count() == 1


# ---------------------------------------------------------------------------
# Ingest endpoint
# ---------------------------------------------------------------------------


def test_ingest_single_and_batch(client):
    resp = client.post("/api/v2/analytics/event",
                       json={"event": "page_view", "page": "index.html",
                             "session_id": "x", "device": "desktop"})
    assert resp.status_code == 202
    assert resp.get_json()["recorded"] == 1

    resp = client.post("/api/v2/analytics/event",
                       json={"events": [
                           {"event": "map_opened"},
                           {"event": "not_a_real_event"},
                           {"event": "hazard_selected", "hazard": "flood"},
                       ]})
    assert resp.status_code == 202
    assert resp.get_json()["recorded"] == 2  # unknown event silently skipped


def test_ingest_drops_unexpected_fields(client, env):
    client.post("/api/v2/analytics/event",
                json={"event": "page_view", "email": "a@b.c", "password": "x"})
    store = AnalyticsStore(str(env["db"]))
    with sqlite3.connect(store.db_path) as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(analytics_events)")]
    assert "email" not in cols and "password" not in cols


def test_ingest_never_accepts_user_id(client, env):
    """Identity must not be forgeable from the public endpoint."""
    client.post("/api/v2/analytics/event",
                json={"event": "page_view", "user_id": 7})
    store = AnalyticsStore(str(env["db"]))
    with sqlite3.connect(store.db_path) as conn:
        uid = conn.execute("SELECT user_id FROM analytics_events").fetchone()[0]
    assert uid is None


# ---------------------------------------------------------------------------
# Admin aggregates (access control)
# ---------------------------------------------------------------------------


def _make_admin(client, env):
    """Register + verify a user and promote to admin directly in the DB."""
    resp = client.post("/api/v2/auth/register",
                       json={"email": "admin@example.org",
                             "password": "Correct-Horse-42!", "consent": True})
    assert resp.status_code == 201
    from src.dashboard.accounts import UserStore

    store = UserStore(str(env["db"]))
    user = store.get_user_by_email("admin@example.org")
    assert user is not None
    store.mark_email_verified(user["id"])
    with sqlite3.connect(store.db_path) as conn:
        conn.execute("UPDATE users SET role = 'admin' WHERE id = ?", (user["id"],))
    login = client.post("/api/v2/auth/login",
                        json={"email": "admin@example.org",
                              "password": "Correct-Horse-42!"})
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.get_json()['session_token']}"}


def test_admin_endpoints_require_admin(client):
    assert client.get("/api/v2/admin/analytics/summary").status_code == 401
    assert client.get("/api/v2/admin/analytics/top").status_code == 401
    assert client.get("/api/v2/admin/analytics/daily").status_code == 401


def test_admin_summary_and_top(client, env):
    headers = _make_admin(client, env)
    client.post("/api/v2/analytics/event",
                json={"events": [{"event": "page_view", "page": "map.html"},
                                 {"event": "page_view", "page": "map.html"},
                                 {"event": "map_opened", "page": "map.html"}]})
    summary = client.get("/api/v2/admin/analytics/summary", headers=headers)
    assert summary.status_code == 200
    body = summary.get_json()
    assert body["by_event"]["page_view"] >= 2
    assert "funnel" in body and "account_created" in body["funnel"]

    top = client.get("/api/v2/admin/analytics/top?dimension=page",
                     headers=headers)
    assert top.status_code == 200
    assert top.get_json()["top"][0]["value"] == "map.html"

    daily = client.get("/api/v2/admin/analytics/daily", headers=headers)
    assert daily.status_code == 200
    assert daily.get_json()["days"]
    bad = client.get("/api/v2/admin/analytics/top?dimension=email",
                     headers=headers)
    assert bad.status_code == 400
