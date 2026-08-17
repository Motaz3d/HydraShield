"""
Offline tests for event-driven intelligence (Stage 8): webhooks,
significant-change triggers, API keys for external consumers, CORS.

ALL tests are offline: webhook delivery goes through a monkeypatched
``urllib.request.urlopen`` and DNS through a monkeypatched
``socket.gethostbyname`` — no network is ever touched. Email/SMS run on
fakes or the dev outbox backends (SMTP_HOST / SMS_PROVIDER unset).

Covers: webhook CRUD + per-user cap + isolation, the SSRF guard matrix,
HMAC signature correctness over the exact body sent, delivery status
recording (sent|failed|disabled), dispatch_alert firing webhook
deliveries alongside email/SMS, the significant-change matrix (jump >=
threshold fires, small drift silent, missing series skipped honestly),
API key create/list/revoke with plaintext-never-stored, key auth on GET
allowed vs POST denied (read-only), session auth unaffected, CORS
listed/unlisted/auth-path/preflight behaviour, and secret hygiene (no
plaintext keys or webhook entropy in the DB or audit log).
"""

import hashlib
import hmac
import json
import re
import socket
import sqlite3
import urllib.request

import pytest

from src.dashboard import alert_engine, webhooks
from src.dashboard.accounts import UserStore
from src.dashboard.api import create_app
from src.dashboard.notify_store import MAX_WEBHOOKS_PER_USER, NotifyStore


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """Isolated DB + outbox per test; dev SMS/email backends guaranteed."""
    db_path = tmp_path / "webhooks.sqlite3"
    monkeypatch.setenv("HYDRASHIELD_CACHE_DB", str(db_path))
    monkeypatch.setenv("HYDRASHIELD_OUTBOX_DIR", str(tmp_path / "outbox"))
    monkeypatch.delenv("HYDRASHIELD_CORS_ORIGINS", raising=False)
    for var in ("SMTP_HOST", "SMTP_USER", "SMS_PROVIDER", "SMS_HTTP_URL",
                "SMS_FROM", "SMS_API_KEY", "SMS_API_SECRET",
                "SMS_HTTP_AUTH_HEADER"):
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


@pytest.fixture()
def fake_dns(monkeypatch):
    """Deterministic offline DNS: host→IP mapping; IP literals resolve to
    themselves; unknown hosts fail like a real NXDOMAIN."""
    mapping = {
        "hooks.example.com": "93.184.216.34",
        "api.example.org": "203.0.113.10",
        "localhost": "127.0.0.1",
        "internal.lan": "10.1.2.3",
    }

    def _gethostbyname(host):
        if host in mapping:
            return mapping[host]
        try:
            socket.inet_aton(host)
            return host  # IP literal: resolves to itself, no network
        except OSError:
            pass
        raise socket.gaierror(f"Name or service not known: {host}")

    monkeypatch.setattr(socket, "gethostbyname", _gethostbyname)
    return mapping


class FakeResponse:
    def __init__(self, status=200, body=b"{}"):
        self.status = status
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture()
def capture_urlopen(monkeypatch):
    """Monkeypatched urllib.request.urlopen capturing every request."""
    calls = []

    def _urlopen(req, timeout=None):
        calls.append({"req": req, "timeout": timeout})
        return FakeResponse()

    monkeypatch.setattr(urllib.request, "urlopen", _urlopen)
    return calls


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


def _set_role(env, email, role):
    conn = sqlite3.connect(str(env["db"]))
    conn.execute("UPDATE users SET role = ? WHERE email = ?", (role, email))
    conn.commit()
    conn.close()


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


def _verified_user(store, env, email="fanis@example.org"):
    user = _make_user(env, email)
    result = store.upsert_phone(user["id"], "+306912345678")
    store.verify_phone(user["id"], result["code"])
    store.update_prefs(user["id"], sms_enabled=True)
    return user


class FakeMailer:
    def __init__(self):
        self.sent = []

    def send_mail(self, to, template, context, subject_override=None):
        self.sent.append({"to": to, "subject": subject_override or context.get("subject")})
        return {"backend": "outbox", "path": None}


