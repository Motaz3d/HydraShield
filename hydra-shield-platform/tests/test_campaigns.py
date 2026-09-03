"""Tests for campaign waves, reply detection and contact imports (Phase 18)."""

import importlib.util
import json
import os
import sqlite3
from datetime import datetime, timedelta
from email.message import EmailMessage
from pathlib import Path

import pytest


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """Isolated DB + dev outbox + temporary marketing workspace."""
    db_path = tmp_path / "campaigns.sqlite3"
    outbox_dir = tmp_path / "outbox"
    ws_dir = tmp_path / "marketing"
    (ws_dir / "leads").mkdir(parents=True)

    monkeypatch.setenv("HYDRASHIELD_CACHE_DB", str(db_path))
    monkeypatch.setenv("HYDRASHIELD_OUTBOX_DIR", str(outbox_dir))
    for var in ("SMTP_HOST", "SMTP_USER", "HUNTER_API_KEY", "IMAP_HOST"):
        monkeypatch.delenv(var, raising=False)

    import src.dashboard.cache as cache_mod
    import src.dashboard.admin_intel as intel_mod
    import src.dashboard.marketing_crm as crm_mod

    monkeypatch.setattr(cache_mod, "_default_cache", None)
    # Point modules at the temporary workspace.
    monkeypatch.setattr(intel_mod, "_WORKSPACE", str(ws_dir))
    monkeypatch.setattr(crm_mod, "_WORKSPACE", str(ws_dir))

    return {"db": db_path, "outbox": outbox_dir, "ws": ws_dir}


def _write_lead(ws_dir, slug, lead):
    path = Path(ws_dir) / "leads" / f"{slug}.json"
    path.write_text(json.dumps(lead), encoding="utf-8")


@pytest.fixture()
def sample_workspace(env):
    """A small lead base with banking and insurance leads."""
    leads = [
        {
            "organization": "Campaign Bank One",
            "segment": "banking",
            "country": "US",
            "website": "https://www.campaignbankone.com",
            "priority": "high",
            "urgency": "high",
            "outreach_status": "researched",
            "recommended_product": "portfolio_screening",
            "next_action": "Send intro email",
            "decision_maker_role": "Sustainability Director",
            "identified_problem": "Exposure to flood risk.",
            "relevant_capability": "Portfolio screening",
            "status": "open",
        },
        {
            "organization": "Campaign Bank Two",
            "segment": "banking",
            "country": "US",
            "website": "https://www.campaignbanktwo.com",
            "priority": "medium",
            "urgency": "medium",
            "outreach_status": "qualified",
            "recommended_product": "enterprise_dashboard",
            "decision_maker_role": "Risk Officer",
            "identified_problem": "Needs climate risk data.",
            "relevant_capability": "Enterprise dashboard",
            "status": "open",
        },
        {
            "organization": "Campaign Insurer",
            "segment": "insurance",
            "country": "DE",
            "priority": "high",
            "urgency": "low",
            "outreach_status": "researched",
            "recommended_product": "risk_api",
            "decision_maker_role": "Head of Underwriting",
            "identified_problem": "Accumulating nat-cat exposure.",
            "relevant_capability": "Risk API",
            "status": "open",
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
            "status": "open",
        },
    ]
    for lead in leads:
        slug = lead["organization"].lower().replace(" ", "-")
        lead["_slug"] = slug
        _write_lead(env["ws"], slug, lead)
    return env


# ---------------------------------------------------------------------------
# MarketingStore campaign-wave primitives
# ---------------------------------------------------------------------------


def test_store_enqueue_and_fetch_wave(env):
    from src.dashboard.marketing_store import MarketingStore

    store = MarketingStore(str(env["db"]))
    row = store.enqueue_wave(
        campaign="q4-2026",
        lead_slug="campaign-bank-one",
        wave=1,
        template="followup_1",
        context={"organization": "Campaign Bank One"},
        send_at="2026-09-01T09:00",
    )
    assert row is not None
    assert row["campaign"] == "q4-2026"
    assert row["wave"] == 1
    assert row["status"] == "pending"

    fetched = store.get_wave(row["id"])
    assert fetched["lead_slug"] == "campaign-bank-one"

    pending = store.pending_waves()
    assert len(pending) == 1


