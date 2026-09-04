"""Offline tests for the Marketing CRM (src/dashboard/marketing_crm.py).

Covers the lazy navigation tree, lead detail, immediate send, scheduled
outreach, the scheduled processor script, and MarketingStore validation.
All email delivery uses the dev outbox backend; no SMTP server is contacted.
"""

import importlib.util
import json
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest

os.environ["HYDRASHIELD_CACHE_DB"] = "/tmp/hydrashield_test_marketing_crm.sqlite3"
if os.path.exists(os.environ["HYDRASHIELD_CACHE_DB"]):
    os.remove(os.environ["HYDRASHIELD_CACHE_DB"])


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """Isolated DB + dev outbox + temporary marketing workspace."""
    db_path = tmp_path / "api.sqlite3"
    outbox_dir = tmp_path / "outbox"
    ws_dir = tmp_path / "marketing"
    (ws_dir / "leads").mkdir(parents=True)
    (ws_dir / "followups").mkdir(parents=True)

    monkeypatch.setenv("HYDRASHIELD_CACHE_DB", str(db_path))
    monkeypatch.setenv("HYDRASHIELD_OUTBOX_DIR", str(outbox_dir))
    for var in ("SMTP_HOST", "SMTP_USER", "HUNTER_API_KEY"):
        monkeypatch.delenv(var, raising=False)

    import src.dashboard.cache as cache_mod
    import src.dashboard.admin_intel as intel_mod
    import src.dashboard.marketing_crm as crm_mod
    import src.dashboard.api as api_mod

    monkeypatch.setattr(cache_mod, "_default_cache", None)
    monkeypatch.setattr(api_mod, "_rate_limiter", api_mod._RateLimiter())
    # Point both modules at the temporary workspace so reads and followup
    # lookups stay inside the test directory.
    monkeypatch.setattr(intel_mod, "_WORKSPACE", str(ws_dir))
    monkeypatch.setattr(crm_mod, "_WORKSPACE", str(ws_dir))

    return {"db": db_path, "outbox": outbox_dir, "ws": ws_dir}


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


def _write_lead(ws_dir, slug, lead):
    path = Path(ws_dir) / "leads" / f"{slug}.json"
    path.write_text(json.dumps(lead), encoding="utf-8")


def _write_followup(ws_dir, slug, followup):
    path = Path(ws_dir) / "followups" / f"{slug}_followup.json"
    path.write_text(json.dumps(followup), encoding="utf-8")


def _eml_files(outbox_dir, template=None):
    pattern = f"*_{template}_*.eml" if template else "*.eml"
    return sorted(Path(outbox_dir).glob(pattern))


# ---------------------------------------------------------------------------
# Workspace fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def sample_workspace(env):
    """A handful of leads covering sectors, countries and pipeline states."""
    leads = [
        {
            "organization": "Test Bank One",
            "segment": "banking",
            "country": "US",
            "website": "https://www.testbankone.com",
            "priority": "high",
            "urgency": "high",
            "outreach_status": "researched",
            "recommended_product": "portfolio_screening",
            "next_action": "Send intro email",
            "decision_maker_role": "Sustainability Director",
            "identified_problem": "Exposure to flood and wildfire risk.",
            "relevant_capability": "Portfolio screening",
            "region": "Northeast",
        },
        {
            "organization": "Test Bank Two",
            "segment": "banking",
            "country": "US",
            "priority": "medium",
            "urgency": "medium",
            "outreach_status": "qualified",
            "recommended_product": "enterprise_dashboard",
            "decision_maker_role": "Risk Officer",
            "identified_problem": "Needs climate risk data.",
            "relevant_capability": "Enterprise dashboard",
            "region": "Southeast",
        },
        {
            "organization": "Test Insurer",
            "segment": "insurance",
            "country": "DE",
            "priority": "high",
            "urgency": "low",
            "outreach_status": "researched",
            "recommended_product": "risk_api",
            "decision_maker_role": "Head of Underwriting",
            "identified_problem": "Accumulating nat-cat exposure.",
            "relevant_capability": "Risk API",
        },
        {
            "organization": "Test Municipality",
            "segment": "municipalities",
            "country": "FR",
            "priority": "medium",
            "urgency": "medium",
            "outreach_status": "researched",
            "recommended_product": "municipal_dashboard",
            "decision_maker_role": "Resilience Officer",
            "identified_problem": "Adaptation planning gap.",
            "relevant_capability": "Municipal dashboard",
        },
        {
            "organization": "Test Engineering Firm",
            "segment": "engineering_firms",
            "country": "US",
            "priority": "medium",
            "urgency": "low",
            "outreach_status": "researched",
            "recommended_product": "risk_api",
            "decision_maker_role": "Technical Director",
            "identified_problem": "Engineering projects need hazard screening.",
            "relevant_capability": "Risk API",
        },
        {
            "organization": "Test Research Center",
            "segment": "research_centers",
            "country": "GB",
            "priority": "medium",
            "urgency": "low",
            "outreach_status": "researched",
            "recommended_product": "risk_api",
            "decision_maker_role": "Research Director",
            "identified_problem": "Data integration for climate models.",
            "relevant_capability": "Risk API",
        },
        {
            "organization": "Excluded Bank",
            "segment": "banking",
            "country": "US",
            "priority": "low",
            "urgency": "low",
            "outreach_status": "researched",
            "excluded": True,
            "recommended_product": "portfolio_screening",
            "decision_maker_role": "CFO",
            "identified_problem": "Competitor.",
            "relevant_capability": "Portfolio screening",
        },
    ]
    for lead in leads:
        slug = lead["organization"].lower().replace(" ", "-")
        lead["_slug"] = slug
        _write_lead(env["ws"], slug, lead)
    return env


# ---------------------------------------------------------------------------
# Auth gating
# ---------------------------------------------------------------------------

@pytest.mark.usefixtures("sample_workspace")
def test_crm_endpoints_require_auth(client):
    assert client.get("/api/v2/admin/marketing/tree").status_code == 401
    assert client.get("/api/v2/admin/marketing/lead/test-bank-one").status_code == 401
    assert client.post("/api/v2/admin/marketing/lead/test-bank-one/send",
                       json={}).status_code == 401
    assert client.post("/api/v2/admin/marketing/lead/test-bank-one/schedule",
                       json={}).status_code == 401
    assert client.get("/api/v2/admin/marketing/scheduled").status_code == 401
    assert client.post("/api/v2/admin/marketing/scheduled/1/cancel").status_code == 401


@pytest.mark.usefixtures("sample_workspace")
def test_crm_endpoints_require_admin_role(client, env):
    plain = _make_user(client, env, "plain@example.org")
    assert client.get("/api/v2/admin/marketing/tree",
                      headers=plain).status_code == 403
    assert client.get("/api/v2/admin/marketing/lead/test-bank-one",
                      headers=plain).status_code == 403
    assert client.post("/api/v2/admin/marketing/lead/test-bank-one/send",
                       headers=plain, json={}).status_code == 403


# ---------------------------------------------------------------------------
# Marketing aggregate stats
# ---------------------------------------------------------------------------

@pytest.mark.usefixtures("sample_workspace")
def test_stats_requires_auth(client):
    assert client.get("/api/v2/admin/marketing/stats").status_code == 401


@pytest.mark.usefixtures("sample_workspace")
def test_stats_requires_admin_role(client, env):
    plain = _make_user(client, env, "plain@example.org")
    assert client.get("/api/v2/admin/marketing/stats",
                      headers=plain).status_code == 403


def test_stats_empty_db(client, env):
    admin = _make_user(client, env, "op@example.org", role="admin")
    resp = client.get("/api/v2/admin/marketing/stats", headers=admin)
    assert resp.status_code == 200
    body = resp.get_json()
    for key in ("visitors", "subscribers", "activity", "top_pages",
                "daily", "top_referrers", "devices", "languages",
                "top_hazards", "note", "generated_at"):
        assert key in body, key
    assert body["visitors"]["today"] == 0
    assert body["visitors"]["last_7_days"] == 0
    assert body["visitors"]["last_30_days"] == 0
    assert body["visitors"]["total_unique_sessions"] == 0
    assert body["visitors"]["total_page_views"] == 0
    assert body["subscribers"]["active_subscriptions"] == 0
    assert body["subscribers"]["accounts"] == 1  # the admin user
    assert body["subscribers"]["verified_accounts"] == 1  # admin is verified
    assert body["activity"]["active_sessions_30d"] == 0
    assert body["activity"]["analyses"] == 0
    assert body["activity"]["cta_clicks"] == 0
    assert body["activity"]["accounts_created"] == 0
    assert body["activity"]["subscription_events"] == 0
    assert body["top_pages"] == []
    assert body["daily"] == []
    assert body["top_referrers"] == []
    assert body["devices"] == []
    assert body["languages"] == []
    assert body["top_hazards"] == []