class FakeSms:
    def __init__(self):
        self.sent = []

    def send_sms(self, to, message):
        self.sent.append({"to": to, "message": message})
        return {"backend": "http", "provider_message_id": "fake-1"}


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


WEBHOOK_URL = "https://hooks.example.com/ingest"


# ---------------------------------------------------------------------------
# SSRF guard matrix
# ---------------------------------------------------------------------------

def test_target_allowed_matrix(fake_dns):
    ta = webhooks.target_allowed
    # Non-HTTPS is never allowed.
    assert not ta("http://hooks.example.com/x")
    assert not ta("ftp://hooks.example.com/x")
    assert not ta("hooks.example.com")
    assert not ta("")
    assert not ta(None)
    # Loopback / private / link-local targets are rejected.
    assert not ta("https://localhost/webhook")          # → 127.0.0.1
    assert not ta("https://127.0.0.1/webhook")
    assert not ta("https://10.0.0.5/webhook")
    assert not ta("https://192.168.1.10/webhook")
    assert not ta("https://172.16.3.4/webhook")
    assert not ta("https://169.254.1.1/webhook")        # link-local
    assert not ta("https://internal.lan/x")             # → 10.1.2.3
    # Unresolvable hosts fail closed.
    assert not ta("https://no-such-host.invalid/x")
    # A public HTTPS host is allowed.
    assert ta("https://hooks.example.com/ingest")
    assert ta("https://93.184.216.34/ingest")


# ---------------------------------------------------------------------------
# Signature + delivery statuses
# ---------------------------------------------------------------------------

def test_deliver_webhook_signature_over_exact_body(fake_dns, capture_urlopen):
    secret = "test-signing-secret"
    payload = {"alert_id": "al_1", "severity": "EXTREME"}
    result = webhooks.deliver_webhook(WEBHOOK_URL, secret, "alert_fired", payload)
    assert result["status"] == "sent"
    assert len(capture_urlopen) == 1
    req = capture_urlopen[0]["req"]
    assert capture_urlopen[0]["timeout"] == webhooks.HTTP_TIMEOUT_SECONDS
    body = req.data
    # The signature is HMAC-SHA256 over the exact raw body with the secret.
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    assert req.get_header("X-hydrashield-signature") == f"sha256={expected}"
    parsed = json.loads(body.decode("utf-8"))
    assert parsed["event"] == "alert_fired"
    assert parsed["data"] == payload
    assert parsed["sent_at"]
    assert req.get_header("Content-type") == "application/json"


def test_deliver_webhook_statuses(fake_dns, monkeypatch):
    secret = "s"
    # failed: urlopen raises (network/HTTP error reported, never raised).
    def _boom(req, timeout=None):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(urllib.request, "urlopen", _boom)
    assert webhooks.deliver_webhook(
        WEBHOOK_URL, secret, "alert_fired", {})["status"] == "failed"
    # disabled: target no longer passes the SSRF guard at delivery time.
    assert webhooks.deliver_webhook(
        "https://localhost/x", secret, "alert_fired", {})["status"] == "disabled"
    assert webhooks.deliver_webhook(
        "http://hooks.example.com/x", secret, "alert_fired", {})["status"] == "disabled"


def test_dispatch_webhooks_records_statuses(store, env, fake_dns, monkeypatch):
    user = _make_user(env)
    store.add_webhook(user["id"], WEBHOOK_URL, ["alert_fired"])
    store.add_webhook(user["id"], "https://internal.lan/x", ["alert_fired"])

    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda req, timeout=None: FakeResponse())
    alert_id = store.record_alert(
        user["id"], 1, "wildfire", 37.9, 23.7, "EXTREME",
        "threshold_crossing", "a1", "real-analysis:Extreme")
    results = webhooks.dispatch_webhooks(
        store, user["id"], "alert_fired", {"alert_id": alert_id}, alert_id=alert_id)
    assert {r["status"] for r in results} == {"sent", "disabled"}
    deliveries = store.list_history(user["id"])[0]["deliveries"]
    by_target = {d["target"]: d for d in deliveries}
    assert by_target[WEBHOOK_URL]["channel"] == "webhook"
    assert by_target[WEBHOOK_URL]["status"] == "sent"
    assert by_target["https://internal.lan/x"]["status"] == "disabled"


