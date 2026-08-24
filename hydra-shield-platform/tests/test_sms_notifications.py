"""
Offline tests for SMS alerting (Stage 7).

ALL tests are offline: the SMS backend is the dev outbox (files in
HYDRASHIELD_OUTBOX_DIR) or fakes — no real SMS is ever sent, no network is
touched, no provider credentials are used. Email runs on the mailer's dev
outbox backend (SMTP_HOST unset).

Covers: outbox/misconfigured backends, E.164 validation, phone
verification flow (code via outbox, wrong/expired codes), preferences,
rules + tier caps, the transition matrix, dedupe cooldown, quiet hours,
daily cap, message format, unsubscribe, per-user isolation, secret hygiene
(no credentials/codes in the DB or audit log) and the periodic checker.
"""

import importlib.util
import io
import json
import os
import re
import sqlite3
from datetime import datetime

import pytest

from src.dashboard import alert_engine, sms
from src.dashboard.accounts import UserStore
from src.dashboard.api import create_app
from src.dashboard.notify_store import NotifyStore


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """Isolated DB + outbox per test; dev SMS/email backends guaranteed."""
    db_path = tmp_path / "notify.sqlite3"
    monkeypatch.setenv("HYDRASHIELD_CACHE_DB", str(db_path))
    monkeypatch.setenv("HYDRASHIELD_OUTBOX_DIR", str(tmp_path / "outbox"))
    for var in ("SMTP_HOST", "SMTP_USER", "SMS_PROVIDER", "SMS_HTTP_URL",
                "SMS_FROM", "SMS_API_KEY", "SMS_API_SECRET",
                "SMS_HTTP_AUTH_HEADER", "TWILIO_ACCOUNT_SID",
                "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER"):
        monkeypatch.delenv(var, raising=False)
    import src.dashboard.cache as cache_mod
    import src.dashboard.api as api_module

    monkeypatch.setattr(cache_mod, "_default_cache", None)
    api_module._rate_limiter._hits.clear()
    yield {"db": db_path, "outbox": tmp_path / "outbox"}
    api_module._rate_limiter._hits.clear()


@pytest.fixture()
def store(env):
    return NotifyStore(str(env["db"]))


@pytest.fixture()
def client(env):
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(env, email="user@example.org"):
    us = UserStore(str(env["db"]))
    user = us.register_user(email, "correct horse battery", consent=True)
    us.mark_email_verified(user["id"])
    return us.get_user(user["id"])


def _auth_headers(client, env, email="user@example.org", password="correct horse battery"):
    """Register + verify a user through the real auth flow; Bearer headers."""
    resp = client.post("/api/v2/auth/register",
                       json={"email": email, "password": password, "consent": True})
    assert resp.status_code == 201, resp.get_json()
    import email as email_lib
    import email.policy

    files = sorted(env["outbox"].glob("*_email_verification_*.eml"))
    msg = email_lib.message_from_string(
        files[-1].read_text(encoding="utf-8"), policy=email_lib.policy.default)
    plain = msg.get_body(("plain",)).get_content()
    token = re.search(r"token=([A-Za-z0-9_\-]+)", plain).group(1)
    resp = client.get(f"/api/v2/auth/verify?token={token}")
    assert resp.status_code == 200, resp.get_json()
    return {"Authorization": f"Bearer {resp.get_json()['session_token']}"}


def _sms_files(outbox_dir):
    return sorted(outbox_dir.glob("*.sms.txt"))


def _verification_code(outbox_dir):
    files = _sms_files(outbox_dir)
    assert files, "no SMS in outbox"
    text = files[-1].read_text(encoding="utf-8")
    match = re.search(r"code: (\d{6})", text)
    assert match, "no verification code in outbox SMS"
    return match.group(1)


def _add_phone(client, headers, phone="+306912345678"):
    resp = client.post("/api/v2/alerts/phone", json={"phone": phone}, headers=headers)
    assert resp.status_code == 201, resp.get_json()
    return resp


def _add_rule(client, headers, hazard="wildfire", lat=37.9, lon=23.7,
              threshold="HIGH", name="Athens"):
    return client.post("/api/v2/alerts/rules",
                       json={"hazard": hazard, "lat": lat, "lon": lon,
                             "name": name, "severity_threshold": threshold},
                       headers=headers)


class FakeMailer:
    def __init__(self):
        self.sent = []

    def send_mail(self, to, template, context, subject_override=None):
        self.sent.append({"to": to, "subject": subject_override or context.get("subject")})
        return {"backend": "outbox", "path": None}