def test_store_duplicate_wave_is_ignored(env):
    from src.dashboard.marketing_store import MarketingStore

    store = MarketingStore(str(env["db"]))
    base = {
        "campaign": "q4-2026",
        "lead_slug": "campaign-bank-one",
        "wave": 1,
        "template": "followup_1",
        "context": {},
        "send_at": "2026-09-01T09:00",
    }
    assert store.enqueue_wave(**base) is not None
    assert store.enqueue_wave(**base) is None


def test_store_mark_wave_and_cancel(env):
    from src.dashboard.marketing_store import MarketingStore

    store = MarketingStore(str(env["db"]))
    row = store.enqueue_wave(
        campaign="q4-2026",
        lead_slug="campaign-bank-one",
        wave=1,
        template="followup_1",
        context={},
        send_at="2026-09-01T09:00",
    )
    updated = store.mark_wave(row["id"], "sent")
    assert updated["status"] == "sent"
    assert updated["sent_at"] is not None

    row2 = store.enqueue_wave(
        campaign="q4-2026",
        lead_slug="campaign-bank-one",
        wave=2,
        template="followup_2",
        context={},
        send_at="2026-09-02T09:00",
    )
    assert store.cancel_waves_for_lead("campaign-bank-one") == 1
    assert store.get_wave(row2["id"])["status"] == "cancelled"


def test_store_campaign_stats(env):
    from src.dashboard.marketing_store import MarketingStore

    store = MarketingStore(str(env["db"]))
    store.enqueue_wave("c1", "campaign-bank-one", 1, "followup_1", {}, "2026-09-01T09:00")
    store.enqueue_wave("c1", "campaign-bank-one", 2, "followup_2", {}, "2026-09-02T09:00")
    store.enqueue_wave("c1", "campaign-insurer", 1, "followup_1", {}, "2026-09-01T09:00")

    store.mark_wave(store.pending_waves()[0]["id"], "sent")

    stats = store.campaign_stats()
    by_name = {s["campaign"]: s for s in stats}
    assert "c1" in by_name
    c1 = by_name["c1"]
    # Two unique lead slugs (bank-one has two waves).
    assert len(c1["leads"]) == 2
    assert sum(w.get("sent", 0) for w in c1["waves"]) == 1

    detail = store.campaign_stats(campaign="c1")
    assert len(detail) == 1
    assert detail[0]["campaign"] == "c1"


def test_store_list_contacts_all_or_filtered(env):
    from src.dashboard.marketing_store import MarketingStore

    store = MarketingStore(str(env["db"]))
    store.add_contacts("campaign-bank-one", [{"email": "a@example.com"}])
    store.add_contacts("campaign-insurer", [{"email": "b@example.com"}])

    assert len(store.list_contacts("campaign-bank-one")) == 1
    all_contacts = store.list_contacts()
    assert len(all_contacts) == 2


# ---------------------------------------------------------------------------
# Campaign selection and enqueue logic
# ---------------------------------------------------------------------------


def test_select_campaign_leads_eligibility(sample_workspace):
    from src.dashboard.campaigns import select_campaign_leads
    from src.dashboard.marketing_store import MarketingStore

    store = MarketingStore(str(sample_workspace["db"]))
    store.add_contacts("campaign-bank-one", [{"email": "one@example.com"}])
    store.add_contacts("campaign-bank-two", [{"email": "two@example.com"}])
    store.add_contacts("campaign-insurer", [{"email": "insurer@example.com"}])

    from src.dashboard.admin_intel import _records_ws

    leads = _records_ws("leads")
    selected = select_campaign_leads(leads, store, "q4-2026", 1)
    slugs = {l["_slug"] for l in selected}
    assert "campaign-bank-one" in slugs
    assert "campaign-bank-two" in slugs
    assert "campaign-insurer" in slugs
    assert "excluded-bank" not in slugs


def test_select_campaign_leads_filters_and_dedup(sample_workspace):
    from src.dashboard.campaigns import select_campaign_leads
    from src.dashboard.marketing_store import MarketingStore

    store = MarketingStore(str(sample_workspace["db"]))
    store.add_contacts("campaign-bank-one", [{"email": "one@example.com"}])
    store.add_contacts("campaign-insurer", [{"email": "insurer@example.com"}])
    store.enqueue_wave("q4-2026", "campaign-bank-one", 1, "followup_1", {}, "2026-09-01T09:00")

    from src.dashboard.admin_intel import _records_ws

    leads = _records_ws("leads")

    # Country filter.
    selected = select_campaign_leads(leads, store, "q4-2026", 1, filters={"country": "DE"})
    assert [l["_slug"] for l in selected] == ["campaign-insurer"]

    # Lead already has a pending/sent wave for this campaign/wave.
    selected = select_campaign_leads(leads, store, "q4-2026", 1, filters={"country": "US"})
    assert "campaign-bank-one" not in {l["_slug"] for l in selected}