# ---------------------------------------------------------------------------
# Webhook store CRUD: cap, isolation, secret-once
# ---------------------------------------------------------------------------

def test_webhook_crud_cap_and_isolation(store, env):
    user_a = _make_user(env, "a@example.org")
    user_b = _make_user(env, "b@example.org")

    created = store.add_webhook(user_a["id"], WEBHOOK_URL,
                                ["alert_fired", "significant_change"])
    webhook = created["webhook"]
    assert webhook["url"] == WEBHOOK_URL
    assert webhook["events"] == ["alert_fired", "significant_change"]
    assert webhook["active"] is True
    # The signing secret is returned once at creation and never again.
    assert created["secret"]
    listed = store.list_webhooks(user_a["id"])
    assert len(listed) == 1
    assert "secret" not in listed[0]
    assert "secret_hash" not in listed[0]

    # Invalid events are rejected.
    assert "error" in store.add_webhook(user_a["id"], WEBHOOK_URL, ["explosion"])
    assert "error" in store.add_webhook(user_a["id"], WEBHOOK_URL, [])

    # Per-user cap.
    for _ in range(MAX_WEBHOOKS_PER_USER - 1):
        assert "webhook" in store.add_webhook(user_a["id"], WEBHOOK_URL, ["alert_fired"])
    over = store.add_webhook(user_a["id"], WEBHOOK_URL, ["alert_fired"])
    assert "error" in over and "limit" in over["error"].lower()

    # Per-user isolation: B sees nothing and cannot delete A's webhook.
    assert store.list_webhooks(user_b["id"]) == []
    assert store.delete_webhook(user_b["id"], webhook["id"]) is False
    assert store.delete_webhook(user_a["id"], webhook["id"]) is True
    assert store.list_webhooks(user_a["id"])[0]["id"] != webhook["id"]


def test_webhook_event_filtering(store, env):
    user = _make_user(env)
    store.add_webhook(user["id"], WEBHOOK_URL, ["significant_change"])
    store.add_webhook(user["id"], WEBHOOK_URL, ["alert_fired"])
    assert len(store.list_active_webhooks_for_event(user["id"], "alert_fired")) == 1
    assert len(store.list_active_webhooks_for_event(user["id"], "significant_change")) == 1


# ---------------------------------------------------------------------------
# dispatch_alert: webhooks fire alongside email/SMS
# ---------------------------------------------------------------------------

def test_dispatch_alert_fires_webhook_alongside_sms_email(
        store, env, fake_dns, capture_urlopen):
    user = _verified_user(store, env)
    created = store.add_webhook(user["id"], WEBHOOK_URL, ["alert_fired"])
    rule = _rule(store, user["id"])
    mailer, sms_fake = FakeMailer(), FakeSms()
    result = alert_engine.dispatch_alert(
        store, user, rule, _wildfire_analysis(),
        mailer=mailer, sms=sms_fake, severity="EXTREME",
        trigger="threshold_crossing")
    assert result["status"] == "dispatched"
    assert len(sms_fake.sent) == 1
    assert len(mailer.sent) == 1
    assert len(capture_urlopen) == 1  # the webhook POST went out
    req = capture_urlopen[0]["req"]
    expected = hmac.new(
        created["secret"].encode("utf-8"), req.data, hashlib.sha256).hexdigest()
    assert req.get_header("X-hydrashield-signature") == f"sha256={expected}"
    body = json.loads(req.data.decode("utf-8"))
    assert body["event"] == "alert_fired"
    assert body["data"]["hazard"] == "wildfire"
    assert body["data"]["severity"] == "EXTREME"
    assert body["data"]["trigger"] == "threshold_crossing"
    assert body["data"]["location"] == {"name": "Athens", "lat": 37.9, "lon": 23.7}
    record = store.list_history(user["id"])[0]
    statuses = {(d["channel"], d["status"]) for d in record["deliveries"]}
    assert ("sms", "sent") in statuses
    assert ("email", "outbox") in statuses
    assert ("webhook", "sent") in statuses


