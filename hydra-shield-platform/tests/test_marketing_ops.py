"""Offline tests for marketing operations (the operator works the pipeline
from the Commercial Center).

Covers: the marketing_store overlay (validation, sparse upserts,
interaction log), the admin endpoints (gating, validation, audit), and the
intel overlay — a DB-stored status change must surface in /api/v2/admin/intel
without touching the read-only workspace files.
"""

import os
import sqlite3

import pytest

os.environ["HYDRASHIELD_CACHE_DB"] = "/tmp/hydrashield_test_mktops.sqlite3"
if os.path.exists(os.environ["HYDRASHIELD_CACHE_DB"]):
    os.remove(os.environ["HYDRASHIELD_CACHE_DB"])


@pytest.fixture()
def env(tmp_path, monkeypatch):
    db_path = tmp_path / "api.sqlite3"
    monkeypatch.setenv("HYDRASHIELD_CACHE_DB", str(db_path))
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


# ---------------------------------------------------------------------------
# Store behaviour
# ---------------------------------------------------------------------------

def test_store_sparse_upsert_and_validation(env):
    from src.dashboard.marketing_store import MarketingStore

    store = MarketingStore(str(env["db"]))
    assert store.update_state("aecom", outreach_status="bogus") is None
    assert store.update_state("aecom", status="maybe") is None
    assert store.update_state("bad slug!", outreach_status="contacted") is None
    assert store.update_state("aecom", unknown_field="x") is None

    st = store.update_state("aecom", outreach_status="contacted")
    assert st["outreach_status"] == "contacted" and st["status"] is None
    st = store.update_state("aecom", status="won", next_followup="2026-09-01")
    assert st["outreach_status"] == "contacted"  # earlier field kept
    assert st["status"] == "won"
    assert st["next_followup"] == "2026-09-01"
    assert store.update_state("aecom", next_followup="01-09-2026") is None


def test_store_interaction_log(env):
    from src.dashboard.marketing_store import MarketingStore

    store = MarketingStore(str(env["db"]))
    assert store.add_interaction("aecom", "") is None
    assert store.add_interaction("aecom", "x", type="smoke-signal") is None
    ok = store.add_interaction("aecom", "Sent the screening proposal",
                               type="email", date="2026-08-23")
    assert ok["type"] == "email"
    listed = store.list_interactions("aecom")
    assert len(listed) == 1 and listed[0]["summary"].startswith("Sent")
    assert store.list_interactions("other-org") == []


# ---------------------------------------------------------------------------
# Endpoint gating + validation + audit
# ---------------------------------------------------------------------------

def test_lead_ops_require_admin(client, env):
    assert client.patch("/api/v2/admin/leads/aecom", json={}).status_code == 401
    plain = _make_user(client, env, "plain@example.org")
    assert client.patch("/api/v2/admin/leads/aecom", headers=plain,
                        json={"status": "won"}).status_code == 403
    assert client.post("/api/v2/admin/leads/aecom/interactions",
                       headers=plain, json={"summary": "hi"}).status_code == 403


def test_lead_update_validation(client, env):
    admin = _make_user(client, env, "op@example.org", role="admin")
    assert client.patch("/api/v2/admin/leads/aecom", headers=admin,
                        json={"outreach_status": "bogus"}).status_code == 400
    assert client.patch("/api/v2/admin/leads/aecom", headers=admin,
                        json={}).status_code == 400


def test_lead_update_and_interaction_are_audited(client, env):
    admin = _make_user(client, env, "op@example.org", role="admin")
    resp = client.patch("/api/v2/admin/leads/aecom", headers=admin,
                        json={"outreach_status": "contacted"})
    assert resp.status_code == 200
    assert resp.get_json()["lead"]["outreach_status"] == "contacted"

    resp = client.post("/api/v2/admin/leads/aecom/interactions", headers=admin,
                       json={"type": "call", "summary": "Intro call with the CIO"})
    assert resp.status_code == 201

    from src.dashboard.accounts import UserStore

    actions = [r["action"] for r in UserStore(str(env["db"])).list_audit()]
    assert "lead_update" in actions and "lead_interaction" in actions


# ---------------------------------------------------------------------------
# The overlay surfaces in the intel payload (workspace files untouched)
# ---------------------------------------------------------------------------