@pytest.mark.usefixtures("sample_workspace")
def test_stats_seeded_db(client, env):
    from src.dashboard.analytics import AnalyticsStore
    from src.dashboard.accounts import hash_token

    admin = _make_user(client, env, "op@example.org", role="admin")
    store = AnalyticsStore(str(env["db"]))

    # Today: two sessions on /solution.html with referrer/device/language.
    store.record({
        "event": "page_view", "page": "/solution.html",
        "session_id": "current-one", "referrer": "google",
        "device": "desktop", "language": "en",
    })
    store.record({
        "event": "location_analyzed", "hazard": "flood",
        "session_id": "current-one",
    })
    store.record({
        "event": "page_view", "page": "/solution.html",
        "session_id": "current-two", "referrer": "direct",
        "device": "mobile", "language": "es",
    })
    store.record({
        "event": "subscription_started", "session_id": "current-two",
    })
    # 10 days ago: third session page view from google/desktop/en.
    store.record({
        "event": "page_view", "page": "/solution.html",
        "session_id": "older", "referrer": "google",
        "device": "desktop", "language": "en",
    })
    # 5 days ago: fourth session selecting heat hazard.
    store.record({
        "event": "hazard_selected", "hazard": "heat",
        "session_id": "five-days-ago",
    })

    # Roll selected events back so daily/last_7_days/last_30_days differ.
    now = datetime.utcnow()
    with sqlite3.connect(str(env["db"])) as conn:
        conn.execute(
            "UPDATE analytics_events SET ts = ? WHERE session_hash = ?",
            ((now - timedelta(days=10)).isoformat() + "Z", hash_token("older")),
        )
        conn.execute(
            "UPDATE analytics_events SET ts = ? WHERE session_hash = ?",
            ((now - timedelta(days=5)).isoformat() + "Z", hash_token("five-days-ago")),
        )

    # One extra user and one active subscription in the shared DB.
    with sqlite3.connect(str(env["db"])) as conn:
        conn.execute(
            "INSERT INTO users (email, password_hash, role, status, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            ("seeded@example.org", "x", "registered", "pending",
             now.isoformat() + "Z"),
        )
        conn.execute(
            "INSERT INTO subscriptions (owner_user_id, tier, status, started_at)"
            " VALUES (?, ?, ?, ?)",
            (2, "professional", "active", now.isoformat() + "Z"),
        )

    resp = client.get("/api/v2/admin/marketing/stats", headers=admin)
    assert resp.status_code == 200
    body = resp.get_json()
    visitors = body["visitors"]
    assert visitors["today"] == 2
    assert visitors["last_7_days"] == 3
    assert visitors["last_30_days"] == 4
    assert visitors["total_unique_sessions"] == 4
    assert visitors["total_page_views"] == 3

    assert body["subscribers"]["active_subscriptions"] == 1
    assert body["subscribers"]["accounts"] == 2
    assert body["subscribers"]["verified_accounts"] == 1

    activity = body["activity"]
    assert activity["active_sessions_30d"] == 3
    assert activity["analyses"] == 1
    assert activity["cta_clicks"] == 0
    assert activity["accounts_created"] == 0
    assert activity["subscription_events"] == 1

    assert body["top_pages"] == [
        {"page": "/solution.html", "views": 3, "unique_visitors": 3}
    ]

    daily = {d["date"]: d for d in body["daily"]}
    today_str = now.strftime("%Y-%m-%d")
    assert daily[today_str] == {"date": today_str, "visitors": 2, "page_views": 2}
    assert daily[(now - timedelta(days=5)).strftime("%Y-%m-%d")] == {
        "date": (now - timedelta(days=5)).strftime("%Y-%m-%d"),
        "visitors": 1, "page_views": 0,
    }
    assert daily[(now - timedelta(days=10)).strftime("%Y-%m-%d")] == {
        "date": (now - timedelta(days=10)).strftime("%Y-%m-%d"),
        "visitors": 1, "page_views": 1,
    }

    assert body["top_referrers"] == [
        {"referrer": "google", "count": 2},
        {"referrer": "direct", "count": 1},
    ]
    assert body["devices"] == [
        {"device": "desktop", "count": 2},
        {"device": "mobile", "count": 1},
    ]
    assert body["languages"] == [
        {"language": "en", "count": 2},
        {"language": "es", "count": 1},
    ]
    assert sorted(body["top_hazards"], key=lambda x: x["hazard"]) == [
        {"hazard": "flood", "count": 1},
        {"hazard": "heat", "count": 1},
    ]


# ---------------------------------------------------------------------------
# Lazy navigation tree
# ---------------------------------------------------------------------------

@pytest.mark.usefixtures("sample_workspace")
def test_tree_root_returns_sectors_with_counts(client, env):
    admin = _make_user(client, env, "op@example.org", role="admin")
    resp = client.get("/api/v2/admin/marketing/tree", headers=admin)
    assert resp.status_code == 200
    body = resp.get_json()
    assert "sectors" in body
    assert "countries" not in body
    sectors = body["sectors"]
    # Six for-* categories in fixed order, plus "more" when raw segments exist.
    assert [s["key"] for s in sectors] == [
        "banking", "environmental_consulting", "investment", "insurance",
        "real_estate", "governments", "more",
    ]
    by_key = {s["key"]: s for s in sectors}
    assert by_key["banking"]["label"] == "Banks & lenders"
    assert by_key["environmental_consulting"]["label"] == "Consultants"
    assert by_key["investment"]["label"] == "Investors"
    assert by_key["insurance"]["label"] == "Insurance"
    assert by_key["real_estate"]["label"] == "Real estate"
    assert by_key["governments"]["label"] == "Government"
    assert by_key["more"]["label"] == "More sectors"
    # Aliases are aggregated into categories.
    assert by_key["banking"]["count"] == 2
    assert by_key["insurance"]["count"] == 1
    assert by_key["governments"]["count"] == 1  # municipalities
    assert by_key["environmental_consulting"]["count"] == 1  # engineering_firms
    assert by_key["investment"]["count"] == 0
    assert by_key["real_estate"]["count"] == 0
    assert by_key["more"]["count"] == 1  # research_centers


@pytest.mark.usefixtures("sample_workspace")
def test_tree_segment_returns_countries_for_category_or_raw(client, env):
    admin = _make_user(client, env, "op@example.org", role="admin")
    # Category: banking aggregates all banking leads.
    resp = client.get("/api/v2/admin/marketing/tree?segment=banking", headers=admin)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["segment"] == "banking"
    assert "countries" in body and "statuses" not in body and "leads" not in body
    assert body["countries"] == [{"country": "US", "count": 2}]

    # Alias category: environmental_consulting sees engineering_firms leads.
    resp = client.get("/api/v2/admin/marketing/tree?segment=environmental_consulting",
                      headers=admin)
    assert resp.get_json()["countries"] == [{"country": "US", "count": 1}]

    # Raw sub-sector: research_centers.
    resp = client.get("/api/v2/admin/marketing/tree?segment=research_centers",
                      headers=admin)
    assert resp.status_code == 200
    assert resp.get_json()["countries"] == [{"country": "GB", "count": 1}]


@pytest.mark.usefixtures("sample_workspace")
def test_tree_more_returns_subsectors(client, env):
    admin = _make_user(client, env, "op@example.org", role="admin")
    resp = client.get("/api/v2/admin/marketing/tree?segment=more", headers=admin)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["segment"] == "more"
    assert body["subsectors"] == [
        {"key": "research_centers", "label": "Research Centers", "count": 1}
    ]


@pytest.mark.usefixtures("sample_workspace")
def test_tree_parent_params_required(client, env):
    admin = _make_user(client, env, "op@example.org", role="admin")
    # Country without segment.
    assert client.get("/api/v2/admin/marketing/tree?country=US",
                      headers=admin).status_code == 400
    # Status without country.
    assert client.get("/api/v2/admin/marketing/tree?segment=banking&status=researched",
                      headers=admin).status_code == 400
    # Region without country.
    assert client.get("/api/v2/admin/marketing/tree?segment=banking&region=Northeast",
                      headers=admin).status_code == 400


