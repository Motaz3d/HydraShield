"""Offline tests for marketing automation (src/dashboard/marketing_automation.py).

Covers: new-contact auto follow-up (opt-in flag, dedupe, unsubscribe) and
registration matching (domain match → interaction + auto-cancel + operator
notification; free-mail never matches; auth verify wiring).
"""

import json

import pytest


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
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.delenv("SMTP_USER", raising=False)
    monkeypatch.delenv("AUTO_OUTREACH_ON_CONTACT", raising=False)

    import src.dashboard.cache as cache_mod
    import src.dashboard.admin_intel as intel_mod
    import src.dashboard.marketing_crm as crm_mod
    import src.dashboard.api as api_mod

    monkeypatch.setattr(cache_mod, "_default_cache", None)
    monkeypatch.setattr(api_mod, "_rate_limiter", api_mod._RateLimiter())
    monkeypatch.setattr(intel_mod, "_WORKSPACE", str(ws_dir))
    monkeypatch.setattr(crm_mod, "_WORKSPACE", str(ws_dir))

    lead = {
        "organization": "CMCC Foundation",
        "segment": "research_centers",
        "country": "IT",
        "website": "https://www.cmcc.it",
        "outreach_status": "researched",
        "identified_problem": "needs reproducible evidence pipelines",
        "relevant_capability": "content-hashed analyses",
        "recommended_product": "portfolio_screening",
    }
    (ws_dir / "leads" / "cmcc-foundation.json").write_text(
        json.dumps(lead), encoding="utf-8")
    return {"db": db_path, "outbox": outbox_dir, "ws": ws_dir}


@pytest.fixture()
def store(env):
    from src.dashboard.marketing_store import MarketingStore

    return MarketingStore(str(env["db"]))


CONTACTS = [
    {"email": "silvia.torresan@cmcc.it", "name": "Silvia Torresan"},
    {"email": "paola.mercogliano@cmcc.it", "name": "Paola Mercogliano"},
]


# ---------------------------------------------------------------------------
# New-contact auto follow-up
# ---------------------------------------------------------------------------

def test_auto_queue_disabled_by_default(env, store):
    from src.dashboard.marketing_automation import queue_outreach_for_new_contacts

    queued = queue_outreach_for_new_contacts(store, "cmcc-foundation", CONTACTS)
    assert queued == 0
    assert store.list_scheduled(lead_slug="cmcc-foundation") == []


def test_auto_queue_enabled_queues_and_dedupes(env, store, monkeypatch):
    monkeypatch.setenv("AUTO_OUTREACH_ON_CONTACT", "1")
    from src.dashboard.marketing_automation import queue_outreach_for_new_contacts

    queued = queue_outreach_for_new_contacts(store, "cmcc-foundation", CONTACTS)
    assert queued == 2
    rows = store.list_scheduled(lead_slug="cmcc-foundation", status="scheduled")
    assert {r["to_email"] for r in rows} == {c["email"] for c in CONTACTS}
    assert all(r["template"].startswith("outreach_") for r in rows)
    # The automation leaves an interaction record.
    notes = [i for i in store.list_interactions("cmcc-foundation")
             if "Auto-queued" in i["summary"]]
    assert notes
    # Second run with the same contacts queues nothing (pending rows exist).
    assert queue_outreach_for_new_contacts(store, "cmcc-foundation", CONTACTS) == 0


def test_auto_queue_respects_unsubscribe(env, store, monkeypatch):
    monkeypatch.setenv("AUTO_OUTREACH_ON_CONTACT", "1")
    from src.dashboard.marketing_automation import queue_outreach_for_new_contacts

    store.unsubscribe("cmcc-foundation", reason="test")
    assert queue_outreach_for_new_contacts(store, "cmcc-foundation", CONTACTS) == 0
    assert store.list_scheduled(lead_slug="cmcc-foundation") == []


# ---------------------------------------------------------------------------
# Registration matching
# ---------------------------------------------------------------------------

def test_registration_match_records_cancels_and_notifies(env, store, monkeypatch):
    from src.dashboard.marketing_automation import handle_registration

    store.schedule_send(
        lead_slug="cmcc-foundation", to_email="silvia.torresan@cmcc.it",
        contact_name="Silvia", template="outreach_generic", context={},
        send_at="2099-01-01T00:00:00")
    matched = handle_registration("new.person@cmcc.it")
    assert matched == ["cmcc-foundation"]

    rows = store.list_scheduled(lead_slug="cmcc-foundation")
    assert rows[0]["status"] == "cancelled"
    interactions = store.list_interactions("cmcc-foundation")
    assert any(i["type"] == "registered" for i in interactions)

    files = list(env["outbox"].glob("*_operator_notification_*.eml"))
    assert files, "operator was not notified"
    import email as email_lib
    import email.policy  # noqa: F401

    msg = email_lib.message_from_string(
        files[-1].read_text(encoding="utf-8"), policy=email_lib.policy.default)
    plain = msg.get_body(("plain",)).get_content()
    assert "Lead registered" in str(msg["Subject"])
    assert "cmcc-foundation" in plain
    assert "new.person@cmcc.it" in plain


def test_registration_ignores_free_mail(env, store):
    from src.dashboard.marketing_automation import handle_registration

    assert handle_registration("someone@gmail.com") == []
    assert store.list_interactions("cmcc-foundation") == []


def test_registration_wired_into_verify(client_env):
    """The auth verify endpoint triggers the automation end-to-end."""
    env, client, token = client_env
    resp = client.get(f"/api/v2/auth/verify?token={token}")
    assert resp.status_code == 200
    from src.dashboard.marketing_store import MarketingStore

    store = MarketingStore(str(env["db"]))
    interactions = store.list_interactions("cmcc-foundation")
    assert any(i["type"] == "registered" for i in interactions)


@pytest.fixture()
def client_env(env):
    """Client + a registered (unverified) user on the lead's domain."""
    import re
    import email as email_lib
    import email.policy  # noqa: F401

    from src.dashboard.api import create_app

    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()
    resp = client.post("/api/v2/auth/register",
                       json={"email": "new.person@cmcc.it",
                             "password": "correct horse battery", "consent": True})
    assert resp.status_code == 201, resp.get_json()
    files = sorted(env["outbox"].glob("*_email_verification_*.eml"))
    assert files
    msg = email_lib.message_from_string(
        files[-1].read_text(encoding="utf-8"), policy=email_lib.policy.default)
    token = re.search(r"token=([A-Za-z0-9_\-]+)",
                      msg.get_body(("plain",)).get_content()).group(1)
    return env, client, token