class FakeSms:
    def __init__(self, backend="outbox"):
        self.backend = backend
        self.sent = []

    def send_sms(self, to, message):
        self.sent.append({"to": to, "message": message})
        if self.backend == "http":
            return {"backend": "http", "provider_message_id": "fake-1"}
        return {"backend": "outbox", "path": "fake"}


def _wildfire_analysis(risk=72.0, risk_class="Extreme"):
    return {
        "location": {"lat": 37.9, "lon": 23.7, "name": "Athens"},
        "generated_at": "2026-08-17T00:00:00Z",
        "analysis": {"risk": {"baseline": risk, "class": risk_class}},
        "fire_danger": {"fwi": 41.2, "class": "Very high"},
        "recommendations": [
            {"what": "Increase monitoring frequency and preparedness level."}],
    }


def _rule(store, user_id, threshold="HIGH", last_severity=None):
    result = store.add_rule(user_id, "wildfire", 37.9, 23.7,
                            name="Athens", severity_threshold=threshold)
    rule = result["rule"]
    if last_severity is not None:
        store.update_rule_state(rule["id"], last_severity)
        rule = store.get_rule(rule["id"])
    return rule


def _db_dump_text(db_path, tables=None):
    conn = sqlite3.connect(str(db_path))
    try:
        if tables is None:
            tables = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")]
        parts = []
        for table in tables:
            for row in conn.execute(f"SELECT * FROM {table}"):
                parts.append(repr(row))
        return "\n".join(parts)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# sms.py — backends + E.164
# ---------------------------------------------------------------------------

def test_outbox_backend_writes_file(env):
    result = sms.send_sms("+306912345678", "HYDRASHIELD ALERT test body")
    assert result["backend"] == "outbox"
    assert os.path.exists(result["path"])
    content = open(result["path"], encoding="utf-8").read()
    assert "HYDRASHIELD ALERT test body" in content
    assert "+306912345678" in content
    assert sms.sms_configured() is False


def test_http_without_url_is_honestly_misconfigured(env, monkeypatch):
    monkeypatch.setenv("SMS_PROVIDER", "http")
    monkeypatch.delenv("SMS_HTTP_URL", raising=False)
    result = sms.send_sms("+306912345678", "hello")
    assert result["backend"] == "misconfigured"
    assert "SMS_HTTP_URL" in result["error"]
    assert sms.sms_configured() is False


# ---------------------------------------------------------------------------
# sms.py — Twilio backend (offline: urllib mocked, no network)
# ---------------------------------------------------------------------------

def _twilio_env(monkeypatch):
    monkeypatch.setenv("SMS_PROVIDER", "twilio")
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "ACtest123")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "tok-test")
    monkeypatch.setenv("TWILIO_FROM_NUMBER", "+15551234567")


def test_twilio_without_credentials_is_honestly_misconfigured(env, monkeypatch):
    monkeypatch.setenv("SMS_PROVIDER", "twilio")
    result = sms.send_sms("+352661811680", "hello")
    assert result["backend"] == "misconfigured"
    assert "TWILIO_ACCOUNT_SID" in result["error"]
    assert sms.sms_configured() is False


def test_twilio_configured_requires_all_three(env, monkeypatch):
    _twilio_env(monkeypatch)
    assert sms.sms_configured() is True
    monkeypatch.delenv("TWILIO_FROM_NUMBER")
    assert sms.sms_configured() is False


def test_twilio_posts_form_with_basic_auth(env, monkeypatch):
    import base64
    import urllib.parse

    _twilio_env(monkeypatch)
    captured = {}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps({"sid": "SMxyz"}).encode()

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["body"] = req.data.decode()
        captured["auth"] = req.get_header("Authorization")
        captured["content_type"] = req.get_header("Content-type")
        return _Resp()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    result = sms.send_sms("+352661811680", "Talaix test")
    assert result == {"backend": "twilio", "provider_message_id": "SMxyz"}
    assert captured["url"] == (
        "https://api.twilio.com/2010-04-01/Accounts/ACtest123/Messages.json")
    assert captured["content_type"] == "application/x-www-form-urlencoded"
    fields = urllib.parse.parse_qs(captured["body"])
    assert fields["To"] == ["+352661811680"]
    assert fields["From"] == ["+15551234567"]
    assert fields["Body"] == ["Talaix test"]
    expected = "Basic " + base64.b64encode(b"ACtest123:tok-test").decode()
    assert captured["auth"] == expected


def test_twilio_http_error_reported_honestly(env, monkeypatch):
    import urllib.error

    _twilio_env(monkeypatch)

    def fake_urlopen(req, timeout=None):
        raise urllib.error.HTTPError(
            req.full_url, 401, "Unauthorized", None,
            io.BytesIO(json.dumps({"message": "Authenticate"}).encode()))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    result = sms.send_sms("+352661811680", "hello")
    assert result["backend"] == "twilio"
    assert "Authenticate" in result["error"]