def test_dispatch_alert_webhook_failure_never_breaks_other_channels(
        store, env, fake_dns, monkeypatch):
    user = _verified_user(store, env)
    store.add_webhook(user["id"], WEBHOOK_URL, ["alert_fired"])
    rule = _rule(store, user["id"])
    mailer, sms_fake = FakeMailer(), FakeSms()

    def _boom(req, timeout=None):
        raise urllib.error.URLError("timeout")

    monkeypatch.setattr(urllib.request, "urlopen", _boom)
    result = alert_engine.dispatch_alert(
        store, user, rule, _wildfire_analysis(),
        mailer=mailer, sms=sms_fake, severity="EXTREME",
        trigger="threshold_crossing")
    assert result["status"] == "dispatched"
    assert len(sms_fake.sent) == 1 and len(mailer.sent) == 1
    record = store.list_history(user["id"])[0]
    statuses = {(d["channel"], d["status"]) for d in record["deliveries"]}
    assert ("webhook", "failed") in statuses


# ---------------------------------------------------------------------------
# Significant-change trigger
# ---------------------------------------------------------------------------

def test_significant_change_matrix():
    esc = alert_engine.evaluate_significant_change
    # Jump >= threshold fires (24 h and 7 d windows).
    fired, detail = esc([40.0, 40.0, 65.0], window=1, threshold=20.0)
    assert fired and detail["delta"] == 25.0 and detail["direction"] == "rise"
    fired, detail = esc([80.0, 59.9], window=1, threshold=20.0)
    assert fired and detail["direction"] == "fall"
    fired, _ = esc([50.0] * 7 + [71.0], window=7, threshold=20.0)
    assert fired
    # Small drift stays silent.
    fired, detail = esc([40.0, 41.0, 42.0], window=1, threshold=20.0)
    assert not fired and detail["delta"] == 1.0
    fired, _ = esc([50.0] * 7 + [69.9], window=7, threshold=20.0)
    assert not fired
    # Too-short series never fires (nothing interpolated).
    fired, detail = esc([], window=1)
    assert not fired and detail["reason"] == "insufficient_series"
    fired, _ = esc([50.0, 90.0], window=7)
    assert not fired
    # Only 1|7 windows are declared.
    with pytest.raises(ValueError):
        esc([1.0, 2.0], window=3)


def test_daily_risk_scores_from_analysis():
    helper = alert_engine.daily_risk_scores_from_analysis
    # FWI-anchored risk scale: 100 * FWI / (FWI + 25).
    assert helper({"fire_danger": {"series": [{"fwi": 25.0}]}}) == [50.0]
    assert helper({"fire_danger": {"series": [{"fwi": None}]}}) is None
    assert helper({"fire_danger": {}}) is None
    assert helper({}) is None


def test_process_rule_significant_change_fires(store, env):
    user = _verified_user(store, env)
    rule = _rule(store, user["id"], last_severity="EXTREME")  # no transition
    sms_fake = FakeSms()
    outcome = alert_engine.process_rule(
        store, rule, _wildfire_analysis(), mailer=FakeMailer(), sms=sms_fake,
        user=user, daily_scores=[40.0, 40.0, 65.0])
    assert outcome["trigger"] == "significant_change"
    assert outcome["significant_change"]["fired"] is True
    assert outcome["significant_change"]["window_days"] == 1
    assert len(sms_fake.sent) == 1
    record = store.list_history(user["id"])[0]
    assert record["trigger"] == "significant_change"
    assert record["severity"] == "EXTREME"