@pytest.mark.usefixtures("sample_workspace")
def test_tree_segment_country_returns_regions_statuses_and_all_leads(client, env):
    admin = _make_user(client, env, "op@example.org", role="admin")
    resp = client.get("/api/v2/admin/marketing/tree?segment=banking&country=US",
                      headers=admin)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["segment"] == "banking"
    assert body["country"] == "US"
    assert body["regions"] == [
        {"region": "Northeast", "count": 1},
        {"region": "Southeast", "count": 1},
    ]
    assert body["statuses"] == [
        {"status": "researched", "count": 1},
        {"status": "qualified", "count": 1},
    ]
    # All leads in the intersection are returned, unfiltered by status/region.
    assert len(body["leads"]) == 2
    by_slug = {l["slug"]: l for l in body["leads"]}
    assert by_slug["test-bank-one"]["outreach_status"] == "researched"
    assert by_slug["test-bank-one"]["segment"] == "banking"
    assert by_slug["test-bank-one"]["region"] == "Northeast"
    assert by_slug["test-bank-two"]["outreach_status"] == "qualified"
    assert by_slug["test-bank-two"]["region"] == "Southeast"
    for lead in body["leads"]:
        assert "score" in lead and "recommended_product" in lead


@pytest.mark.usefixtures("sample_workspace")
def test_tree_region_filter_narrows_leads_and_statuses(client, env):
    admin = _make_user(client, env, "op@example.org", role="admin")
    resp = client.get(
        "/api/v2/admin/marketing/tree?segment=banking&country=US&region=Northeast",
        headers=admin,
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["segment"] == "banking"
    assert body["country"] == "US"
    assert body["region"] == "Northeast"
    # Regions are computed before filtering.
    assert body["regions"] == [
        {"region": "Northeast", "count": 1},
        {"region": "Southeast", "count": 1},
    ]
    assert body["statuses"] == [{"status": "researched", "count": 1}]
    assert len(body["leads"]) == 1
    lead = body["leads"][0]
    assert lead["slug"] == "test-bank-one"
    assert lead["region"] == "Northeast"


@pytest.mark.usefixtures("sample_workspace")
def test_tree_status_filter_works_with_regions(client, env):
    admin = _make_user(client, env, "op@example.org", role="admin")
    resp = client.get(
        "/api/v2/admin/marketing/tree?segment=banking&country=US&status=researched",
        headers=admin,
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["segment"] == "banking"
    assert body["country"] == "US"
    assert body["status"] == "researched"
    assert body["statuses"] == [
        {"status": "researched", "count": 1},
        {"status": "qualified", "count": 1},
    ]
    assert len(body["leads"]) == 1
    lead = body["leads"][0]
    assert lead["slug"] == "test-bank-one"
    assert lead["outreach_status"] == "researched"
    assert lead["segment"] == "banking"
    assert lead["region"] == "Northeast"


# ---------------------------------------------------------------------------
# Lead detail
# ---------------------------------------------------------------------------

@pytest.mark.usefixtures("sample_workspace")
def test_lead_detail_returns_full_payload(client, env):
    admin = _make_user(client, env, "op@example.org", role="admin")
    _write_followup(env["ws"], "test-bank-one",
                    {"next_action": "Call back", "note": "follow-up note"})
    resp = client.get("/api/v2/admin/marketing/lead/test-bank-one", headers=admin)
    assert resp.status_code == 200
    body = resp.get_json()
    for key in ("lead", "score", "interactions", "followup", "scheduled"):
        assert key in body, key
    assert body["lead"]["organization"] == "Test Bank One"
    assert body["followup"]["next_action"] == "Call back"


@pytest.mark.usefixtures("sample_workspace")
def test_lead_detail_unknown_slug_is_404(client, env):
    admin = _make_user(client, env, "op@example.org", role="admin")
    resp = client.get("/api/v2/admin/marketing/lead/no-such-lead", headers=admin)
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Immediate send
# ---------------------------------------------------------------------------

@pytest.mark.usefixtures("sample_workspace")
def test_send_creates_outbox_interaction_and_advances_status(client, env):
    admin = _make_user(client, env, "op@example.org", role="admin")
    resp = client.post(
        "/api/v2/admin/marketing/lead/test-bank-one/send",
        headers=admin,
        json={"to_email": "contact@example.org", "contact_name": "Ada"},
    )
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True
    assert resp.get_json()["outreach_status"] == "contacted"

    files = _eml_files(env["outbox"], "outreach_banking")
    assert len(files) == 1
    raw = files[0].read_text(encoding="utf-8")
    assert "To: contact@example.org" in raw
    assert "Subject:" in raw

    detail = client.get("/api/v2/admin/marketing/lead/test-bank-one",
                        headers=admin).get_json()
    emails = [i for i in detail["interactions"] if i["type"] == "email"]
    assert len(emails) == 1
    assert "contact@example.org" in emails[0]["summary"]
    assert detail["lead"]["outreach_status"] == "contacted"


@pytest.mark.usefixtures("sample_workspace")
def test_send_validates_email_and_slug(client, env):
    admin = _make_user(client, env, "op@example.org", role="admin")
    assert client.post(
        "/api/v2/admin/marketing/lead/test-bank-one/send",
        headers=admin, json={}).status_code == 400
    assert client.post(
        "/api/v2/admin/marketing/lead/test-bank-one/send",
        headers=admin, json={"to_email": "not-an-email"}).status_code == 400
    assert client.post(
        "/api/v2/admin/marketing/lead/unknown-lead/send",
        headers=admin, json={"to_email": "a@b.org"}).status_code == 404


# ---------------------------------------------------------------------------
# Schedule + cancel
# ---------------------------------------------------------------------------

@pytest.mark.usefixtures("sample_workspace")
def test_schedule_future_send_and_cancel(client, env):
    admin = _make_user(client, env, "op@example.org", role="admin")
    future = (datetime.utcnow() + timedelta(days=1)).isoformat() + "Z"
    resp = client.post(
        "/api/v2/admin/marketing/lead/test-bank-one/schedule",
        headers=admin,
        json={"to_email": "later@example.org", "send_at": future,
              "contact_name": "Bob"},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    sid = body["scheduled"]["id"]

    listed = client.get("/api/v2/admin/marketing/scheduled", headers=admin).get_json()
    assert any(r["id"] == sid for r in listed["scheduled"])

    detail = client.get("/api/v2/admin/marketing/lead/test-bank-one",
                        headers=admin).get_json()
    assert any(r["id"] == sid for r in detail["scheduled"])

    cancel = client.post(f"/api/v2/admin/marketing/scheduled/{sid}/cancel",
                         headers=admin)
    assert cancel.status_code == 200
    assert cancel.get_json()["ok"] is True
    assert cancel.get_json()["scheduled"]["status"] == "cancelled"

    # Second cancel is a 409.
    assert client.post(f"/api/v2/admin/marketing/scheduled/{sid}/cancel",
                       headers=admin).status_code == 409


@pytest.mark.usefixtures("sample_workspace")
def test_schedule_past_send_at_is_400(client, env):
    admin = _make_user(client, env, "op@example.org", role="admin")
    past = (datetime.utcnow() - timedelta(days=1)).isoformat() + "Z"
    resp = client.post(
        "/api/v2/admin/marketing/lead/test-bank-one/schedule",
        headers=admin,
        json={"to_email": "past@example.org", "send_at": past},
    )
    assert resp.status_code == 400
    assert "future" in resp.get_json()["error"]


# ---------------------------------------------------------------------------
# Scheduled processor script
# ---------------------------------------------------------------------------

@pytest.mark.usefixtures("sample_workspace")
def test_processor_script_sends_due_row(client, env):
    from src.dashboard.marketing_store import MarketingStore

    admin = _make_user(client, env, "op@example.org", role="admin")
    store = MarketingStore(str(env["db"]))
    past = (datetime.utcnow() - timedelta(hours=1)).isoformat()[:19]
    row = store.schedule_send(
        lead_slug="test-bank-one",
        to_email="scheduled@example.org",
        contact_name="Carol",
        template="outreach_generic",
        context={"organization": "Test Bank One", "country": "US"},
        send_at=past,
    )
    assert row is not None
    sid = row["id"]

    script_path = Path(__file__).resolve().parent.parent / "scripts" / "process_scheduled_outreach.py"
    spec = importlib.util.spec_from_file_location("process_scheduled_outreach", str(script_path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.main() == 0

    updated = store.get_scheduled(sid)
    assert updated["status"] == "sent"
    assert updated["sent_at"] is not None

    detail = client.get("/api/v2/admin/marketing/lead/test-bank-one",
                        headers=admin).get_json()
    emails = [i for i in detail["interactions"] if i["type"] == "email"]
    assert len(emails) == 1
    assert "scheduled@example.org" in emails[0]["summary"]
    assert detail["lead"]["outreach_status"] == "contacted"

    files = _eml_files(env["outbox"], "outreach_generic")
    assert len(files) == 1


# ---------------------------------------------------------------------------
# MarketingStore scheduled-outreach unit tests
# ---------------------------------------------------------------------------

def test_store_schedule_send_validation(env):
    from src.dashboard.marketing_store import MarketingStore

    store = MarketingStore(str(env["db"]))
    good_context = {"organization": "X"}
    base = {
        "lead_slug": "test-bank-one",
        "to_email": "a@b.org",
        "contact_name": None,
        "template": "outreach_generic",
        "context": good_context,
        "send_at": "2026-09-01T09:00",
    }
    assert store.schedule_send(**{**base, "to_email": "bad"}) is None
    assert store.schedule_send(**{**base, "lead_slug": "bad slug!"}) is None
    assert store.schedule_send(**{**base, "send_at": "not-a-date"}) is None
    assert store.schedule_send(**{**base, "send_at": "2026-09-01"}) is None
    assert store.schedule_send(**{**base, "template": "x" * 61}) is None


def test_store_mark_scheduled_sets_sent_at(env):
    from src.dashboard.marketing_store import MarketingStore

    store = MarketingStore(str(env["db"]))
    row = store.schedule_send(
        lead_slug="test-bank-one",
        to_email="a@b.org",
        contact_name=None,
        template="outreach_generic",
        context={},
        send_at="2026-09-01T09:00",
    )
    updated = store.mark_scheduled(row["id"], "sent")
    assert updated["status"] == "sent"
    assert updated["sent_at"] is not None


def test_store_cancel_refuses_non_scheduled_rows(env):
    from src.dashboard.marketing_store import MarketingStore

    store = MarketingStore(str(env["db"]))
    row = store.schedule_send(
        lead_slug="test-bank-one",
        to_email="a@b.org",
        contact_name=None,
        template="outreach_generic",
        context={},
        send_at="2026-09-01T09:00",
    )
    store.mark_scheduled(row["id"], "sent")
    assert store.cancel_scheduled(row["id"]) is None


# ---------------------------------------------------------------------------
# Hunter.io contact discovery
# ---------------------------------------------------------------------------

def test_domain_from_url_normalizes_input():
    from src.dashboard.hunter import domain_from_url

    assert domain_from_url("https://www.example.com/path?x=1") == "example.com"
    assert domain_from_url("http://example.com:8080/") == "example.com"
    assert domain_from_url("www.example.com") == "example.com"
    assert domain_from_url("example.com") == "example.com"
    assert domain_from_url("https://sub.example.co.uk/a") == "sub.example.co.uk"
    assert domain_from_url("") is None
    assert domain_from_url("not a url") is None
    assert domain_from_url("localhost") is None
    assert domain_from_url(None) is None


def test_store_add_contacts_validation_and_dedup(env):
    from src.dashboard.marketing_store import MarketingStore

    store = MarketingStore(str(env["db"]))
    # Bad emails are skipped.
    added = store.add_contacts("test-bank-one", [
        {"email": "bad-email", "name": "Bad", "confidence": 50},
        {"email": "", "name": "Empty"},
    ])
    assert added == 0

    added = store.add_contacts("test-bank-one", [
        {"email": "good@example.com", "name": "Good", "confidence": 90},
    ])
    assert added == 1

    # Duplicate (lead_slug, email) is ignored.
    added = store.add_contacts("test-bank-one", [
        {"email": "good@example.com", "name": "Duplicate", "confidence": 95},
    ])
    assert added == 0

    # Invalid slug returns None.
    assert store.add_contacts("bad slug!", [
        {"email": "x@example.com"},
    ]) is None


def test_store_list_contacts_orders_by_confidence(env):
    from src.dashboard.marketing_store import MarketingStore

    store = MarketingStore(str(env["db"]))
    store.add_contacts("test-bank-one", [
        {"email": "mid@example.com", "name": "Mid", "confidence": 50},
        {"email": "high@example.com", "name": "High", "confidence": 90},
        {"email": "none@example.com", "name": "None"},
    ])
    emails = [c["email"] for c in store.list_contacts("test-bank-one")]
    assert emails == ["high@example.com", "mid@example.com", "none@example.com"]


def test_store_delete_contact(env):
    from src.dashboard.marketing_store import MarketingStore

    store = MarketingStore(str(env["db"]))
    store.add_contacts("test-bank-one", [
        {"email": "del@example.com", "name": "To Delete", "confidence": 70},
    ])
    cid = store.list_contacts("test-bank-one")[0]["id"]
    deleted = store.delete_contact(cid)
    assert deleted["email"] == "del@example.com"
    assert store.delete_contact(cid) is None
    assert store.delete_contact("not-an-int") is None


@pytest.mark.usefixtures("sample_workspace")
def test_lead_contacts_requires_auth(client):
    assert client.get("/api/v2/admin/marketing/lead/test-bank-one/contacts").status_code == 401


@pytest.mark.usefixtures("sample_workspace")
def test_lead_contacts_requires_admin_role(client, env):
    plain = _make_user(client, env, "plain@example.org")
    assert client.get("/api/v2/admin/marketing/lead/test-bank-one/contacts",
                      headers=plain).status_code == 403


@pytest.mark.usefixtures("sample_workspace")
def test_lead_contacts_unknown_slug_is_404(client, env):
    admin = _make_user(client, env, "op@example.org", role="admin")
    assert client.get("/api/v2/admin/marketing/lead/no-such-lead/contacts",
                      headers=admin).status_code == 404


@pytest.mark.usefixtures("sample_workspace")
def test_lead_contacts_not_configured_returns_empty(client, env):
    admin = _make_user(client, env, "op@example.org", role="admin")
    resp = client.get("/api/v2/admin/marketing/lead/test-bank-one/contacts",
                      headers=admin)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["configured"] is False
    assert body["contacts"] == []


@pytest.mark.usefixtures("sample_workspace")
def test_discover_without_key_is_honest_and_adds_nothing(client, env):
    admin = _make_user(client, env, "op@example.org", role="admin")
    resp = client.post("/api/v2/admin/marketing/lead/test-bank-one/contacts/discover",
                       headers=admin)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["configured"] is False
    assert "Hunter.io is not configured" in body["note"]
    assert body["contacts"] == []

    # Nothing was stored.
    from src.dashboard.marketing_store import MarketingStore
    assert MarketingStore(str(env["db"])).list_contacts("test-bank-one") == []


@pytest.mark.usefixtures("sample_workspace")
def test_discover_with_mocked_hunter_adds_and_merges_contacts(client, env, monkeypatch):
    from src.dashboard import hunter
    from src.dashboard.marketing_store import MarketingStore

    admin = _make_user(client, env, "op@example.org", role="admin")
    store = MarketingStore(str(env["db"]))
    store.add_contacts("test-bank-one", [
        {"email": "existing@example.com", "name": "Existing", "confidence": 60},
    ])

    def _fake_search(domain):
        return [
            {"email": "existing@example.com", "name": "Existing Updated", "confidence": 90},
            {"email": "new@example.com", "name": "New Person", "confidence": 80,
             "position": "CEO", "department": "Executive"},
        ]

    monkeypatch.setattr(hunter, "configured", lambda: True)
    monkeypatch.setattr(hunter, "domain_search", _fake_search)

    resp = client.post("/api/v2/admin/marketing/lead/test-bank-one/contacts/discover",
                       headers=admin)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["configured"] is True
    assert body["domain"] == "testbankone.com"
    assert body["added"] == 1

    contacts = body["contacts"]
    assert len(contacts) == 2
    emails = {c["email"]: c for c in contacts}
    assert "existing@example.com" in emails
    assert "new@example.com" in emails
    assert emails["new@example.com"]["position"] == "CEO"

    # Lead detail also exposes contacts.
    detail = client.get("/api/v2/admin/marketing/lead/test-bank-one",
                        headers=admin).get_json()
    assert len(detail["contacts"]) == 2


@pytest.mark.usefixtures("sample_workspace")
def test_discover_hunter_error_returns_502(client, env, monkeypatch):
    from src.dashboard import hunter

    admin = _make_user(client, env, "op@example.org", role="admin")
    monkeypatch.setattr(hunter, "configured", lambda: True)
    monkeypatch.setattr(hunter, "domain_search",
                        lambda domain, limit=10: (_ for _ in ()).throw(
                            hunter.HunterError("Hunter.io quota exhausted")))

    resp = client.post("/api/v2/admin/marketing/lead/test-bank-one/contacts/discover",
                       headers=admin)
    assert resp.status_code == 502
    assert "quota exhausted" in resp.get_json()["error"]


@pytest.mark.usefixtures("sample_workspace")
def test_contact_delete_endpoint(client, env):
    from src.dashboard.marketing_store import MarketingStore

    admin = _make_user(client, env, "op@example.org", role="admin")
    store = MarketingStore(str(env["db"]))
    store.add_contacts("test-bank-one", [
        {"email": "tobedeleted@example.com", "name": "X", "confidence": 50},
    ])
    cid = store.list_contacts("test-bank-one")[0]["id"]

    resp = client.post(f"/api/v2/admin/marketing/contacts/{cid}/delete",
                       headers=admin)
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True

    assert client.post(f"/api/v2/admin/marketing/contacts/{cid}/delete",
                       headers=admin).status_code == 404


@pytest.mark.usefixtures("sample_workspace")
def test_discover_no_usable_domain_returns_422(client, env, monkeypatch):
    from src.dashboard import hunter

    admin = _make_user(client, env, "op@example.org", role="admin")
    # Pretend Hunter is configured so the endpoint reaches domain validation.
    monkeypatch.setattr(hunter, "configured", lambda: True)
    monkeypatch.setattr(hunter, "domain_search",
                        lambda domain, limit=10: (_ for _ in ()).throw(
                            AssertionError("should not be called without usable domain")))
    # Test Engineering Firm has no website in the fixture.
    resp = client.post(
        "/api/v2/admin/marketing/lead/test-engineering-firm/contacts/discover",
        headers=admin,
    )
    assert resp.status_code == 422
    assert "no usable domain" in resp.get_json()["error"]


# ---------------------------------------------------------------------------
# Hunter.io email finder + verifier
# ---------------------------------------------------------------------------

def test_email_finder_returns_contact_or_none(env, monkeypatch):
    from src.dashboard import hunter

    calls = []

    def _fake_urlopen(req, timeout=None):
        url = req.full_url
        calls.append(url)
        if "email-finder" in url and "Ada" in url and "Lovelace" in url:
            payload = {
                "data": {
                    "email": "ada@example.com",
                    "score": 95,
                    "sources": [{"uri": "http://example.com"}],
                    "verification": {"status": "valid"},
                }
            }
        elif "email-verifier" in url:
            payload = {
                "data": {
                    "email": "ada@example.com",
                    "score": 95,
                    "status": "valid",
                    "result": "deliverable",
                }
            }
        else:
            import urllib.error
            raise urllib.error.HTTPError(url, 404, "Not found", {}, None)

        class Resp:
            def read(self):
                return json.dumps(payload).encode("utf-8")

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False
        return Resp()

    monkeypatch.setenv("HUNTER_API_KEY", "test-key")
    monkeypatch.setattr(hunter.urllib.request, "urlopen", _fake_urlopen)

    found = hunter.email_finder("example.com", "Ada", "Lovelace")
    assert found["email"] == "ada@example.com"
    assert found["score"] == 95
    assert found["verification"] == "valid"

    verified = hunter.verify_email("ada@example.com")
    assert verified["result"] == "deliverable"


def test_email_finder_returns_none_on_404(env, monkeypatch):
    from src.dashboard import hunter

    def _fake_urlopen(req, timeout=None):
        import urllib.error
        raise urllib.error.HTTPError(req.full_url, 404, "Not found", {}, None)

    monkeypatch.setenv("HUNTER_API_KEY", "test-key")
    monkeypatch.setattr(hunter.urllib.request, "urlopen", _fake_urlopen)
    assert hunter.email_finder("example.com", "No", "Such") is None


def test_hunter_quota_alert_once_per_episode(env, monkeypatch, tmp_path):
    """429 → operator emailed once; a successful call re-arms the alert."""
    import urllib.error

    from src.dashboard import hunter, mailer

    monkeypatch.setenv("HUNTER_API_KEY", "test-key")
    monkeypatch.setenv("HUNTER_QUOTA_GUARD_FILE", str(tmp_path / "guard.json"))
    alerts = []
    monkeypatch.setattr(
        mailer, "operator_notify", lambda *args, **kwargs: alerts.append(args)
    )

    def _quota_urlopen(req, timeout=None):
        raise urllib.error.HTTPError(
            req.full_url, 429, "Too Many Requests", {}, None)

    monkeypatch.setattr(hunter.urllib.request, "urlopen", _quota_urlopen)
    for _ in range(2):
        with pytest.raises(hunter.HunterError, match="quota exhausted"):
            hunter.verify_email("ada@example.com")
    assert len(alerts) == 1  # once per episode, not per failure

    def _ok_urlopen(req, timeout=None):
        class Resp:
            def read(self):
                return json.dumps({"data": {
                    "email": "ada@example.com",
                    "score": 90,
                    "status": "valid",
                    "result": "deliverable",
                }}).encode("utf-8")

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False
        return Resp()

    monkeypatch.setattr(hunter.urllib.request, "urlopen", _ok_urlopen)
    assert hunter.verify_email("ada@example.com")["result"] == "deliverable"

    monkeypatch.setattr(hunter.urllib.request, "urlopen", _quota_urlopen)
    with pytest.raises(hunter.HunterError, match="quota exhausted"):
        hunter.verify_email("ada@example.com")
    assert len(alerts) == 2  # quota returned then ran out again — new alert


def test_hunter_quota_alert_failure_does_not_break_lookup(env, monkeypatch, tmp_path):
    """A failing alert channel must not change the HunterError contract."""
    import urllib.error

    from src.dashboard import hunter, mailer

    monkeypatch.setenv("HUNTER_API_KEY", "test-key")
    monkeypatch.setenv("HUNTER_QUOTA_GUARD_FILE", str(tmp_path / "guard.json"))

    def _boom(*args, **kwargs):
        raise RuntimeError("smtp down")

    monkeypatch.setattr(mailer, "operator_notify", _boom)

    def _quota_urlopen(req, timeout=None):
        raise urllib.error.HTTPError(
            req.full_url, 429, "Too Many Requests", {}, None)

    monkeypatch.setattr(hunter.urllib.request, "urlopen", _quota_urlopen)
    with pytest.raises(hunter.HunterError, match="quota exhausted"):
        hunter.verify_email("ada@example.com")


# ---------------------------------------------------------------------------
# MarketingStore auto-send / unsubscribe / verification / daily count
# ---------------------------------------------------------------------------

def test_store_auto_send_unsubscribe_and_verification(env):
    from src.dashboard.marketing_store import MarketingStore

    store = MarketingStore(str(env["db"]))
    store.add_contacts("test-bank-one", [
        {"email": "x@example.com", "name": "X", "confidence": 80},
    ])

    assert store.set_auto_send("test-bank-one", True) is True
    state = store.get_state("test-bank-one")
    assert state["auto_send"] is True

    assert store.set_auto_send("test-bank-one", False) is True
    state = store.get_state("test-bank-one")
    assert state["auto_send"] is False

    assert store.unsubscribe("test-bank-one", "asked to stop") is True
    assert store.is_unsubscribed("test-bank-one") is True
    state = store.get_state("test-bank-one")
    assert state["unsub_reason"] == "asked to stop"

    cid = store.list_contacts("test-bank-one")[0]["id"]
    updated = store.set_contact_verification(cid, "valid")
    assert updated["verification"] == "valid"
    assert store.get_contact(cid)["verification"] == "valid"


def test_store_sent_today_count(env):
    from src.dashboard.marketing_store import MarketingStore

    store = MarketingStore(str(env["db"]))
    assert store.sent_today_count() == 0

    store.add_interaction("test-bank-one", "Outreach email to a@b.org", type="email")
    assert store.sent_today_count() == 1

    store.schedule_send(
        lead_slug="test-bank-two",
        to_email="b@c.org",
        contact_name=None,
        template="outreach_generic",
        context={},
        send_at="2026-09-01T09:00",
    )
    # scheduled rows do not count until marked sent
    assert store.sent_today_count() == 1


# ---------------------------------------------------------------------------
# CRM auto-send / unsubscribe / preview
# ---------------------------------------------------------------------------

@pytest.mark.usefixtures("sample_workspace")
def test_auto_send_toggle(client, env):
    admin = _make_user(client, env, "op@example.org", role="admin")
    resp = client.post(
        "/api/v2/admin/marketing/lead/test-bank-one/auto-send",
        headers=admin,
        json={"enabled": True},
    )
    assert resp.status_code == 200
    assert resp.get_json()["auto_send"] is True

    detail = client.get("/api/v2/admin/marketing/lead/test-bank-one",
                        headers=admin).get_json()
    assert detail["lead"]["auto_send"] is True


@pytest.mark.usefixtures("sample_workspace")
def test_unsubscribe_blocks_send_and_schedule(client, env):
    admin = _make_user(client, env, "op@example.org", role="admin")
    resp = client.post(
        "/api/v2/admin/marketing/lead/test-bank-one/unsubscribe",
        headers=admin,
        json={"reason": "opted out"},
    )
    assert resp.status_code == 200
    assert resp.get_json()["unsubscribed"] is True

    send = client.post(
        "/api/v2/admin/marketing/lead/test-bank-one/send",
        headers=admin,
        json={"to_email": "contact@example.org"},
    )
    assert send.status_code == 400
    assert "unsubscribed" in send.get_json()["error"]

    future = (datetime.utcnow() + timedelta(days=1)).isoformat() + "Z"
    schedule = client.post(
        "/api/v2/admin/marketing/lead/test-bank-one/schedule",
        headers=admin,
        json={"to_email": "later@example.org", "send_at": future},
    )
    assert schedule.status_code == 400
    assert "unsubscribed" in schedule.get_json()["error"]


@pytest.mark.usefixtures("sample_workspace")
def test_preview_returns_rendered_template(client, env):
    admin = _make_user(client, env, "op@example.org", role="admin")
    resp = client.post(
        "/api/v2/admin/marketing/lead/test-bank-one/preview",
        headers=admin,
        json={"contact_name": "Ada"},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert "Test Bank One" in body["subject"]
    assert "Test Bank One" in body["body"]
    assert "Ada" in body["body"]


# ---------------------------------------------------------------------------
# CRM find-email / verify-email / bulk discover
# ---------------------------------------------------------------------------

@pytest.mark.usefixtures("sample_workspace")
def test_find_email_stores_contact(client, env, monkeypatch):
    from src.dashboard import hunter

    admin = _make_user(client, env, "op@example.org", role="admin")

    def _fake_finder(domain, first, last):
        return {
            "email": f"{first.lower()}.{last.lower()}@testbankone.com",
            "score": 90,
            "sources": [],
            "verification": "valid",
        }

    monkeypatch.setattr(hunter, "configured", lambda: True)
    monkeypatch.setattr(hunter, "email_finder", _fake_finder)

    resp = client.post(
        "/api/v2/admin/marketing/lead/test-bank-one/find-email",
        headers=admin,
        json={"first_name": "Ada", "last_name": "Lovelace"},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["found"] is True
    assert data["contact"]["email"] == "ada.lovelace@testbankone.com"

    contacts = client.get(
        "/api/v2/admin/marketing/lead/test-bank-one/contacts",
        headers=admin,
    ).get_json()["contacts"]
    assert any(c["email"] == "ada.lovelace@testbankone.com" for c in contacts)


@pytest.mark.usefixtures("sample_workspace")
def test_verify_email_endpoint_updates_contact(client, env, monkeypatch):
    from src.dashboard import hunter
    from src.dashboard.marketing_store import MarketingStore

    admin = _make_user(client, env, "op@example.org", role="admin")
    store = MarketingStore(str(env["db"]))
    store.add_contacts("test-bank-one", [
        {"email": "check@example.com", "name": "Check", "confidence": 70},
    ])
    cid = store.list_contacts("test-bank-one")[0]["id"]

    monkeypatch.setattr(hunter, "configured", lambda: True)
    monkeypatch.setattr(hunter, "verify_email",
                        lambda email: {"email": email, "score": 80, "result": "deliverable", "status": "valid"})

    resp = client.post(
        f"/api/v2/admin/marketing/contacts/{cid}/verify",
        headers=admin,
    )
    assert resp.status_code == 200
    assert resp.get_json()["verification"]["result"] == "deliverable"
    assert store.get_contact(cid)["verification"] == "deliverable"


@pytest.mark.usefixtures("sample_workspace")
def test_bulk_discover_adds_contacts_to_multiple_leads(client, env, monkeypatch):
    from src.dashboard import hunter

    admin = _make_user(client, env, "op@example.org", role="admin")

    def _fake_search(domain):
        return [{"email": f"contact@{domain}", "name": "Contact", "confidence": 80}]

    monkeypatch.setattr(hunter, "configured", lambda: True)
    monkeypatch.setattr(hunter, "domain_search", _fake_search)

    resp = client.post(
        "/api/v2/admin/marketing/tree/discover",
        headers=admin,
        json={"segment": "banking", "country": "US"},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    # Only Test Bank One has a website in the fixture; Test Bank Two does not.
    assert data["added"] == 1
    assert data["leads"] == 2
    assert data["domains"] == ["testbankone.com"]


# ---------------------------------------------------------------------------
# Daily cap enforcement
# ---------------------------------------------------------------------------

@pytest.mark.usefixtures("sample_workspace")
def test_send_rejects_when_daily_cap_reached(client, env, monkeypatch):
    from src.dashboard import marketing_crm

    admin = _make_user(client, env, "op@example.org", role="admin")
    monkeypatch.setattr(marketing_crm, "_DAILY_SEND_CAP", 1)

    # First send consumes the cap.
    r1 = client.post(
        "/api/v2/admin/marketing/lead/test-bank-one/send",
        headers=admin,
        json={"to_email": "one@example.org"},
    )
    assert r1.status_code == 200

    r2 = client.post(
        "/api/v2/admin/marketing/lead/test-bank-two/send",
        headers=admin,
        json={"to_email": "two@example.org"},
    )
    assert r2.status_code == 429
    assert "cap" in r2.get_json()["error"].lower()


@pytest.mark.usefixtures("sample_workspace")
def test_processor_leaves_pending_when_cap_reached(client, env, monkeypatch):
    from src.dashboard.marketing_store import MarketingStore

    admin = _make_user(client, env, "op@example.org", role="admin")
    store = MarketingStore(str(env["db"]))

    script_path = Path(__file__).resolve().parent.parent / "scripts" / "process_scheduled_outreach.py"
    spec = importlib.util.spec_from_file_location("process_scheduled_outreach", str(script_path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    # Cap of 1; first scheduled row will consume it, second must stay pending.
    monkeypatch.setattr(mod, "_DAILY_SEND_CAP", 1)

    past = (datetime.utcnow() - timedelta(hours=1)).isoformat()[:19]
    row1 = store.schedule_send(
        lead_slug="test-bank-one",
        to_email="first@example.org",
        contact_name="First",
        template="outreach_generic",
        context={"organization": "Test Bank One"},
        send_at=past,
    )
    row2 = store.schedule_send(
        lead_slug="test-bank-two",
        to_email="second@example.org",
        contact_name="Second",
        template="outreach_generic",
        context={"organization": "Test Bank Two"},
        send_at=past,
    )

    assert mod.main() == 0

    assert store.get_scheduled(row1["id"])["status"] == "sent"
    assert store.get_scheduled(row2["id"])["status"] == "scheduled"


@pytest.mark.usefixtures("sample_workspace")
def test_processor_skips_unsubscribed_lead(client, env):
    from src.dashboard.marketing_store import MarketingStore

    admin = _make_user(client, env, "op@example.org", role="admin")
    store = MarketingStore(str(env["db"]))
    store.unsubscribe("test-bank-one")

    past = (datetime.utcnow() - timedelta(hours=1)).isoformat()[:19]
    row = store.schedule_send(
        lead_slug="test-bank-one",
        to_email="skip@example.org",
        contact_name="Skip",
        template="outreach_generic",
        context={"organization": "Test Bank One"},
        send_at=past,
    )

    script_path = Path(__file__).resolve().parent.parent / "scripts" / "process_scheduled_outreach.py"
    spec = importlib.util.spec_from_file_location("process_scheduled_outreach", str(script_path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.main() == 0

    updated = store.get_scheduled(row["id"])
    assert updated["status"] == "skipped_unsubscribed"

    detail = client.get("/api/v2/admin/marketing/lead/test-bank-one",
                        headers=admin).get_json()
    assert not any(i["type"] == "email" for i in detail["interactions"])


# ---------------------------------------------------------------------------
# Pre-send Hunter.io verification layer (send_plan §7.1)
# ---------------------------------------------------------------------------

def _load_processor():
    script_path = Path(__file__).resolve().parent.parent / "scripts" / "process_scheduled_outreach.py"
    spec = importlib.util.spec_from_file_location("process_scheduled_outreach", str(script_path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _due_past():
    return (datetime.utcnow() - timedelta(hours=1)).isoformat()[:19]


def _schedule_one(store, to_email):
    return store.schedule_send(
        lead_slug="test-bank-one",
        to_email=to_email,
        contact_name="Test",
        template="outreach_generic",
        context={"organization": "Test Bank One"},
        send_at=_due_past(),
    )


def test_processor_skips_undeliverable_recipient(env, monkeypatch):
    from src.dashboard.marketing_store import MarketingStore

    store = MarketingStore(str(env["db"]))
    store.add_contacts("test-bank-one", [
        {"email": "gone@example.org", "name": "Gone", "confidence": 90},
    ])
    row = _schedule_one(store, "gone@example.org")

    mod = _load_processor()
    monkeypatch.setenv("HUNTER_API_KEY", "test-key")
    monkeypatch.setattr(mod.hunter, "verify_email", lambda email: {
        "email": email, "score": 2, "status": "invalid", "result": "undeliverable",
    })

    assert mod.main() == 0
    assert store.get_scheduled(row["id"])["status"] == "skipped_undeliverable"
    cid = store.list_contacts("test-bank-one")[0]["id"]
    assert store.get_contact(cid)["verification"] == "undeliverable"
    assert not _eml_files(env["outbox"], "outreach_generic")


def test_processor_persists_verdict_and_sends(env, monkeypatch):
    from src.dashboard.marketing_store import MarketingStore

    store = MarketingStore(str(env["db"]))
    store.add_contacts("test-bank-one", [
        {"email": "ok@example.org", "name": "Ok", "confidence": 90},
    ])
    row = _schedule_one(store, "ok@example.org")

    mod = _load_processor()
    monkeypatch.setenv("HUNTER_API_KEY", "test-key")
    monkeypatch.setattr(mod.hunter, "verify_email", lambda email: {
        "email": email, "score": 95, "status": "valid", "result": "deliverable",
    })

    assert mod.main() == 0
    assert store.get_scheduled(row["id"])["status"] == "sent"
    cid = store.list_contacts("test-bank-one")[0]["id"]
    assert store.get_contact(cid)["verification"] == "deliverable"
    assert len(_eml_files(env["outbox"], "outreach_generic")) == 1


def test_processor_fail_open_when_hunter_errors(env, monkeypatch):
    from src.dashboard.marketing_store import MarketingStore

    store = MarketingStore(str(env["db"]))
    row = _schedule_one(store, "unverified@example.org")

    mod = _load_processor()
    monkeypatch.setenv("HUNTER_API_KEY", "test-key")

    def _boom(email):
        raise mod.hunter.HunterError("Hunter.io quota exhausted")

    monkeypatch.setattr(mod.hunter, "verify_email", _boom)

    assert mod.main() == 0
    assert store.get_scheduled(row["id"])["status"] == "sent"


def test_processor_stored_invalid_blocks_without_key(env, monkeypatch):
    """Stored hard-fail verdicts are honored even with Hunter unconfigured."""
    from src.dashboard.marketing_store import MarketingStore

    store = MarketingStore(str(env["db"]))
    store.add_contacts("test-bank-one", [
        {"email": "dead@example.org", "name": "Dead", "confidence": 90},
    ])
    cid = store.list_contacts("test-bank-one")[0]["id"]
    store.set_contact_verification(cid, "invalid")
    row = _schedule_one(store, "dead@example.org")

    mod = _load_processor()  # no HUNTER_API_KEY in env
    assert mod.main() == 0
    assert store.get_scheduled(row["id"])["status"] == "skipped_undeliverable"
    assert not _eml_files(env["outbox"], "outreach_generic")


def test_processor_wave_falls_through_to_next_contact(env, monkeypatch):
    from src.dashboard.marketing_store import MarketingStore

    store = MarketingStore(str(env["db"]))
    store.add_contacts("test-bank-one", [
        {"email": "dead@example.org", "name": "Dead", "confidence": 95},
        {"email": "live@example.org", "name": "Live", "confidence": 80},
    ])
    wave = store.enqueue_wave(
        "testcamp", "test-bank-one", 1, "outreach_generic",
        {"organization": "Test Bank One"}, _due_past(),
    )

    mod = _load_processor()
    monkeypatch.setenv("HUNTER_API_KEY", "test-key")

    def _fake_verify(email):
        if email == "dead@example.org":
            return {"email": email, "score": 1, "status": "invalid",
                    "result": "undeliverable"}
        return {"email": email, "score": 90, "status": "valid",
                "result": "deliverable"}

    monkeypatch.setattr(mod.hunter, "verify_email", _fake_verify)

    assert mod.main() == 0
    assert store.get_wave(wave["id"])["status"] == "sent"
    verdicts = {c["email"]: c["verification"]
                for c in store.list_contacts("test-bank-one")}
    assert verdicts["dead@example.org"] == "undeliverable"
    assert verdicts["live@example.org"] == "deliverable"
    files = _eml_files(env["outbox"], "outreach_generic")
    assert len(files) == 1
    assert "live@example.org" in files[0].read_text()


# ---------------------------------------------------------------------------
# Talaix email-discovery endpoints
# ---------------------------------------------------------------------------

@pytest.mark.usefixtures("sample_workspace")
def test_discover_own_stores_observed_contacts(client, env, monkeypatch):
    from src.dashboard import email_discovery

    admin = _make_user(client, env, "op@example.org", role="admin")

    def _fake_discover(domain, **kwargs):
        return {
            "domain": domain,
            "contacts": [
                {"email": "team@example.com", "type": "role", "source_url": f"https://{domain}/contact",
                 "found_on": "/contact", "claim_status": "OBSERVED", "confidence": 0.9},
                {"email": "ada.lovelace@example.com", "type": "personal", "source_url": f"https://{domain}/team",
                 "found_on": "/team", "claim_status": "OBSERVED", "confidence": 0.85},
            ],
            "pages_fetched": 2,
            "robots_respected": True,
            "note": "test note",
        }

    monkeypatch.setattr(email_discovery, "discover_emails", _fake_discover)

    resp = client.post(
        "/api/v2/admin/marketing/lead/test-bank-one/contacts/discover-own",
        headers=admin,
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["added"] == 2
    assert body["domain"] == "testbankone.com"

    contacts = {c["email"]: c for c in body["contacts"]}
    assert "team@example.com" in contacts
    assert contacts["team@example.com"]["source"] == "talaix-discovery"
    assert contacts["team@example.com"]["verification"] == "OBSERVED"


@pytest.mark.usefixtures("sample_workspace")
def test_discover_own_returns_400_without_website(client, env):
    admin = _make_user(client, env, "op@example.org", role="admin")
    # Test Engineering Firm has no website in the fixture.
    resp = client.post(
        "/api/v2/admin/marketing/lead/test-engineering-firm/contacts/discover-own",
        headers=admin,
    )
    assert resp.status_code == 400
    assert "no usable domain" in resp.get_json()["error"]


@pytest.mark.usefixtures("sample_workspace")
def test_infer_email_stores_inferred_contact(client, env, monkeypatch):
    from src.dashboard import email_discovery

    admin = _make_user(client, env, "op@example.org", role="admin")

    def _fake_find(domain, first_name, last_name, known_emails=None):
        return {
            "email": f"{first_name.lower()}.{last_name.lower()}@testbankone.com",
            "claim_status": "INFERRED",
            "pattern": "first.last",
            "basis": "pattern from 2 observed emails at the domain",
            "confidence": 0.6,
        }

    monkeypatch.setattr(email_discovery, "find_for_person", _fake_find)

    resp = client.post(
        "/api/v2/admin/marketing/lead/test-bank-one/contacts/infer-email",
        headers=admin,
        json={"first_name": "Ada", "last_name": "Lovelace"},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["found"] is True
    assert body["claim_status"] == "INFERRED"
    assert body["email"] == "ada.lovelace@testbankone.com"

    contacts = {c["email"]: c for c in body["contacts"]}
    assert contacts["ada.lovelace@testbankone.com"]["source"] == "talaix-inference"
    assert "INFERRED" in contacts["ada.lovelace@testbankone.com"]["verification"]
    assert "verify before sending" in contacts["ada.lovelace@testbankone.com"]["position"]


@pytest.mark.usefixtures("sample_workspace")
def test_infer_email_returns_unknown_without_storing(client, env, monkeypatch):
    from src.dashboard import email_discovery

    admin = _make_user(client, env, "op@example.org", role="admin")
    monkeypatch.setattr(email_discovery, "find_for_person",
                        lambda d, f, l, known_emails=None: {"email": None, "claim_status": "UNKNOWN", "reason": "no pattern"})

    resp = client.post(
        "/api/v2/admin/marketing/lead/test-bank-one/contacts/infer-email",
        headers=admin,
        json={"first_name": "Ada", "last_name": "Lovelace"},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["found"] is False
    assert body["claim_status"] == "UNKNOWN"

    # Nothing was stored.
    detail = client.get("/api/v2/admin/marketing/lead/test-bank-one",
                        headers=admin).get_json()
    assert detail["contacts"] == []


@pytest.mark.usefixtures("sample_workspace")
def test_tree_discover_own_bulk_respects_cap(client, env, monkeypatch):
    from src.dashboard import email_discovery

    admin = _make_user(client, env, "op@example.org", role="admin")

    calls = []

    def _fake_discover(domain, **kwargs):
        calls.append((domain, kwargs))
        return {
            "domain": domain,
            "contacts": [{"email": f"contact@{domain}", "type": "role",
                          "source_url": f"https://{domain}/", "found_on": "/",
                          "claim_status": "OBSERVED", "confidence": 0.8}],
            "pages_fetched": 1,
            "robots_respected": True,
            "note": "",
        }

    monkeypatch.setattr(email_discovery, "discover_emails", _fake_discover)

    resp = client.post(
        "/api/v2/admin/marketing/tree/discover-own",
        headers=admin,
        json={"segment": "banking", "country": "US"},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["leads"] == 2  # Test Bank One + Test Bank Two
    assert body["processed"] == 1  # only Test Bank One has a website
    assert body["added"] == 1
    assert body["skipped"] == 1

    # max_pages=8 passed for bulk politeness.
    assert calls[0][1].get("max_pages") == 8


@pytest.mark.usefixtures("sample_workspace")
def test_discover_own_rate_limit(client, env, monkeypatch):
    from src.dashboard import marketing_crm

    admin = _make_user(client, env, "op@example.org", role="admin")

    # Tighten rate limit so the second request is blocked.
    monkeypatch.setattr(marketing_crm._email_discovery_limiter, "allow",
                        lambda key, max_requests, window_seconds: False)

    resp = client.post(
        "/api/v2/admin/marketing/lead/test-bank-one/contacts/discover-own",
        headers=admin,
    )
    assert resp.status_code == 429
    assert "Rate limit" in resp.get_json()["error"]


# ---------------------------------------------------------------------------
# Replies and campaigns (Phase 18)
# ---------------------------------------------------------------------------

@pytest.mark.usefixtures("sample_workspace")
def test_replies_endpoint_requires_auth(client):
    assert client.get("/api/v2/admin/marketing/replies").status_code == 401


@pytest.mark.usefixtures("sample_workspace")
def test_replies_endpoint_returns_reply_interactions(client, env):
    from src.dashboard.marketing_store import MarketingStore

    admin = _make_user(client, env, "op@example.org", role="admin")
    store = MarketingStore(str(env["db"]))
    store.add_interaction("test-bank-one", "Reply from a@b.org", type="reply")
    store.add_interaction("test-bank-one", "Unsub request", type="unsubscribe")
    store.add_interaction("test-bank-two", "Plain note", type="note")

    resp = client.get("/api/v2/admin/marketing/replies", headers=admin)
    assert resp.status_code == 200
    body = resp.get_json()
    assert "replies" in body
    summaries = [r["summary"] for r in body["replies"]]
    assert "Reply from a@b.org" in summaries
    assert "Unsub request" in summaries
    assert "Plain note" not in summaries


@pytest.mark.usefixtures("sample_workspace")
def test_campaigns_endpoints_require_auth(client):
    assert client.get("/api/v2/admin/marketing/campaigns").status_code == 401
    assert client.get("/api/v2/admin/marketing/campaigns/test-campaign").status_code == 401
    assert client.post("/api/v2/admin/marketing/campaigns/start", json={}).status_code == 401


@pytest.mark.usefixtures("sample_workspace")
def test_campaigns_endpoint_returns_stats(client, env):
    from src.dashboard.marketing_store import MarketingStore

    admin = _make_user(client, env, "op@example.org", role="admin")
    store = MarketingStore(str(env["db"]))
    store.enqueue_wave("q4-2026", "test-bank-one", 1, "followup_1", {}, "2026-09-01T09:00")

    resp = client.get("/api/v2/admin/marketing/campaigns", headers=admin)
    assert resp.status_code == 200
    body = resp.get_json()
    assert "campaigns" in body
    assert len(body["campaigns"]) == 1
    assert body["campaigns"][0]["campaign"] == "q4-2026"


@pytest.mark.usefixtures("sample_workspace")
def test_campaign_detail_endpoint(client, env):
    from src.dashboard.marketing_store import MarketingStore

    admin = _make_user(client, env, "op@example.org", role="admin")
    store = MarketingStore(str(env["db"]))
    store.enqueue_wave("q4-2026", "test-bank-one", 1, "followup_1", {}, "2026-09-01T09:00")

    resp = client.get("/api/v2/admin/marketing/campaigns/q4-2026", headers=admin)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["campaign"]["campaign"] == "q4-2026"
    assert body["campaign"]["waves"][0]["wave"] == 1

    assert client.get("/api/v2/admin/marketing/campaigns/no-such-campaign",
                      headers=admin).status_code == 404


@pytest.mark.usefixtures("sample_workspace")
def test_campaign_start_endpoint_validation(client, env):
    admin = _make_user(client, env, "op@example.org", role="admin")

    resp = client.post("/api/v2/admin/marketing/campaigns/start", headers=admin, json={})
    assert resp.status_code == 400
    assert "campaign" in resp.get_json()["error"]

    resp = client.post("/api/v2/admin/marketing/campaigns/start", headers=admin, json={
        "campaign": "x", "wave": 0, "template": "followup_1"})
    assert resp.status_code == 400
    assert "wave" in resp.get_json()["error"]

    resp = client.post("/api/v2/admin/marketing/campaigns/start", headers=admin, json={
        "campaign": "x", "wave": 1, "template": "bad_template"})
    assert resp.status_code == 400
    assert "template" in resp.get_json()["error"]


@pytest.mark.usefixtures("sample_workspace")
def test_campaign_start_endpoint_enqueues_wave(client, env):
    from src.dashboard.marketing_store import MarketingStore

    admin = _make_user(client, env, "op@example.org", role="admin")
    store = MarketingStore(str(env["db"]))
    store.add_contacts("test-bank-one", [{"email": "contact@testbankone.com"}])

    resp = client.post("/api/v2/admin/marketing/campaigns/start", headers=admin, json={
        "campaign": "q4-2026",
        "wave": 1,
        "template": "followup_1",
        "filters": {"country": "US"},
        "delay_days": 0.5,
    })
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["enqueued"] == 1
    assert body["leads"] == ["test-bank-one"]

    stats = store.campaign_stats(campaign="q4-2026")[0]
    assert stats["leads"][0]["slug"] == "test-bank-one"