def test_enqueue_campaign_wave_staggers_send_at(env, sample_workspace):
    from src.dashboard.campaigns import enqueue_campaign_wave
    from src.dashboard.marketing_store import MarketingStore

    store = MarketingStore(str(sample_workspace["db"]))
    store.add_contacts("campaign-bank-one", [{"email": "one@example.com"}])
    store.add_contacts("campaign-bank-two", [{"email": "two@example.com"}])

    from src.dashboard.admin_intel import _records_ws

    leads = _records_ws("leads")
    us_leads = [l for l in leads if l.get("country") == "US" and not l.get("excluded")]

    result = enqueue_campaign_wave(
        campaign="q4-2026",
        wave=2,
        template="followup_1",
        leads=us_leads,
        store=store,
        delay_days=1.0,
    )
    assert result["enqueued"] == 2
    assert result["skipped"] == 0

    waves = store.pending_waves()
    assert len(waves) == 2
    # Sends are staggered by 5 minutes.
    t0 = datetime.fromisoformat(waves[0]["send_at"])
    t1 = datetime.fromisoformat(waves[1]["send_at"])
    assert (t1 - t0).total_seconds() == 300


def test_start_campaign_respects_filters(env, sample_workspace):
    from src.dashboard.campaigns import start_campaign
    from src.dashboard.marketing_store import MarketingStore

    store = MarketingStore(str(sample_workspace["db"]))
    store.add_contacts("campaign-bank-one", [{"email": "one@example.com"}])
    store.add_contacts("campaign-insurer", [{"email": "insurer@example.com"}])

    result = start_campaign(
        campaign="de-2026",
        wave=1,
        template="followup_1",
        filters={"country": "DE"},
        store=store,
    )
    assert result["enqueued"] == 1
    assert result["leads"] == ["campaign-insurer"]


# ---------------------------------------------------------------------------
# Scheduled processor handles campaign waves
# ---------------------------------------------------------------------------