def test_intel_reflects_operator_working_state(client, env):
    admin = _make_user(client, env, "op@example.org", role="admin")
    client.patch("/api/v2/admin/leads/aecom", headers=admin,
                 json={"outreach_status": "opportunity", "status": "won"})
    client.post("/api/v2/admin/leads/aecom/interactions", headers=admin,
                json={"type": "demo", "summary": "Platform demo delivered"})

    resp = client.get("/api/v2/admin/intel", headers=admin)
    assert resp.status_code == 200
    leads = resp.get_json()["workspace"]["leads"]
    aecom = next(l for l in leads if l["id"] == "aecom")
    assert aecom["outreach_status"] == "opportunity"
    assert aecom["status"] == "won"
    assert any(i.get("type") == "demo" for i in aecom["interactions"])

    # The workspace file itself is untouched (research base stays intact).
    import json as _json

    path = os.path.join(os.path.dirname(__file__), "..", "marketing",
                        "leads", "aecom.json")
    with open(path, encoding="utf-8") as fh:
        raw = _json.load(fh)
    assert raw.get("outreach_status", "researched") != "opportunity" or \
        raw.get("status", "open") != "won"


# ---------------------------------------------------------------------------
# Segmentation (sector × country)
# ---------------------------------------------------------------------------

def test_segmentation_covers_six_target_sectors(client, env):
    admin = _make_user(client, env, "op@example.org", role="admin")
    resp = client.get("/api/v2/admin/intel", headers=admin)
    seg = resp.get_json()["segmentation"]
    labels = [s["label"] for s in seg]
    assert labels == ["Banks & lenders", "Consultants", "Investors",
                      "Insurance", "Real estate", "Government"]
    insurance = next(s for s in seg if s["key"] == "insurance")
    assert insurance["count"] > 0
    assert sum(c["count"] for c in insurance["countries"]) == insurance["count"]
    # Municipal leads roll up into the Government sector.
    gov = next(s for s in seg if s["key"] == "governments")
    assert gov["count"] >= 10


def test_campaign_plans_match_active_leads_only(client, env):
    admin = _make_user(client, env, "op@example.org", role="admin")
    # Exclude one insurer and win another — neither may appear in plans.
    client.patch("/api/v2/admin/leads/axa-xl-axa-group-p-c-and-specialty-division",
                 headers=admin,
                 json={"excluded": True, "exclude_reason": "competitor"})
    resp = client.get("/api/v2/admin/intel", headers=admin)
    body = resp.get_json()
    plans = body["campaign_plans"]
    assert len(plans) >= 1
    insurer_plan = next(p for p in plans
                        if "insurance" in str(p.get("audience") or "")
                        or "insur" in (p.get("name") or "").lower())
    ids = [l["id"] for l in insurer_plan["leads"]]
    assert "axa-xl-axa-group-p-c-and-specialty-division" not in ids
    for l in insurer_plan["leads"]:
        assert l["outreach_status"] in (
            "researched", "qualified", "draft_prepared",
            "contacted", "responded", "opportunity")
        assert "decision_maker_role" in l and "activity" in l
    # The excluded lead is also off the map and out of contact_now.
    map_ids = [m["organization"] for m in body["leads_map"]]
    assert "AXA XL (AXA Group P&C and Specialty division)" not in map_ids


def test_excluded_lead_badged_and_restorable(client, env):
    admin = _make_user(client, env, "op@example.org", role="admin")
    slug = "aecom"
    resp = client.patch(f"/api/v2/admin/leads/{slug}", headers=admin,
                        json={"excluded": True, "exclude_reason": "competitor"})
    assert resp.status_code == 200
    assert resp.get_json()["lead"]["excluded"] is True

    body = client.get("/api/v2/admin/intel", headers=admin).get_json()
    lead = next(l for l in body["workspace"]["leads"] if l["id"] == slug)
    assert lead["excluded"] is True
    assert lead["exclude_reason"] == "competitor"

    client.patch(f"/api/v2/admin/leads/{slug}", headers=admin,
                 json={"excluded": False})
    body = client.get("/api/v2/admin/intel", headers=admin).get_json()
    lead = next(l for l in body["workspace"]["leads"] if l["id"] == slug)
    assert lead["excluded"] is False


def test_activity_signals_carry_honest_staleness():
    from src.dashboard.admin_intel import _latest_signals

    signals = [
        {"organization": "Acme", "signal_type": "funding_signal",
         "date_observed": "2020-01-01", "date_checked": "2020-01-02"},
        {"organization": "Acme", "signal_type": "hiring",
         "date_observed": "2026-08-01", "date_checked": "2026-08-02"},
        {"organization": "OldCo", "signal_type": "funding_signal",
         "date_observed": "2020-05-01", "date_checked": "2020-05-02"},
    ]
    latest = _latest_signals(signals)
    assert latest["Acme"]["signal_type"] == "hiring"  # newest wins
    assert latest["Acme"]["stale"] is False
    assert latest["OldCo"]["stale"] is True
