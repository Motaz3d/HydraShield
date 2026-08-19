"""Offline tests for the operator intelligence endpoint
(GET /api/v2/admin/intel, src/dashboard/admin_intel.py).

Covers: admin-only access, aggregate structure, the honest
workspace-unavailable path, and that no individual visitor data leaks.
"""

import os
import sqlite3

import pytest

os.environ["HYDRASHIELD_CACHE_DB"] = "/tmp/hydrashield_test_adminintel.sqlite3"
if os.path.exists(os.environ["HYDRASHIELD_CACHE_DB"]):
    os.remove(os.environ["HYDRASHIELD_CACHE_DB"])


@pytest.fixture()
def env(tmp_path, monkeypatch):
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


def _make_admin(client, env):
    resp = client.post("/api/v2/auth/register",
                       json={"email": "op@example.org",
                             "password": "Correct-Horse-42!", "consent": True})
    assert resp.status_code == 201
    from src.dashboard.accounts import UserStore

    store = UserStore(str(env["db"]))
    user = store.get_user_by_email("op@example.org")
    store.mark_email_verified(user["id"])
    with sqlite3.connect(store.db_path) as conn:
        conn.execute("UPDATE users SET role = 'admin' WHERE id = ?",
                     (user["id"],))
    login = client.post("/api/v2/auth/login",
                        json={"email": "op@example.org",
                              "password": "Correct-Horse-42!"})
    return {"Authorization": f"Bearer {login.get_json()['session_token']}"}


def test_intel_requires_auth(client):
    assert client.get("/api/v2/admin/intel").status_code == 401


def test_intel_requires_admin_role(client, env):
    # A plain registered user gets 403 with the upgrade descriptor.
    client.post("/api/v2/auth/register",
                json={"email": "user@example.org",
                      "password": "Correct-Horse-42!", "consent": True})
    from src.dashboard.accounts import UserStore

    store = UserStore(str(env["db"]))
    user = store.get_user_by_email("user@example.org")
    store.mark_email_verified(user["id"])
    login = client.post("/api/v2/auth/login",
                        json={"email": "user@example.org",
                              "password": "Correct-Horse-42!"})
    headers = {"Authorization": f"Bearer {login.get_json()['session_token']}"}
    resp = client.get("/api/v2/admin/intel", headers=headers)
    assert resp.status_code == 403
    assert resp.get_json()["upgrade"]["required_role"] == "admin"


def test_intel_structure_and_aggregates(client, env):
    headers = _make_admin(client, env)
    client.post("/api/v2/analytics/event",
                json={"events": [{"event": "page_view", "page": "map.html"},
                                 {"event": "hazard_selected", "hazard": "flood"}]})
    resp = client.get("/api/v2/admin/intel", headers=headers)
    assert resp.status_code == 200
    body = resp.get_json()
    for key in ("date", "today", "accounts", "alerts", "demand", "workspace"):
        assert key in body, key
    assert body["accounts"]["total_users"] >= 1
    assert body["demand"]["funnel"]["page_view"] >= 1
    assert body["demand"]["top_hazards"][0]["hazard"] == "flood"
    # The workspace may or may not be present in the checkout; both paths
    # must be honest.
    if body["workspace"]["available"]:
        assert "leads" in body["workspace"]
    else:
        assert body["workspace"]["note"]


def test_intel_contains_no_individual_visitor_data(client, env):
    headers = _make_admin(client, env)
    client.post("/api/v2/analytics/event",
                json={"event": "page_view", "session_id": "secret-session-xyz"})
    body = client.get("/api/v2/admin/intel", headers=headers).get_json()
    assert "secret-session-xyz" not in str(body)


def test_intel_commercial_center_sections(client, env):
    """The Commercial Center payload carries the full section set with
    aggregate counts and the honest workspace state."""
    headers = _make_admin(client, env)
    client.post("/api/v2/analytics/event",
                json={"events": [{"event": "page_view", "session_id": "s1"},
                                 {"event": "location_analyzed", "session_id": "s1"},
                                 {"event": "cta_viewed", "session_id": "s1"}]})
    body = client.get("/api/v2/admin/intel", headers=headers).get_json()
    today = body["today"]
    for key in ("visitors", "repeat_users", "new_users", "analyses",
                "reports", "saved_locations", "monitoring_rules",
                "sms_interest", "subscriptions"):
        assert key in today, key
    assert today["analyses"] >= 1
    for section in ("customers", "marketing", "copilot", "attention",
                    "funnel_stages", "targets"):
        assert section in body, section
    funnel = body["funnel_stages"]
    for stage in ("visitor", "analysis", "repeat_analysis", "account",
                  "saved_location", "monitoring", "sms", "subscription",
                  "professional", "business"):
        assert stage in funnel, stage
    # SMS delivery state is honest.
    assert body["attention"]["sms_delivery_configured"] is False


def test_intel_funding_radar_provenance(client, env):
    """The funding radar exposes programmes with official URLs and honest
    deadline/amount states — never fabricated facts."""
    headers = _make_admin(client, env)
    body = client.get("/api/v2/admin/intel", headers=headers).get_json()
    fr = body["funding_radar"]
    assert "programmes" in fr and "eu_funding" in fr and "procurement" in fr
    assert fr["programmes"], "platform funding KB must be present"
    for p in fr["programmes"]:
        assert p["official_url"].startswith("https://"), p["name"]
        assert p["deadline"] in ("not stated", "not currently verified") \
            or p["deadline"][:4].isdigit(), p["name"]
        assert p["date_checked"]
    # Asian development finance is now in the KB.
    names = {p["name"] for p in fr["programmes"]}
    assert any("Asian Development Bank" in n for n in names)
    assert any("Asian Infrastructure Investment Bank" in n for n in names)


def test_intel_daily_workspace_fields(client, env):
    """The daily-workspace payload: contact-now carries the full context
    (why/hazards/product/message/next action), plus campaigns and today's
    activity."""
    headers = _make_admin(client, env)
    body = client.get("/api/v2/admin/intel", headers=headers).get_json()
    cp = body["copilot"]
    for key in ("contact_now", "followups_due", "publish_queue",
                "campaigns", "new_leads_today", "interactions_today"):
        assert key in cp, key
    if cp["contact_now"]:
        c = cp["contact_now"][0]
        for field in ("organization", "why", "hazards", "service",
                      "message", "next_action"):
            assert field in c, field
    assert body["hazard_areas"] is not None
    assert body["hazard_opportunities"] is not None