def test_disabled_backend(env, monkeypatch):
    monkeypatch.setenv("SMS_PROVIDER", "disabled")
    result = sms.send_sms("+306912345678", "hello")
    assert result["backend"] == "disabled"
    assert _sms_files(env["outbox"]) == [] if env["outbox"].exists() else True


def test_valid_e164():
    assert sms.valid_e164("+306912345678")
    assert sms.valid_e164("+15551234567")
    assert sms.valid_e164("00306912345678")          # 00 prefix normalised
    assert sms.valid_e164("+30 691 234 5678")        # separators stripped
    assert sms.valid_e164("+1 (555) 123-4567")
    assert not sms.valid_e164("6912345678")          # missing country code +
    assert not sms.valid_e164("+0123")
    assert not sms.valid_e164("+30691")              # too short
    assert not sms.valid_e164("")
    assert not sms.valid_e164(None)
    assert sms.normalize_e164("00 30 691 234 5678") == "+306912345678"


# ---------------------------------------------------------------------------
# Phone verification flow (API)
# ---------------------------------------------------------------------------

def test_phone_add_verify_flow(client, env):
    headers = _auth_headers(client, env)
    resp = _add_phone(client, headers)
    body = resp.get_json()
    assert body["status"] == "verification_sent"
    assert body["phone"]["e164"] == "+306912345678"
    assert body["phone"]["verified"] is False
    # The code is only delivered via SMS (dev: outbox) — never in the API.
    code = _verification_code(env["outbox"])
    assert code not in json.dumps(body)

    resp = client.post("/api/v2/alerts/phone/verify", json={"code": code},
                       headers=headers)
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()["phone"]["verified"] is True
    # Verification turns SMS on by default.
    assert resp.get_json()["prefs"]["sms_enabled"] is True


def test_phone_verify_wrong_code(client, env):
    headers = _auth_headers(client, env)
    _add_phone(client, headers)
    code = _verification_code(env["outbox"])
    wrong = f"{(int(code) + 1) % 1000000:06d}"
    resp = client.post("/api/v2/alerts/phone/verify", json={"code": wrong},
                       headers=headers)
    assert resp.status_code == 400
    assert "Invalid" in resp.get_json()["error"]


def test_phone_verify_expired_code(client, env):
    headers = _auth_headers(client, env)
    _add_phone(client, headers)
    code = _verification_code(env["outbox"])
    conn = sqlite3.connect(str(env["db"]))
    conn.execute("UPDATE phone_numbers SET verify_expires = '2020-01-01T00:00:00Z'")
    conn.commit()
    conn.close()
    resp = client.post("/api/v2/alerts/phone/verify", json={"code": code},
                       headers=headers)
    assert resp.status_code == 400
    assert "expired" in resp.get_json()["error"].lower()


def test_phone_delete(client, env):
    headers = _auth_headers(client, env)
    _add_phone(client, headers)
    resp = client.delete("/api/v2/alerts/phone", headers=headers)
    assert resp.status_code == 200
    assert resp.get_json()["deleted"] is True
    resp = client.delete("/api/v2/alerts/phone", headers=headers)
    assert resp.status_code == 404


def test_invalid_phone_rejected(client, env):
    headers = _auth_headers(client, env)
    resp = client.post("/api/v2/alerts/phone", json={"phone": "123"},
                       headers=headers)
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Preferences (API)
# ---------------------------------------------------------------------------

def test_preferences_defaults_and_patch(client, env):
    headers = _auth_headers(client, env)
    resp = client.get("/api/v2/alerts/preferences", headers=headers)
    assert resp.status_code == 200
    prefs = resp.get_json()["prefs"]
    assert prefs["sms_enabled"] is False      # on only after verification
    assert prefs["email_enabled"] is True
    assert prefs["quiet_hours"] is None
    assert prefs["language"] == "en"
    assert prefs["max_per_day"] == 10

    resp = client.patch("/api/v2/alerts/preferences",
                        json={"quiet_hours": {"start": "22:00", "end": "07:00"},
                              "language": "el", "max_per_day": 5,
                              "email_enabled": False},
                        headers=headers)
    assert resp.status_code == 200, resp.get_json()
    prefs = resp.get_json()["prefs"]
    assert prefs["quiet_hours"] == {"start": "22:00", "end": "07:00"}
    assert prefs["language"] == "el"
    assert prefs["max_per_day"] == 5
    assert prefs["email_enabled"] is False

    resp = client.patch("/api/v2/alerts/preferences",
                        json={"quiet_hours": None}, headers=headers)
    assert resp.get_json()["prefs"]["quiet_hours"] is None