def test_process_rule_small_drift_silent(store, env):
    user = _verified_user(store, env)
    rule = _rule(store, user["id"], last_severity="EXTREME")
    sms_fake = FakeSms()
    outcome = alert_engine.process_rule(
        store, rule, _wildfire_analysis(), mailer=FakeMailer(), sms=sms_fake,
        user=user, daily_scores=[60.0, 61.0, 62.0])
    assert outcome["trigger"] is None
    assert outcome["significant_change"]["fired"] is False
    assert sms_fake.sent == []
    assert store.list_history(user["id"]) == []


def test_process_rule_missing_series_skips_significant_change(store, env):
    user = _verified_user(store, env)
    rule = _rule(store, user["id"], last_severity="EXTREME")
    outcome = alert_engine.process_rule(
        store, rule, _wildfire_analysis(), mailer=FakeMailer(), sms=FakeSms(),
        user=user)  # no daily_scores → skipped honestly
    assert outcome["trigger"] is None
    assert "significant_change" not in outcome
    assert store.list_history(user["id"]) == []


def test_process_rule_significant_change_deduped(store, env):
    user = _verified_user(store, env)
    rule = _rule(store, user["id"], last_severity="EXTREME")
    sms_fake = FakeSms()
    kwargs = dict(mailer=FakeMailer(), sms=sms_fake, user=user,
                  daily_scores=[40.0, 40.0, 65.0])
    first = alert_engine.process_rule(store, rule, _wildfire_analysis(), **kwargs)
    assert first["trigger"] == "significant_change"
    second = alert_engine.process_rule(
        store, store.get_rule(rule["id"]), _wildfire_analysis(), **kwargs)
    assert second["significant_change"]["dispatch"] == "suppressed_duplicate"
    assert len(sms_fake.sent) == 1  # 6 h dedupe cooldown held


# ---------------------------------------------------------------------------
# Webhook API endpoints
# ---------------------------------------------------------------------------

def test_webhook_endpoints_crud_and_validation(client, env, fake_dns):
    headers = _auth_headers(client, env)
    resp = client.post("/api/v2/account/webhooks",
                       json={"url": WEBHOOK_URL,
                             "events": ["alert_fired", "significant_change"]},
                       headers=headers)
    assert resp.status_code == 201, resp.get_json()
    body = resp.get_json()
    webhook_id = body["webhook"]["id"]
    assert body["secret"]  # shown once
    resp = client.get("/api/v2/account/webhooks", headers=headers)
    listed = resp.get_json()["webhooks"]
    assert len(listed) == 1
    assert "secret" not in json.dumps(listed)
    assert "secret_hash" not in json.dumps(listed)

    # SSRF guard at creation: disallowed targets are 400.
    assert client.post("/api/v2/account/webhooks",
                       json={"url": "http://hooks.example.com/x"},
                       headers=headers).status_code == 400
    assert client.post("/api/v2/account/webhooks",
                       json={"url": "https://localhost/x"},
                       headers=headers).status_code == 400
    assert client.post("/api/v2/account/webhooks",
                       json={"url": "https://10.0.0.1/x"},
                       headers=headers).status_code == 400
    assert client.post("/api/v2/account/webhooks",
                       json={"url": WEBHOOK_URL, "events": ["nope"]},
                       headers=headers).status_code == 400

    resp = client.delete(f"/api/v2/account/webhooks/{webhook_id}", headers=headers)
    assert resp.status_code == 200
    assert client.get("/api/v2/account/webhooks", headers=headers).get_json()["webhooks"] == []


def test_webhook_endpoints_isolation_and_auth(client, env, fake_dns):
    headers_a = _auth_headers(client, env, email="wa@example.org")
    headers_b = _auth_headers(client, env, email="wb@example.org")
    webhook_id = client.post(
        "/api/v2/account/webhooks", json={"url": WEBHOOK_URL},
        headers=headers_a).get_json()["webhook"]["id"]
    assert client.get("/api/v2/account/webhooks", headers=headers_b).get_json()["webhooks"] == []
    assert client.delete(
        f"/api/v2/account/webhooks/{webhook_id}", headers=headers_b).status_code == 404
    # Unauthenticated: 401 (fresh client — the main client carries the
    # session cookie set by the register/verify flow).
    anon = create_app().test_client()
    assert anon.get("/api/v2/account/webhooks").status_code == 401
    assert anon.post("/api/v2/account/webhooks",
                     json={"url": WEBHOOK_URL}).status_code == 401