def _load_processor():
    script_path = Path(__file__).resolve().parent.parent / "scripts" / "process_scheduled_outreach.py"
    spec = importlib.util.spec_from_file_location("process_scheduled_outreach", str(script_path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_processor_sends_due_wave(env, sample_workspace):
    from src.dashboard.campaigns import start_campaign
    from src.dashboard.marketing_store import MarketingStore

    store = MarketingStore(str(env["db"]))
    store.add_contacts("campaign-bank-one", [{"email": "one@example.com"}])

    result = start_campaign("q4-2026", 1, "followup_1", store=store)
    assert result["enqueued"] == 1
    wid = store.pending_waves()[0]["id"]

    # Make the wave due now.
    with sqlite3.connect(str(env["db"])) as conn:
        conn.execute(
            "UPDATE campaign_waves SET send_at = ? WHERE id = ?",
            ((datetime.utcnow() - timedelta(hours=1)).isoformat()[:19], wid),
        )

    mod = _load_processor()
    assert mod.main() == 0

    assert store.get_wave(wid)["status"] == "sent"
    assert len(list(env["outbox"].glob("*.eml"))) == 1


def test_processor_cancels_wave_for_replied_lead(env, sample_workspace):
    from src.dashboard.campaigns import start_campaign
    from src.dashboard.marketing_store import MarketingStore

    store = MarketingStore(str(env["db"]))
    store.add_contacts("campaign-bank-one", [{"email": "one@example.com"}])
    store.update_state("campaign-bank-one", outreach_status="replied")

    result = start_campaign("q4-2026", 1, "followup_1", store=store)
    wid = store.pending_waves()[0]["id"]

    with sqlite3.connect(str(env["db"])) as conn:
        conn.execute(
            "UPDATE campaign_waves SET send_at = ? WHERE id = ?",
            ((datetime.utcnow() - timedelta(hours=1)).isoformat()[:19], wid),
        )

    mod = _load_processor()
    assert mod.main() == 0

    assert store.get_wave(wid)["status"] == "cancelled"
    assert len(list(env["outbox"].glob("*.eml"))) == 0


# ---------------------------------------------------------------------------
# Reply detection (IMAP helper)
# ---------------------------------------------------------------------------


def _load_check_replies():
    script_path = Path(__file__).resolve().parent.parent / "scripts" / "check_replies.py"
    spec = importlib.util.spec_from_file_location("check_replies", str(script_path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_process_message_logs_reply_and_auto_stops(env):
    from src.dashboard.marketing_store import MarketingStore

    store = MarketingStore(str(env["db"]))
    store.add_contacts("campaign-bank-one", [{"email": "reply@example.com"}])

    mod = _load_check_replies()
    msg = EmailMessage()
    msg["From"] = "Reply Person <reply@example.com>"
    msg["Subject"] = "Re: introduction"
    msg["Date"] = datetime.utcnow().isoformat() + "Z"
    msg.set_content("Thanks, let's talk next week.")

    contacts = mod._load_contacts(store)
    result = mod._process_message(store, msg, contacts)
    assert result == ("campaign-bank-one", "reply", False)

    state = store.get_state("campaign-bank-one")
    assert state["outreach_status"] == "replied"

    interactions = store.list_interactions("campaign-bank-one")
    types = [i["type"] for i in interactions]
    assert "reply" in types
    assert "note" in types
    assert any("Auto-stopped" in i["summary"] for i in interactions)


def test_process_message_unsubscribe_heuristic(env):
    from src.dashboard.marketing_store import MarketingStore

    store = MarketingStore(str(env["db"]))
    store.add_contacts("campaign-bank-one", [{"email": "unsub@example.com"}])

    mod = _load_check_replies()
    msg = EmailMessage()
    msg["From"] = "Unsub <unsub@example.com>"
    msg["Subject"] = "Re: introduction"
    msg["Date"] = datetime.utcnow().isoformat() + "Z"
    msg.set_content("Please unsubscribe me.")

    contacts = mod._load_contacts(store)
    result = mod._process_message(store, msg, contacts)
    assert result == ("campaign-bank-one", "reply", True)

    assert store.is_unsubscribed("campaign-bank-one")
    interactions = store.list_interactions("campaign-bank-one")
    assert any(i["type"] == "unsubscribe" for i in interactions)


def test_process_message_auto_reply_header_does_not_stop_outreach(env):
    """A machine acknowledgement (RFC 3834) is not a human reply: it must be
    logged for the record but never set 'replied' nor cancel pending sends."""
    from src.dashboard.marketing_store import MarketingStore

    store = MarketingStore(str(env["db"]))
    store.add_contacts("campaign-bank-one", [{"email": "auto@example.com"}])

    mod = _load_check_replies()
    msg = EmailMessage()
    msg["From"] = "SGX <auto@example.com>"
    msg["Subject"] = "CRS0389850 - Climate evidence behind the assets"
    msg["Date"] = datetime.utcnow().isoformat() + "Z"
    msg["Auto-Submitted"] = "auto-replied"
    msg.set_content("Thank you for writing to SGX. We will respond to your "
                    "CDP query within 3-5 business days.")

    contacts = mod._load_contacts(store)
    result = mod._process_message(store, msg, contacts)
    assert result == ("campaign-bank-one", "auto_reply", False)

    state = store.get_state("campaign-bank-one")
    assert not state or state.get("outreach_status") != "replied"
    interactions = store.list_interactions("campaign-bank-one")
    assert all(i["type"] == "note" for i in interactions)
    assert any("Auto-reply" in i["summary"] for i in interactions)


def test_process_message_auto_reply_body_phrase_does_not_stop_outreach(env):
    """Stock auto-acknowledgement wording without headers is still a machine
    reply — outreach continues and the unsubscribe heuristic never runs."""
    from src.dashboard.marketing_store import MarketingStore

    store = MarketingStore(str(env["db"]))
    store.add_contacts("campaign-bank-one", [{"email": "bot@example.com"}])

    mod = _load_check_replies()
    msg = EmailMessage()
    msg["From"] = "Bot <bot@example.com>"
    msg["Subject"] = "Re: introduction"
    msg["Date"] = datetime.utcnow().isoformat() + "Z"
    # Contains the word "unsubscribe" inside a quoted footer AND an
    # auto-acknowledgement phrase: neither may change lead state.
    msg.set_content(
        "This is a system generated auto reply.\n\n"
        "On Mon, 1 Sep 2026, Talaix <info@talaix.com> wrote:\n"
        '> reply "unsubscribe" to opt out.\n'
    )

    contacts = mod._load_contacts(store)
    result = mod._process_message(store, msg, contacts)
    assert result == ("campaign-bank-one", "auto_reply", False)

    state = store.get_state("campaign-bank-one")
    assert not state or state.get("outreach_status") != "replied"
    assert not store.is_unsubscribed("campaign-bank-one")


def test_process_message_notifies_operator_on_human_reply(env, monkeypatch):
    """A genuine reply must be surfaced to the operator inbox."""
    from src.dashboard.marketing_store import MarketingStore

    store = MarketingStore(str(env["db"]))
    store.add_contacts("campaign-bank-one", [{"email": "human@example.com"}])

    mod = _load_check_replies()
    calls = []
    monkeypatch.setattr(
        mod.mailer, "operator_notify",
        lambda subject, message, kind="general": calls.append(
            {"subject": subject, "message": message, "kind": kind}))

    msg = EmailMessage()
    msg["From"] = "Human <human@example.com>"
    msg["Subject"] = "Re: introduction"
    msg["Date"] = datetime.utcnow().isoformat() + "Z"
    msg.set_content("Interesting — can we get a demo next week?")

    contacts = mod._load_contacts(store)
    result = mod._process_message(store, msg, contacts)
    assert result == ("campaign-bank-one", "reply", False)

    assert len(calls) == 1
    assert calls[0]["kind"] == "lead_reply"
    assert "human@example.com" in calls[0]["message"]
    assert "demo next week" in calls[0]["message"]


def test_process_message_no_operator_notification_on_auto_reply(env, monkeypatch):
    from src.dashboard.marketing_store import MarketingStore

    store = MarketingStore(str(env["db"]))
    store.add_contacts("campaign-bank-one", [{"email": "ooo@example.com"}])

    mod = _load_check_replies()
    calls = []
    monkeypatch.setattr(
        mod.mailer, "operator_notify",
        lambda subject, message, kind="general": calls.append(subject))

    msg = EmailMessage()
    msg["From"] = "OOO <ooo@example.com>"
    msg["Subject"] = "Automatic reply: introduction"
    msg["Date"] = datetime.utcnow().isoformat() + "Z"
    msg.set_content("I am out of office until Monday.")

    contacts = mod._load_contacts(store)
    result = mod._process_message(store, msg, contacts)
    assert result == ("campaign-bank-one", "auto_reply", False)
    assert calls == []


# ---------------------------------------------------------------------------
# Bounce guard (delivery failures + Hunter.io alert trigger)
# ---------------------------------------------------------------------------


def test_process_message_bounce_invalidates_contact_and_cancels(env, tmp_path, monkeypatch):
    """A delivery-failure notice names the failed recipient in its body:
    log a 'bounce', mark that contact invalid, cancel its pending sends."""
    from src.dashboard.marketing_store import MarketingStore

    monkeypatch.setenv("BOUNCE_GUARD_FILE", str(tmp_path / "guard.json"))
    store = MarketingStore(str(env["db"]))
    store.add_contacts("campaign-bank-one", [{"email": "gone@example.com"}])
    row = store.schedule_send(
        lead_slug="campaign-bank-one",
        to_email="gone@example.com",
        contact_name="there",
        template="outreach_banking",
        context={"organization": "Campaign Bank One"},
        send_at="2099-01-01T00:00:00",
    )

    mod = _load_check_replies()
    msg = EmailMessage()
    msg["From"] = "Mail Delivery System <MAILER-DAEMON@mx.example.com>"
    msg["Subject"] = "Delivery Status Notification (Failure)"
    msg["Date"] = datetime.utcnow().isoformat() + "Z"
    msg.set_content(
        "This is an automatically generated Delivery Status Notification.\n"
        "Delivery to the following recipient failed permanently:\n"
        "    gone@example.com\n"
        "550 5.1.1 The email account that you tried to reach does not exist.\n"
    )

    contacts = mod._load_contacts(store)
    result = mod._process_message(store, msg, contacts)
    assert result == ("campaign-bank-one", "bounce", False)

    contact = store.list_contacts("campaign-bank-one")[0]
    assert contact["verification"] == "invalid"
    assert store.get_scheduled(row["id"])["status"] == "cancelled"
    interactions = store.list_interactions("campaign-bank-one")
    assert any(i["type"] == "bounce" for i in interactions)
    # A bounce is not a reply: status untouched.
    state = store.get_state("campaign-bank-one")
    assert not state or state.get("outreach_status") != "replied"


def test_bounce_guard_alerts_once_over_threshold(env, tmp_path, monkeypatch):
    from src.dashboard.marketing_store import MarketingStore

    monkeypatch.setenv("BOUNCE_GUARD_FILE", str(tmp_path / "guard.json"))
    store = MarketingStore(str(env["db"]))
    mod = _load_check_replies()
    calls = []
    monkeypatch.setattr(
        mod.mailer, "operator_notify",
        lambda subject, message, kind="general": calls.append(
            {"subject": subject, "kind": kind}))

    today = datetime.utcnow().strftime("%Y-%m-%d")
    state = {"days": {today: {"sent": 20, "bounces": 2}},  # 10% > 5%
             "hunter_notified": False}
    assert mod.maybe_alert_hunter(state) is True
    assert len(calls) == 1 and calls[0]["kind"] == "bounce_guard"
    assert "Hunter" in calls[0]["subject"]
    # Once per episode: a second evaluation does not re-notify.
    assert mod.maybe_alert_hunter(state) is False
    assert len(calls) == 1
    # Rate back under the threshold re-arms the alert for the next episode.
    state["days"][today]["bounces"] = 0
    assert mod.maybe_alert_hunter(state) is False
    assert state["hunter_notified"] is False


def test_bounce_guard_silent_below_threshold_and_small_sample(env, tmp_path, monkeypatch):
    monkeypatch.setenv("BOUNCE_GUARD_FILE", str(tmp_path / "guard.json"))
    mod = _load_check_replies()
    calls = []
    monkeypatch.setattr(
        mod.mailer, "operator_notify",
        lambda subject, message, kind="general": calls.append(subject))

    today = datetime.utcnow().strftime("%Y-%m-%d")
    # Exactly 5% is not over the threshold.
    assert mod.maybe_alert_hunter(
        {"days": {today: {"sent": 20, "bounces": 1}},
         "hunter_notified": False}) is False
    # 33% but only 6 sends — below the minimum sample, no alarm.
    assert mod.maybe_alert_hunter(
        {"days": {today: {"sent": 6, "bounces": 2}},
         "hunter_notified": False}) is False
    assert calls == []


# ---------------------------------------------------------------------------
# Contact import
# ---------------------------------------------------------------------------


def test_import_contacts_creates_leads_and_is_idempotent(env):
    script_path = Path(__file__).resolve().parent.parent / "scripts" / "import_contacts.py"
    spec = importlib.util.spec_from_file_location("import_contacts", str(script_path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    # Point the script at a temporary imports directory.
    imports_dir = env["ws"] / "imports"
    imports_dir.mkdir(parents=True)
    seed = {
        "batch": "test-seed",
        "imported_at": "2026-08-26",
        "contacts": [
            {
                "organization": "Imported Startup",
                "email": "hello@importedstartup.com",
                "person": "Founder Name",
                "role": "CEO",
                "segment": "banking",
                "country": "US",
                "email_type": "personal",
            }
        ],
    }
    (imports_dir / "seed.json").write_text(json.dumps(seed), encoding="utf-8")

    # Redirect the script's lead directory into the test workspace.
    mod.LEADS_DIR = env["ws"] / "leads"
    mod.IMPORTS_DIR = imports_dir

    store = mod.MarketingStore(str(env["db"]))
    counts = mod.import_batch(store, seed)
    assert counts["created"] == 1
    assert counts["contacts_added"] == 1

    # Idempotent re-run.
    counts2 = mod.import_batch(store, seed)
    assert counts2["created"] == 0
    assert counts2["contacts_added"] == 0

    lead_file = env["ws"] / "leads" / "imported-startup.json"
    assert lead_file.exists()
    lead = json.loads(lead_file.read_text(encoding="utf-8"))
    assert lead["organization"] == "Imported Startup"
    assert lead["segment"] == "banking"