def test_preferences_report_sms_delivery_state(client, env, monkeypatch):
    """GET /alerts/preferences honestly reports whether a real SMS provider
    is configured (outbox dev default → provider_configured False; an
    HTTP provider with URL → True). No credentials are exposed."""
    headers = _auth_headers(client, env)
    resp = client.get("/api/v2/alerts/preferences", headers=headers)
    assert resp.status_code == 200
    delivery = resp.get_json()["sms_delivery"]
    assert delivery["provider_configured"] is False
    assert "outbox" in delivery["note"]
    assert "SMS_API_KEY" not in resp.get_data(as_text=True)

    monkeypatch.setenv("SMS_PROVIDER", "http")
    monkeypatch.setenv("SMS_HTTP_URL", "https://sms-provider.example/api")
    delivery = client.get("/api/v2/alerts/preferences",
                          headers=headers).get_json()["sms_delivery"]
    assert delivery["provider_configured"] is True


def test_preferences_validation(client, env):
    headers = _auth_headers(client, env)
    resp = client.patch("/api/v2/alerts/preferences",
                        json={"max_per_day": 0}, headers=headers)
    assert resp.status_code == 400
    resp = client.patch("/api/v2/alerts/preferences",
                        json={"max_per_day": 5000}, headers=headers)
    assert resp.status_code == 400
    resp = client.patch("/api/v2/alerts/preferences",
                        json={"quiet_hours": {"start": "25:00", "end": "07:00"}},
                        headers=headers)
    assert resp.status_code == 400
    resp = client.patch("/api/v2/alerts/preferences",
                        json={"language": "klingon!"}, headers=headers)
    assert resp.status_code == 400
    resp = client.patch("/api/v2/alerts/preferences",
                        json={"admin": True}, headers=headers)
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Rules (API) + tier caps + IDOR safety
# ---------------------------------------------------------------------------

def test_rules_crud_and_validation(client, env):
    headers = _auth_headers(client, env)
    resp = _add_rule(client, headers)
    assert resp.status_code == 201, resp.get_json()
    rule = resp.get_json()["rule"]
    assert rule["hazard"] == "wildfire"
    assert rule["severity_threshold"] == "HIGH"
    assert rule["active"] is True

    resp = client.get("/api/v2/alerts/rules", headers=headers)
    assert [r["id"] for r in resp.get_json()["rules"]] == [rule["id"]]

    resp = client.delete(f"/api/v2/alerts/rules/{rule['id']}", headers=headers)
    assert resp.status_code == 200
    resp = client.get("/api/v2/alerts/rules", headers=headers)
    assert resp.get_json()["rules"] == []

    # Invalid hazard / threshold / coordinates are rejected.
    assert _add_rule(client, headers, hazard="volcano").status_code == 400
    assert _add_rule(client, headers, threshold="LOW").status_code == 400
    assert _add_rule(client, headers, lat=91.0).status_code == 400


def test_rules_tier_cap_upgrade_descriptor(client, env):
    headers = _auth_headers(client, env)  # registered: cap 2
    assert _add_rule(client, headers, name="A").status_code == 201
    assert _add_rule(client, headers, name="B").status_code == 201
    resp = _add_rule(client, headers, name="C")
    assert resp.status_code == 403
    body = resp.get_json()
    assert "limit" in body["error"].lower()
    assert body["upgrade"]["required_role"] == "subscriber"
    assert body["upgrade"]["your_role"] == "registered"
    assert "unlocks" in body["upgrade"]


def test_rules_idor_safe(client, env):
    headers_a = _auth_headers(client, env, email="a@example.org")
    headers_b = _auth_headers(client, env, email="b@example.org")
    rule_id = _add_rule(client, headers_a).get_json()["rule"]["id"]
    # User B cannot see or delete user A's rule.
    resp = client.delete(f"/api/v2/alerts/rules/{rule_id}", headers=headers_b)
    assert resp.status_code == 404
    resp = client.get("/api/v2/alerts/rules", headers=headers_b)
    assert resp.get_json()["rules"] == []


def test_alerts_endpoints_require_auth(client, env):
    assert client.get("/api/v2/alerts/preferences").status_code == 401
    assert client.get("/api/v2/alerts/rules").status_code == 401
    assert client.get("/api/v2/alerts/history").status_code == 401
    assert client.post("/api/v2/alerts/phone", json={"phone": "+306912345678"}).status_code == 401


# ---------------------------------------------------------------------------
# Engine: severity + transition matrix
# ---------------------------------------------------------------------------