# ---------------------------------------------------------------------------
# API keys
# ---------------------------------------------------------------------------

def _create_key(client, headers, label="integration"):
    return client.post("/api/v2/account/api-keys",
                       json={"label": label}, headers=headers)


def test_api_key_create_requires_subscriber(client, env):
    headers = _auth_headers(client, env)  # registered tier
    resp = _create_key(client, headers)
    assert resp.status_code == 403
    assert resp.get_json()["upgrade"]["required_role"] == "subscriber"


def test_api_key_lifecycle_and_readonly_auth(client, env):
    headers = _auth_headers(client, env, email="sub@example.org")
    _set_role(env, "sub@example.org", "subscriber")

    resp = _create_key(client, headers, label="gis-integration")
    assert resp.status_code == 201, resp.get_json()
    body = resp.get_json()["api_key"]
    key = body["key"]
    assert key.startswith("hs_")
    assert body["label"] == "gis-integration"

    # List: metadata only — never the plaintext key or its hash.
    resp = client.get("/api/v2/account/api-keys", headers=headers)
    keys = resp.get_json()["api_keys"]
    assert len(keys) == 1
    assert keys[0]["revoked"] is False
    assert key not in json.dumps(keys)
    assert "key_hash" not in json.dumps(keys)

    # Key auth on GET works (read-only semantics). A fresh client is used
    # for key-auth checks: the main client carries the session cookie,
    # which takes precedence over X-API-Key by design.
    anon = create_app().test_client()
    resp = anon.get("/api/v2/account", headers={"X-API-Key": key})
    assert resp.status_code == 200
    assert resp.get_json()["user"]["email"] == "sub@example.org"
    resp = anon.get("/api/v2/account/api-keys", headers={"X-API-Key": key})
    assert resp.status_code == 200

    # Key auth never authenticates mutations: 403 "API keys are read-only".
    resp = anon.post("/api/v2/account/api-keys",
                     json={"label": "nope"}, headers={"X-API-Key": key})
    assert resp.status_code == 403
    assert resp.get_json()["error"] == "API keys are read-only"
    resp = anon.post("/api/v2/account/locations",
                     json={"name": "X", "lat": 1.0, "lon": 2.0},
                     headers={"X-API-Key": key})
    assert resp.status_code == 403
    assert resp.get_json()["error"] == "API keys are read-only"
    resp = anon.patch("/api/v2/account", json={"display_name": "Y"},
                      headers={"X-API-Key": key})
    assert resp.status_code == 403

    # Unknown key: 401.
    assert anon.get("/api/v2/account",
                    headers={"X-API-Key": "hs_unknown"}).status_code == 401

    # Revoke (session auth): the key dies immediately.
    key_id = body["id"]
    resp = client.delete(f"/api/v2/account/api-keys/{key_id}", headers=headers)
    assert resp.status_code == 200
    assert anon.get("/api/v2/account",
                    headers={"X-API-Key": key}).status_code == 401
    keys = client.get("/api/v2/account/api-keys", headers=headers).get_json()["api_keys"]
    assert keys[0]["revoked"] is True
    # Revoking again / someone else's key: 404.
    assert client.delete(
        f"/api/v2/account/api-keys/{key_id}", headers=headers).status_code == 404


def test_api_key_isolation(client, env):
    headers_a = _auth_headers(client, env, email="ka@example.org")
    _set_role(env, "ka@example.org", "subscriber")
    headers_b = _auth_headers(client, env, email="kb@example.org")
    key_id = _create_key(client, headers_a).get_json()["api_key"]["id"]
    assert client.get("/api/v2/account/api-keys", headers=headers_b).get_json()["api_keys"] == []
    assert client.delete(
        f"/api/v2/account/api-keys/{key_id}", headers=headers_b).status_code == 404


