"""Reliability tests for the automatic outreach pipeline.

Covers the fixes around the scheduled processor (real cancel on reply,
transient-failure retry, contact verification filtering, send window),
the reply checker's quoted-text unsubscribe heuristic, the mailer's
standards headers (Date / Message-ID / List-Unsubscribe), the per-lead
auto-send trigger, and the outreach context fallbacks.
All delivery uses the dev outbox backend; nothing is ever sent.
"""

import importlib.util
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """Isolated DB + dev outbox + temporary marketing workspace."""
    db_path = tmp_path / "api.sqlite3"
    outbox_dir = tmp_path / "outbox"
    ws_dir = tmp_path / "marketing"
    (ws_dir / "leads").mkdir(parents=True)

    monkeypatch.setenv("HYDRASHIELD_CACHE_DB", str(db_path))
    monkeypatch.setenv("HYDRASHIELD_OUTBOX_DIR", str(outbox_dir))
    for var in ("SMTP_HOST", "SMTP_USER", "AUTO_OUTREACH_ON_CONTACT",
                "OUTREACH_WINDOW_START", "OUTREACH_WINDOW_END"):
        monkeypatch.delenv(var, raising=False)

    import src.dashboard.cache as cache_mod
    import src.dashboard.admin_intel as intel_mod
    import src.dashboard.marketing_crm as crm_mod

    monkeypatch.setattr(cache_mod, "_default_cache", None)
    monkeypatch.setattr(intel_mod, "_WORKSPACE", str(ws_dir))
    monkeypatch.setattr(crm_mod, "_WORKSPACE", str(ws_dir))

    lead = {
        "organization": "Test Bank One",
        "segment": "banking",
        "country": "US",
        "website": "https://www.testbankone.com",
        "outreach_status": "researched",
        "identified_problem": "Exposure to flood risk.",
        "relevant_capability": "Portfolio screening",
        "recommended_product": "portfolio_screening",
    }
    (ws_dir / "leads" / "test-bank-one.json").write_text(
        json.dumps(lead), encoding="utf-8")
    return {"db": db_path, "outbox": outbox_dir, "ws": ws_dir}


@pytest.fixture()
def store(env):
    from src.dashboard.marketing_store import MarketingStore

    return MarketingStore(str(env["db"]))