def test_classify_severity():
    assert alert_engine.classify_severity(None) is None
    assert alert_engine.classify_severity(10.0) == "NORMAL"
    assert alert_engine.classify_severity(24.9) == "NORMAL"
    assert alert_engine.classify_severity(25.0) == "MODERATE"
    assert alert_engine.classify_severity(44.9) == "MODERATE"
    assert alert_engine.classify_severity(45.0) == "HIGH"
    assert alert_engine.classify_severity(64.9) == "HIGH"
    assert alert_engine.classify_severity(65.0) == "EXTREME"
    assert alert_engine.classify_severity(100.0) == "EXTREME"


def test_transition_matrix():
    et = alert_engine.evaluate_transition
    # Upward crossing of the rule threshold notifies.
    assert et("MODERATE", "HIGH", "HIGH") == (True, "threshold_crossing")
    assert et("NORMAL", "EXTREME", "HIGH") == (True, "threshold_crossing")
    assert et(None, "HIGH", "HIGH") == (True, "threshold_crossing")
    # HIGH → EXTREME notifies when the threshold is EXTREME.
    assert et("HIGH", "EXTREME", "EXTREME") == (True, "threshold_crossing")
    # Downward recovery back below the threshold notifies.
    assert et("EXTREME", "MODERATE", "HIGH") == (True, "recovery")
    assert et("EXTREME", "HIGH", "EXTREME") == (True, "recovery")
    # Same-severity re-checks and same-side moves stay silent.
    assert et("HIGH", "HIGH", "HIGH") == (False, None)
    assert et("MODERATE", "NORMAL", "HIGH") == (False, None)
    assert et("EXTREME", "EXTREME", "EXTREME") == (False, None)
    # No computable severity never notifies.
    assert et("HIGH", None, "HIGH") == (False, None)


def test_sms_message_format():
    message = alert_engine.build_sms_message(
        "wildfire", "Kifisia, Athens", "EXTREME", "FWI 52.3 (Extreme)",
        "Increase monitoring frequency and preparedness level.",
        "2026-08-17 12:00")
    assert "HYDRASHIELD ALERT" in message
    assert "Wildfire: EXTREME" in message
    assert "Kifisia, Athens" in message
    assert "Main driver: FWI 52.3 (Extreme)" in message
    assert "Action: Increase monitoring" in message
    assert "2026-08-17 12:00 UTC" in message
    assert "talaix.com" in message
    assert len(message) <= 320


# ---------------------------------------------------------------------------
# Engine: dispatch semantics (dedupe, quiet hours, daily cap, routing)
# ---------------------------------------------------------------------------

def _verified_user(store, env, email="fanis@example.org"):
    user = _make_user(env, email)
    result = store.upsert_phone(user["id"], "+306912345678")
    store.verify_phone(user["id"], result["code"])
    store.update_prefs(user["id"], sms_enabled=True)
    return user


def test_dispatch_sends_sms_and_email(store, env):
    user = _verified_user(store, env)
    rule = _rule(store, user["id"])
    mailer, sms_fake = FakeMailer(), FakeSms(backend="http")
    result = alert_engine.dispatch_alert(
        store, user, rule, _wildfire_analysis(),
        mailer=mailer, sms=sms_fake, severity="EXTREME",
        trigger="threshold_crossing")
    assert result["status"] == "dispatched"
    assert result["sent"] is True
    assert len(sms_fake.sent) == 1
    assert "HYDRASHIELD ALERT" in sms_fake.sent[0]["message"]
    assert len(mailer.sent) == 1
    history = store.list_history(user["id"])
    assert len(history) == 1
    record = history[0]
    assert record["severity"] == "EXTREME"
    assert record["trigger"] == "threshold_crossing"
    assert record["analysis_id"] == "2026-08-17T00:00:00Z"
    assert record["data_version"] == "real-analysis:Extreme"
    statuses = {d["channel"]: d["status"] for d in record["deliveries"]}
    assert statuses == {"sms": "sent", "email": "outbox"}


def test_dispatch_dedupe_suppressed_duplicate(store, env):
    user = _verified_user(store, env)
    rule = _rule(store, user["id"])
    sms_fake = FakeSms()
    first = alert_engine.dispatch_alert(
        store, user, rule, _wildfire_analysis(), mailer=FakeMailer(),
        sms=sms_fake, severity="EXTREME", trigger="threshold_crossing")
    assert first["status"] == "dispatched"
    # Same rule+hazard+severity+trigger inside the 6 h cooldown: no send.
    second = alert_engine.dispatch_alert(
        store, user, rule, _wildfire_analysis(), mailer=FakeMailer(),
        sms=sms_fake, severity="EXTREME", trigger="threshold_crossing")
    assert second["status"] == "suppressed_duplicate"
    assert len(sms_fake.sent) == 1  # nothing new sent
    history = store.list_history(user["id"])
    assert len(history) == 2
    suppressed = [h for h in history if h["suppressed"]]
    assert len(suppressed) == 1
    assert suppressed[0]["deliveries"][0]["status"] == "suppressed_duplicate"