def test_session_auth_still_works(client, env):
    headers = _auth_headers(client, env)
    resp = client.get("/api/v2/account", headers=headers)
    assert resp.status_code == 200
    assert resp.get_json()["user"]["email"] == "user@example.org"


# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------

def test_cors_listed_origin_public_get(client, monkeypatch):
    monkeypatch.setenv("HYDRASHIELD_CORS_ORIGINS",
                       "https://app.example.com, https://gis.example.org")
    resp = client.get("/api/health",
                      headers={"Origin": "https://app.example.com"})
    assert resp.status_code == 200
    assert resp.headers.get("Access-Control-Allow-Origin") == "https://app.example.com"
    assert resp.headers.get("Vary") == "Origin"
    assert resp.headers.get("Access-Control-Allow-Methods") == "GET, OPTIONS"
    assert "Access-Control-Allow-Credentials" not in resp.headers


def test_cors_unlisted_origin_gets_nothing(client, monkeypatch):
    monkeypatch.setenv("HYDRASHIELD_CORS_ORIGINS", "https://app.example.com")
    resp = client.get("/api/health",
                      headers={"Origin": "https://evil.example.com"})
    assert resp.status_code == 200
    assert "Access-Control-Allow-Origin" not in resp.headers


def test_cors_auth_path_gets_nothing_even_for_listed_origin(client, monkeypatch):
    monkeypatch.setenv("HYDRASHIELD_CORS_ORIGINS", "https://app.example.com")
    resp = client.get("/api/v2/account",
                      headers={"Origin": "https://app.example.com"})
    assert resp.status_code == 401
    assert "Access-Control-Allow-Origin" not in resp.headers
    resp = client.options("/api/v2/account",
                          headers={"Origin": "https://app.example.com"})
    assert "Access-Control-Allow-Origin" not in resp.headers


def test_cors_preflight_204(client, monkeypatch):
    monkeypatch.setenv("HYDRASHIELD_CORS_ORIGINS", "https://app.example.com")
    resp = client.options("/api/health",
                          headers={"Origin": "https://app.example.com"})
    assert resp.status_code == 204
    assert resp.headers.get("Access-Control-Allow-Origin") == "https://app.example.com"
    assert resp.headers.get("Access-Control-Allow-Methods") == "GET, OPTIONS"
    # Unlisted origin: no preflight short-circuit, no ACAO.
    resp = client.options("/api/health",
                          headers={"Origin": "https://evil.example.com"})
    assert resp.status_code != 204
    assert "Access-Control-Allow-Origin" not in resp.headers


def test_cors_default_same_origin(client, env):
    resp = client.get("/api/health",
                      headers={"Origin": "https://app.example.com"})
    assert resp.status_code == 200
    assert "Access-Control-Allow-Origin" not in resp.headers


# ---------------------------------------------------------------------------
# Secret hygiene
# ---------------------------------------------------------------------------

def test_no_secrets_in_db_or_audit(client, env, fake_dns, capture_urlopen):
    headers = _auth_headers(client, env, email="sec@example.org")
    _set_role(env, "sec@example.org", "subscriber")
    key = _create_key(client, headers).get_json()["api_key"]["key"]
    wh = client.post("/api/v2/account/webhooks", json={"url": WEBHOOK_URL},
                     headers=headers).get_json()
    secret = wh["secret"]

    # Fire one alert so the webhook delivery is recorded too.
    store = NotifyStore(str(env["db"]))
    user = UserStore(str(env["db"])).get_user_by_email("sec@example.org")
    rule = _rule(store, user["id"])
    alert_engine.dispatch_alert(
        store, user, rule, _wildfire_analysis(), mailer=FakeMailer(),
        sms=FakeSms(), severity="EXTREME", trigger="threshold_crossing")

    dump = _db_dump_text(env["db"])
    assert key not in dump                # plaintext API key never stored
    assert "whsec_" not in dump           # webhook secret pre-image never stored
    audit_blob = _db_dump_text(env["db"], tables=["audit_log"])
    assert key not in audit_blob
    assert secret not in audit_blob       # signing secret never audited
    assert "whsec_" not in audit_blob