def _load_processor():
    spec = importlib.util.spec_from_file_location(
        "process_scheduled_outreach", str(ROOT / "scripts" / "process_scheduled_outreach.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_reply_checker():
    spec = importlib.util.spec_from_file_location(
        "check_replies", str(ROOT / "scripts" / "check_replies.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _past() -> str:
    return (datetime.utcnow() - timedelta(hours=1)).isoformat()[:19]


# ---------------------------------------------------------------------------
# Reply checker: quoted history must never trigger the unsubscribe heuristic
# ---------------------------------------------------------------------------

def test_quoted_unsubscribe_footer_is_not_an_opt_out():
    mod = _load_reply_checker()
    body = (
        "Thanks for reaching out — a call next week works for us.\n\n"
        "On Mon, 25 Aug 2026 at 14:03, Talaix <info@talaix.com> wrote:\n"
        "> If this is not relevant, just reply \"unsubscribe\" and we will stop.\n"
    )
    assert mod._has_unsubscribe_keyword("Re: environmental evidence", body) is False


def test_angle_quoted_footer_is_not_an_opt_out():
    mod = _load_reply_checker()
    body = (
        "Interesting, send me the sample report.\n"
        "> Hi Jane,\n>\n> If this is not relevant, just reply \"unsubscribe\" and we will stop.\n"
    )
    assert mod._has_unsubscribe_keyword("", body) is False


def test_fresh_unsubscribe_request_is_honored():
    mod = _load_reply_checker()
    assert mod._has_unsubscribe_keyword("", "Please unsubscribe me from these emails.") is True
    assert mod._has_unsubscribe_keyword("unsubscribe", "…") is True
    assert mod._has_unsubscribe_keyword("", "أرجو إلغاء الاشتراك من فضلكم") is True


def test_reply_check_fetches_with_peek_and_marks_only_matches(env, store, monkeypatch):
    """RFC 3501: fetching (RFC822) sets \\Seen implicitly — every scanned
    message looked 'read' in Gmail. The checker must fetch with BODY.PEEK[]
    and set \\Seen explicitly only on matched replies."""
    mod = _load_reply_checker()
    store.add_contacts("test-bank-one", [{"email": "sam@testbankone.com"}])

    raw_match = (b"From: Sam <sam@testbankone.com>\r\n"
                 b"Subject: Re: hello\r\n\r\nThanks, interested.\r\n")
    raw_stranger = (b"From: stranger@example.org\r\n"
                    b"Subject: invoice\r\n\r\nrandom mail\r\n")
    calls = {"fetch": [], "store": []}

    class _FakeIMAP:
        def __init__(self, host, port):
            pass

        def login(self, user, password):
            pass

        def select(self, folder):
            pass

        def search(self, charset, criterion):
            return "OK", [b"1 2"]

        def fetch(self, msg_id, query):
            calls["fetch"].append(query)
            raw = raw_match if msg_id == b"1" else raw_stranger
            return "OK", [(msg_id, raw)]

        def store(self, msg_id, flags, value):
            calls["store"].append((msg_id, flags, value))

        def close(self):
            pass

        def logout(self):
            pass

    monkeypatch.setenv("IMAP_HOST", "imap.example.org")
    monkeypatch.setenv("IMAP_USER", "info@talaix.com")
    monkeypatch.setenv("IMAP_PASS", "secret")
    monkeypatch.setattr(mod.imaplib, "IMAP4_SSL", _FakeIMAP)

    assert mod.main() == 0
    assert calls["fetch"] == ["(BODY.PEEK[])", "(BODY.PEEK[])"]
    # Only the matched reply (id 1) is marked Seen; the stranger's mail
    # keeps its unread state on the server.
    assert calls["store"] == [(b"1", "+FLAGS", "\\Seen")]


# ---------------------------------------------------------------------------
# Processor: a replied lead's rows are cancelled for real (not reprocessed)
# ---------------------------------------------------------------------------

def test_processor_cancels_row_when_lead_replied(env, store):
    store.update_state("test-bank-one", outreach_status="replied")
    row = store.schedule_send(
        lead_slug="test-bank-one",
        to_email="someone@testbankone.com",
        contact_name="Sam",
        template="outreach_generic",
        context={"organization": "Test Bank One"},
        send_at=_past(),
    )
    mod = _load_processor()
    assert mod.main() == 0
    updated = store.get_scheduled(row["id"])
    assert updated["status"] == "cancelled"
    # Nothing was sent — no outbox file, no email interaction.
    assert list(Path(env["outbox"]).glob("*.eml")) == []
    assert not any(i["type"] == "email"
                   for i in store.list_interactions("test-bank-one"))


# ---------------------------------------------------------------------------
# Processor: transient failures are retried, then failed after the budget
# ---------------------------------------------------------------------------

def test_processor_reschedules_after_transient_failure(env, store, monkeypatch):
    row = store.schedule_send(
        lead_slug="test-bank-one",
        to_email="someone@testbankone.com",
        contact_name="Sam",
        template="outreach_generic",
        context={"organization": "Test Bank One"},
        send_at=_past(),
    )
    mod = _load_processor()

    def _boom(*args, **kwargs):
        raise OSError("temporary SMTP connection reset")

    monkeypatch.setattr(mod, "send_mail", _boom)
    assert mod.main() == 0

    updated = store.get_scheduled(row["id"])
    assert updated["status"] == "scheduled"  # retried, not failed
    assert updated["attempts"] == 1
    assert updated["send_at"] > datetime.utcnow().isoformat()[:19]
    assert "temporary SMTP connection reset" in (updated["error"] or "")


def test_processor_fails_after_attempt_budget(env, store, monkeypatch):
    row = store.schedule_send(
        lead_slug="test-bank-one",
        to_email="someone@testbankone.com",
        contact_name="Sam",
        template="outreach_generic",
        context={"organization": "Test Bank One"},
        send_at=_past(),
    )
    # Simulate two earlier retries (budget is 3 attempts by default).
    store.reschedule_scheduled(row["id"], _past(), error="boom")
    store.reschedule_scheduled(row["id"], _past(), error="boom")

    mod = _load_processor()

    def _boom(*args, **kwargs):
        raise OSError("still down")

    monkeypatch.setattr(mod, "send_mail", _boom)
    assert mod.main() == 0

    updated = store.get_scheduled(row["id"])
    assert updated["status"] == "failed"
    assert updated["attempts"] == 2  # third failure marks failed, no bump


# ---------------------------------------------------------------------------
# Processor: contact selection and send window
# ---------------------------------------------------------------------------

def test_best_contact_skips_hard_fail_verification():
    mod = _load_processor()
    contacts = [
        {"email": "bad@testbankone.com", "verification": "invalid", "confidence": 95},
        {"email": "good@testbankone.com", "verification": "valid", "confidence": 80},
    ]
    assert mod._best_contact(contacts)["email"] == "good@testbankone.com"
    only_bad = [{"email": "bad@testbankone.com", "verification": "invalid"}]
    assert mod._best_contact(only_bad)["email"] == "bad@testbankone.com"


def test_send_window(env, monkeypatch):
    mod = _load_processor()
    any_hour = datetime(2026, 9, 1, 12, 0, 0)
    assert mod._window_open(any_hour) is True  # unset = always open
    monkeypatch.setenv("OUTREACH_WINDOW_START", "7")
    monkeypatch.setenv("OUTREACH_WINDOW_END", "17")
    assert mod._window_open(datetime(2026, 9, 1, 8, 0, 0)) is True
    assert mod._window_open(datetime(2026, 9, 1, 23, 0, 0)) is False
    monkeypatch.setenv("OUTREACH_WINDOW_START", "22")
    monkeypatch.setenv("OUTREACH_WINDOW_END", "6")
    assert mod._window_open(datetime(2026, 9, 1, 23, 0, 0)) is True
    assert mod._window_open(datetime(2026, 9, 1, 12, 0, 0)) is False


# ---------------------------------------------------------------------------
# Mailer standards headers
# ---------------------------------------------------------------------------

def test_outreach_message_carries_standards_headers(env):
    from src.dashboard import mailer

    msg = mailer._build_message(
        "someone@testbankone.com", "Subject", "Body.", template="outreach_generic")
    assert msg["Date"] is not None
    assert msg["Message-ID"] is not None
    assert "@testbankone.com" not in msg["Message-ID"]
    assert "talaix.com" in msg["Message-ID"]
    assert msg["List-Unsubscribe"] == "<mailto:info@talaix.com?subject=unsubscribe>"


def test_transactional_message_has_no_unsubscribe_header(env):
    from src.dashboard import mailer

    msg = mailer._build_message(
        "user@example.org", "Welcome", "Body.", template="welcome")
    assert msg["Date"] is not None
    assert msg["Message-ID"] is not None
    assert msg["List-Unsubscribe"] is None


def test_public_signature_and_unsubscribe_helpers(env):
    from src.dashboard import mailer

    assert mailer.signature_text().startswith("--\nTalaix")
    assert mailer.unsubscribe_mailto() == "mailto:info@talaix.com?subject=unsubscribe"


# ---------------------------------------------------------------------------
# Outreach context fallbacks
# ---------------------------------------------------------------------------

def test_context_never_renders_empty_greeting(env):
    from src.dashboard.marketing_crm import _outreach_template_and_context
    from src.dashboard import mailer

    lead = {"organization": "Test Bank One", "segment": "banking"}
    template, context = _outreach_template_and_context(lead, {})
    assert context["contact_name"] == "there"
    rendered = mailer.render_template(template, context)
    assert rendered["text"].startswith("Hi there,\n")
    assert context["unsubscribe_url"].startswith("mailto:")


# ---------------------------------------------------------------------------
# Per-lead auto-send trigger
# ---------------------------------------------------------------------------

def test_per_lead_auto_send_queues_without_global_flag(env, store):
    from src.dashboard.marketing_automation import queue_outreach_for_new_contacts

    contacts = [{"email": "sam@testbankone.com", "name": "Sam"}]
    assert queue_outreach_for_new_contacts(store, "test-bank-one", contacts) == 0

    store.set_auto_send("test-bank-one", True)
    queued = queue_outreach_for_new_contacts(store, "test-bank-one", contacts)
    assert queued == 1
    rows = store.list_scheduled(lead_slug="test-bank-one", status="scheduled")
    assert rows[0]["to_email"] == "sam@testbankone.com"
    notes = [i for i in store.list_interactions("test-bank-one")
             if "per-lead auto-send" in i["summary"]]
    assert notes