def test_dispatch_quiet_hours_holds_sms_but_sends_email(store, env):
    user = _verified_user(store, env)
    store.update_prefs(user["id"], quiet_hours={"start": "00:00", "end": "23:59"})
    rule = _rule(store, user["id"])
    mailer, sms_fake = FakeMailer(), FakeSms()
    result = alert_engine.dispatch_alert(
        store, user, rule, _wildfire_analysis(), mailer=mailer, sms=sms_fake,
        severity="EXTREME", trigger="threshold_crossing")
    assert result["status"] == "dispatched"
    assert sms_fake.sent == []                # SMS held, not sent
    assert len(mailer.sent) == 1              # email still goes out
    record = store.list_history(user["id"])[0]
    statuses = {d["channel"]: d["status"] for d in record["deliveries"]}
    assert statuses["sms"] == "held_quiet_hours"
    assert statuses["email"] == "outbox"


def test_quiet_hours_window_math():
    prefs = {"quiet_hours": {"start": "22:00", "end": "07:00"}}
    assert alert_engine.in_quiet_hours(prefs, datetime(2026, 1, 1, 23, 0))
    assert alert_engine.in_quiet_hours(prefs, datetime(2026, 1, 1, 3, 0))
    assert not alert_engine.in_quiet_hours(prefs, datetime(2026, 1, 1, 12, 0))
    assert not alert_engine.in_quiet_hours({"quiet_hours": None})


def test_dispatch_max_per_day_enforced(store, env):
    user = _make_user(env)  # email only; no phone
    store.update_prefs(user["id"], max_per_day=1)
    rule = _rule(store, user["id"])
    first = alert_engine.dispatch_alert(
        store, user, rule, _wildfire_analysis(), mailer=FakeMailer(),
        sms=FakeSms(), severity="HIGH", trigger="threshold_crossing")
    assert first["status"] == "dispatched"   # consumes the daily budget of 1
    second = alert_engine.dispatch_alert(
        store, user, rule, _wildfire_analysis(risk=88.0), mailer=FakeMailer(),
        sms=FakeSms(), severity="EXTREME", trigger="threshold_crossing")
    assert second["status"] == "max_per_day_reached"
    history = store.list_history(user["id"])
    assert len(history) == 2
    assert [h for h in history if h["suppressed"]]  # second recorded suppressed


def test_dispatch_sms_disabled_without_verified_phone(store, env):
    user = _make_user(env)
    store.upsert_phone(user["id"], "+306912345678")  # registered, NOT verified
    store.update_prefs(user["id"], sms_enabled=True)
    rule = _rule(store, user["id"])
    sms_fake = FakeSms()
    alert_engine.dispatch_alert(
        store, user, rule, _wildfire_analysis(), mailer=FakeMailer(),
        sms=sms_fake, severity="EXTREME", trigger="threshold_crossing")
    assert sms_fake.sent == []
    record = store.list_history(user["id"])[0]
    statuses = {d["channel"]: d["status"] for d in record["deliveries"]}
    assert statuses["sms"] == "disabled"


def test_process_rule_transition_and_state(store, env):
    user = _verified_user(store, env)
    rule = _rule(store, user["id"], last_severity="MODERATE")
    sms_fake = FakeSms()
    outcome = alert_engine.process_rule(
        store, rule, _wildfire_analysis(), mailer=FakeMailer(), sms=sms_fake)
    assert outcome["trigger"] == "threshold_crossing"
    assert outcome["severity"] == "EXTREME"
    assert len(sms_fake.sent) == 1
    updated = store.get_rule(rule["id"])
    assert updated["last_severity"] == "EXTREME"
    assert updated["last_checked"] is not None

    # Re-check at the same severity: silent.
    outcome = alert_engine.process_rule(
        store, store.get_rule(rule["id"]), _wildfire_analysis(),
        mailer=FakeMailer(), sms=sms_fake)
    assert outcome["trigger"] is None
    assert len(sms_fake.sent) == 1

    # No computable severity: honest skip, state still updated.
    outcome = alert_engine.process_rule(
        store, store.get_rule(rule["id"]), {"analysis": {"risk": {"baseline": None}}},
        mailer=FakeMailer(), sms=sms_fake)
    assert outcome["status"] == "no_computable_severity"


