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
    # Sorted by count desc, then key asc; zero-count sectors omitted.
    assert [s["key"] for s in sectors] == [
        "banking", "engineering_firms", "governments", "insurance",
    ]
    by_key = {s["key"]: s for s in sectors}
    # Target sectors keep their nicer labels; non-target segments are first-class.
    assert by_key["banking"]["label"] == "Banks & lenders"
    assert by_key["engineering_firms"]["label"] == "Engineering Firms"
    # Excluded lead is omitted; municipalities roll into governments.
    assert by_key["banking"]["count"] == 2
    assert by_key["insurance"]["count"] == 1
    assert by_key["governments"]["count"] == 1
    assert by_key["engineering_firms"]["count"] == 1


@pytest.mark.usefixtures("sample_workspace")
def test_tree_segment_returns_countries(client, env):
    admin = _make_user(client, env, "op@example.org", role="admin")
    resp = client.get("/api/v2/admin/marketing/tree?segment=banking", headers=admin)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["segment"] == "banking"
    assert "countries" in body and "statuses" not in body and "leads" not in body
    assert body["countries"] == [{"country": "US", "count": 2}]


@pytest.mark.usefixtures("sample_workspace")
def test_tree_parent_params_required(client, env):
    admin = _make_user(client, env, "op@example.org", role="admin")
    # Country without segment.
    assert client.get("/api/v2/admin/marketing/tree?country=US",
                      headers=admin).status_code == 400
    # Status without country.
    assert client.get("/api/v2/admin/marketing/tree?segment=banking&status=researched",
                      headers=admin).status_code == 400


@pytest.mark.usefixtures("sample_workspace")
def test_tree_segment_country_returns_statuses_and_all_leads(client, env):
    admin = _make_user(client, env, "op@example.org", role="admin")
    resp = client.get("/api/v2/admin/marketing/tree?segment=banking&country=US",
                      headers=admin)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["statuses"] == [
        {"status": "researched", "count": 1},
        {"status": "qualified", "count": 1},
    ]
    # All leads in the intersection are returned, unfiltered by status.
    assert len(body["leads"]) == 2
    by_slug = {l["slug"]: l for l in body["leads"]}
    assert by_slug["test-bank-one"]["outreach_status"] == "researched"
    assert by_slug["test-bank-two"]["outreach_status"] == "qualified"
    for lead in body["leads"]:
        assert "score" in lead and "recommended_product" in lead


@pytest.mark.usefixtures("sample_workspace")
def test_tree_full_path_filters_leads_by_status(client, env):
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
    assert lead["organization"] == "Test Bank One"
    assert lead["priority"] == "high"
    assert lead["score"] == 85  # high priority (50) + high urgency (35) + researched (0)
    assert lead["outreach_status"] == "researched"
    assert "recommended_product" in lead


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