# ---------------------------------------------------------------------------
# Unsubscribe + history isolation
# ---------------------------------------------------------------------------

def test_unsubscribe_disables_sms_and_optionally_rules(client, env):
    headers = _auth_headers(client, env)
    _add_phone(client, headers)
    code = _verification_code(env["outbox"])
    client.post("/api/v2/alerts/phone/verify", json={"code": code}, headers=headers)
    _add_rule(client, headers)

    resp = client.post("/api/v2/alerts/unsubscribe", headers=headers)
    assert resp.status_code == 200
    assert resp.get_json()["sms_enabled"] is False
    prefs = client.get("/api/v2/alerts/preferences", headers=headers).get_json()["prefs"]
    assert prefs["sms_enabled"] is False
    # Rules survive a plain unsubscribe…
    assert len(client.get("/api/v2/alerts/rules", headers=headers).get_json()["rules"]) == 1
    # …but ?rules=1 removes them (full opt-out).
    resp = client.post("/api/v2/alerts/unsubscribe?rules=1", headers=headers)
    assert resp.get_json()["rules_deleted"] == 1
    assert client.get("/api/v2/alerts/rules", headers=headers).get_json()["rules"] == []


def test_history_per_user_isolation(client, env):
    headers_a = _auth_headers(client, env, email="hist-a@example.org")
    headers_b = _auth_headers(client, env, email="hist-b@example.org")
    store = NotifyStore(str(env["db"]))
    user_a = UserStore(str(env["db"])).get_user_by_email("hist-a@example.org")
    rule = _rule(store, user_a["id"])
    alert_engine.dispatch_alert(
        store, user_a, rule, _wildfire_analysis(), mailer=FakeMailer(),
        sms=FakeSms(), severity="EXTREME", trigger="threshold_crossing")

    resp = client.get("/api/v2/alerts/history", headers=headers_a)
    assert resp.status_code == 200
    alerts = resp.get_json()["alerts"]
    assert len(alerts) == 1
    assert alerts[0]["hazard"] == "wildfire"
    assert alerts[0]["deliveries"]

    resp = client.get("/api/v2/alerts/history", headers=headers_b)
    assert resp.get_json()["alerts"] == []


# ---------------------------------------------------------------------------
# Secret hygiene: no credentials or codes in the DB / audit log
# ---------------------------------------------------------------------------

def test_no_credentials_or_codes_in_db(client, env, monkeypatch):
    monkeypatch.setenv("SMS_API_KEY", "testkey-abc123")
    monkeypatch.setenv("SMS_API_SECRET", "testsecret-xyz789")
    headers = _auth_headers(client, env)
    _add_phone(client, headers)
    code = _verification_code(env["outbox"])
    client.post("/api/v2/alerts/phone/verify", json={"code": code}, headers=headers)
    _add_rule(client, headers)

    dump = _db_dump_text(env["db"])
    assert "testkey-abc123" not in dump
    assert "testsecret-xyz789" not in dump
    # The plaintext verification code is never stored (only its HMAC hash,
    # which is itself cleared after successful verification).
    sensitive = _db_dump_text(env["db"], tables=["phone_numbers", "audit_log",
                                                 "alert_deliveries"])
    assert code not in sensitive


def test_audit_entries_have_no_codes_or_targets(client, env, monkeypatch):
    monkeypatch.setenv("SMS_API_KEY", "testkey-abc123")
    headers = _auth_headers(client, env)
    _add_phone(client, headers)
    code = _verification_code(env["outbox"])
    client.post("/api/v2/alerts/phone/verify", json={"code": code}, headers=headers)

    conn = sqlite3.connect(str(env["db"]))
    rows = conn.execute(
        "SELECT action, target, meta_json FROM audit_log").fetchall()
    conn.close()
    assert rows, "expected audit entries"
    assert any(r[0] == "phone_verified" for r in rows)
    blob = json.dumps(rows)
    assert code not in blob
    assert "testkey-abc123" not in blob
    assert "+306912345678" not in blob  # phone numbers stay out of the audit log


# ---------------------------------------------------------------------------
# Periodic checker (scripts/check_alert_rules.py) with fakes
# ---------------------------------------------------------------------------

def _load_check_alert_rules():
    path = os.path.join(os.path.dirname(__file__), "..", "scripts",
                        "check_alert_rules.py")
    spec = importlib.util.spec_from_file_location("check_alert_rules", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_check_alert_rules_fires_exactly_one_alert(env, monkeypatch):
    car = _load_check_alert_rules()

    class FakeAnalyser:
        def analyse_point(self, lat, lon, name=None):
            return _wildfire_analysis(risk=72.0, risk_class="Extreme")

    monkeypatch.setattr(car, "TalaixRealAnalyser", FakeAnalyser)

    store = NotifyStore(str(env["db"]))
    user = _verified_user(store, env, email="checker@example.org")
    store.add_rule(user["id"], "wildfire", 37.9, 23.7,
                   name="Athens", severity_threshold="HIGH")

    assert car.main() == 0

    history = store.list_history(user["id"])
    assert len(history) == 1                      # exactly one alert fired
    record = history[0]
    assert record["severity"] == "EXTREME"
    assert record["trigger"] == "threshold_crossing"
    assert record["data_version"] == "real-analysis:Extreme"
    assert record["suppressed"] is False
    channels = {d["channel"] for d in record["deliveries"]}
    assert channels == {"sms", "email"}
    # The dev SMS outbox holds the real alert message.
    sms_files = _sms_files(env["outbox"])
    assert sms_files, "alert SMS not written to outbox"
    content = sms_files[-1].read_text(encoding="utf-8")
    assert "HYDRASHIELD ALERT" in content
    assert "Wildfire: EXTREME" in content
    assert "Athens" in content

    rule = store.list_rules(user["id"])[0]
    assert rule["last_severity"] == "EXTREME"
    assert rule["last_checked"] is not None

    # A second run at the same severity fires nothing new.
    assert car.main() == 0
    assert len(store.list_history(user["id"])) == 1


# ---------------------------------------------------------------------------
# End-to-end with a mock HTTP provider (proves the delivery chain without
# a real provider account; no real SMS is ever sent)
# ---------------------------------------------------------------------------

@pytest.fixture()
def mock_sms_provider(monkeypatch):
    """A local HTTP server honouring the provider contract:
    POST {"to","from","message"} → {"message_id": ...}."""
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
            received.append(body)
            payload = json.dumps(
                {"message_id": f"mock-{len(received):04d}"}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):  # silence
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}/sms"
    monkeypatch.setenv("SMS_PROVIDER", "http")
    monkeypatch.setenv("SMS_HTTP_URL", url)
    monkeypatch.setenv("SMS_FROM", "Talaix")
    yield {"url": url, "received": received}
    server.shutdown()


def test_full_sms_chain_via_mock_provider(client, env, mock_sms_provider):
    """Registration → verification code via provider → verify → rule →
    dispatch → provider message id recorded → status 'sent'."""
    headers = _auth_headers(client, env)

    resp = _add_phone(client, headers)
    assert resp.get_json()["delivery_backend"] == "http"
    assert mock_sms_provider["received"], "provider received no SMS"
    code_msg = mock_sms_provider["received"][-1]
    assert code_msg["to"] == "+306912345678"
    code = re.search(r"code: (\d{6})", code_msg["message"]).group(1)

    resp = client.post("/api/v2/alerts/phone/verify", json={"code": code},
                       headers=headers)
    assert resp.status_code == 200

    resp = _add_rule(client, headers)
    assert resp.status_code == 201

    # Dispatch a fired alert through the engine.
    store = NotifyStore(str(env["db"]))
    user = UserStore(str(env["db"])).get_user_by_email("user@example.org")
    rule = store.list_rules(user["id"])[0]
    analysis = {"analysis": {"risk": {"baseline": 75.0, "class": "Extreme"}},
                "fire_danger": {"fwi": 40.0, "class": "Extreme"},
                "summary": "Extreme fire weather."}
    result = alert_engine.dispatch_alert(
        store, user, rule, analysis,
        mailer=FakeMailer(), sms=sms, severity="EXTREME",
        trigger="threshold_crossing")
    assert result["sent"] is True
    sms_delivery = next(d for d in result["deliveries"] if d["channel"] == "sms")
    assert sms_delivery["status"] == "sent"

    # The provider message id is persisted on the delivery row.
    with sqlite3.connect(str(env["db"])) as conn:
        row = conn.execute(
            "SELECT status, provider_message_id FROM alert_deliveries "
            "WHERE channel = 'sms' ORDER BY id DESC").fetchone()
    assert row[0] == "sent"
    assert row[1] == "mock-0002"  # second provider call (after the code SMS)


def test_sms_delivery_state_reported_honestly(client, env):
    """Without a provider the API must not pretend delivery is possible."""
    headers = _auth_headers(client, env)
    resp = client.get("/api/v2/alerts/preferences", headers=headers)
    delivery = resp.get_json()["sms_delivery"]
    assert delivery["provider_configured"] is False
    assert "outbox" in delivery["note"]
