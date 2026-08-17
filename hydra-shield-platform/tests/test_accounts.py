"""Tests for user accounts, the v2 auth API, and report metadata.

Fully offline: each test gets an isolated tmp SQLite DB (HYDRASHIELD_CACHE_DB)
and the mailer runs on the dev outbox backend (SMTP_HOST unset) — emails are
asserted as .eml files, never sent.
"""

import email as email_lib
import email.policy  # noqa: F401  (registers email_lib.policy)
import io
import json
import os
import re
import sqlite3
import sys

import pytest

from src.dashboard.accounts import UserStore, hash_token  # noqa: E402
from src.dashboard.api import create_app  # noqa: E402


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """Isolated DB + outbox per test; dev email backend guaranteed."""
    db_path = tmp_path / "accounts.sqlite3"
    monkeypatch.setenv("HYDRASHIELD_CACHE_DB", str(db_path))
    monkeypatch.setenv("HYDRASHIELD_OUTBOX_DIR", str(tmp_path / "outbox"))
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.delenv("SMTP_USER", raising=False)
    import src.dashboard.cache as cache_mod

    monkeypatch.setattr(cache_mod, "_default_cache", None)
    return {"db": db_path, "outbox": tmp_path / "outbox"}


@pytest.fixture()
def store(env):
    return UserStore(str(env["db"]))


@pytest.fixture()
def client(env):
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _eml_parts(outbox_dir, template):
    """(raw_text, decoded_plain_body) of the newest <template> outbox mail."""
    files = sorted(outbox_dir.glob(f"*_{template}_*.eml"))
    assert files, f"no {template} email in outbox"
    raw = files[-1].read_text(encoding="utf-8")
    msg = email_lib.message_from_string(raw, policy=email_lib.policy.default)
    body = msg.get_body(("plain",))
    plain = body.get_content() if body else ""
    return raw, plain


def _eml_text(outbox_dir, template):
    raw, plain = _eml_parts(outbox_dir, template)
    return raw + "\n" + plain


def _verification_token(outbox_dir):
    # Extract from the decoded plain body only — the raw MIME part is
    # quoted-printable and would corrupt the match ("token=3D…").
    _, plain = _eml_parts(outbox_dir, "email_verification")
    match = re.search(r"token=([A-Za-z0-9_\-]+)", plain)
    assert match, "no verification token in email"
    return match.group(1)


def _register(client, email="user@example.org", password="correct horse battery"):
    resp = client.post("/api/v2/auth/register",
                       json={"email": email, "password": password,
                             "display_name": "Test User", "consent": True})
    assert resp.status_code == 201, resp.get_json()
    return resp


def _register_and_verify(client, env, email="user@example.org",
                         password="correct horse battery"):
    _register(client, email, password)
    token = _verification_token(env["outbox"])
    resp = client.get(f"/api/v2/auth/verify?token={token}")
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    return body["user"], body["session_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Full register → verify → login → session flow
# ---------------------------------------------------------------------------

def test_full_register_verify_login_flow(client, env):
    resp = client.post("/api/v2/auth/register",
                       json={"email": "ria@example.org",
                             "password": "twelve chars!!", "consent": True})
    assert resp.status_code == 201
    assert resp.get_json()["status"] == "pending_verification"

    # Verification email arrived in the dev outbox (never sent).
    eml = _eml_text(env["outbox"], "email_verification")
    assert "To: ria@example.org" in eml
    assert "Verify your HydraShield email address" in eml

    token = _verification_token(env["outbox"])
    resp = client.get(f"/api/v2/auth/verify?token={token}")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "verified"
    assert body["user"]["status"] == "active"
    assert body["user"]["email_verified_at"]
    session = body["session_token"]

    # HttpOnly SameSite=Lax session cookie was set.
    cookie = resp.headers.get("Set-Cookie", "")
    assert "hydrashield_session=" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=Lax" in cookie

    # Bearer token authenticates.
    resp = client.get("/api/v2/account", headers=_auth(session))
    assert resp.status_code == 200
    assert resp.get_json()["user"]["email"] == "ria@example.org"

    # The session cookie authenticates too (test client keeps the jar).
    resp = client.get("/api/v2/account")
    assert resp.status_code == 200

    # Login with the correct password yields a fresh working session.
    resp = client.post("/api/v2/auth/login",
                       json={"email": "ria@example.org",
                             "password": "twelve chars!!"})
    assert resp.status_code == 200
    session2 = resp.get_json()["session_token"]
    assert client.get("/api/v2/account", headers=_auth(session2)).status_code == 200

    # Logout invalidates the session.
    resp = client.post("/api/v2/auth/logout", headers=_auth(session2))
    assert resp.status_code == 200
    assert client.get("/api/v2/account", headers=_auth(session2)).status_code == 401


def test_unauthenticated_account_endpoints_401(client):
    assert client.get("/api/v2/account").status_code == 401
    assert client.get("/api/v2/account/locations").status_code == 401
    assert client.get("/api/v2/account/history").status_code == 401
    assert client.get("/api/v2/account/usage").status_code == 401


# ---------------------------------------------------------------------------
# Failure paths
# ---------------------------------------------------------------------------

def test_login_wrong_password_401(client, env):
    _register_and_verify(client, env, email="bob@example.org")
    resp = client.post("/api/v2/auth/login",
                       json={"email": "bob@example.org",
                             "password": "wrong password!"})
    assert resp.status_code == 401
    assert "Invalid credentials" in resp.get_json()["error"]


def test_login_unverified_403(client, env):
    _register(client, email="unverified@example.org")
    resp = client.post("/api/v2/auth/login",
                       json={"email": "unverified@example.org",
                             "password": "correct horse battery"})
    assert resp.status_code == 403


def test_expired_verification_token_400(client, env, store):
    user = store.register_user("old@example.org", "correct horse battery")
    token = store.create_email_token(user["id"], "verify_email", ttl_seconds=-10)
    resp = client.get(f"/api/v2/auth/verify?token={token}")
    assert resp.status_code == 400


def test_verification_token_single_use(client, env):
    _register(client, email="once@example.org")
    token = _verification_token(env["outbox"])
    assert client.get(f"/api/v2/auth/verify?token={token}").status_code == 200
    assert client.get(f"/api/v2/auth/verify?token={token}").status_code == 400


def test_register_validation(client):
    resp = client.post("/api/v2/auth/register",
                       json={"email": "not-an-email", "password": "long enough pw"})
    assert resp.status_code == 400
    resp = client.post("/api/v2/auth/register",
                       json={"email": "ok@example.org", "password": "short"})
    assert resp.status_code == 400


def test_duplicate_registration_409(client, env):
    _register(client, email="dup@example.org")
    resp = client.post("/api/v2/auth/register",
                       json={"email": "dup@example.org",
                             "password": "another long password"})
    assert resp.status_code == 409


def test_resend_verification(client, env):
    _register(client, email="resend@example.org")
    resp = client.post("/api/v2/auth/resend-verification",
                       json={"email": "resend@example.org"})
    assert resp.status_code == 200
    # Indistinguishable response for unknown addresses (no enumeration).
    resp2 = client.post("/api/v2/auth/resend-verification",
                        json={"email": "ghost@example.org"})
    assert resp2.get_json() == resp.get_json()
    # A new working token was emailed.
    token = _verification_token(env["outbox"])
    assert client.get(f"/api/v2/auth/verify?token={token}").status_code == 200


# ---------------------------------------------------------------------------
# Password & token storage
# ---------------------------------------------------------------------------

def test_password_hashing(store, env):
    stored = store.hash_password("my secret password")
    assert stored.startswith("pbkdf2-sha256$")
    assert "my secret password" not in stored
    assert store.verify_password("my secret password", stored) is True
    assert store.verify_password("wrong password", stored) is False
    # Per-user salt: two hashes of the same password differ.
    assert store.hash_password("my secret password") != stored
    # The DB holds the hash, never the plaintext.
    user = store.register_user("hash@example.org", "my secret password")
    with sqlite3.connect(env["db"]) as conn:
        row = conn.execute("SELECT password_hash FROM users WHERE id = ?",
                           (user["id"],)).fetchone()
    assert "my secret password" not in row[0]
    assert row[0].startswith("pbkdf2-sha256$")


def test_tokens_stored_hashed(client, env, store):
    _register(client, email="tok@example.org")
    verify_token = _verification_token(env["outbox"])
    resp = client.get(f"/api/v2/auth/verify?token={verify_token}")
    session_token = resp.get_json()["session_token"]
    with sqlite3.connect(env["db"]) as conn:
        rows = []
        for table in ("sessions", "email_tokens"):
            rows += [r[0] for r in conn.execute(f"SELECT token_hash FROM {table}")]
    assert rows  # both tables have entries
    assert verify_token not in rows
    assert session_token not in rows
    # Stored values are the HMAC hashes of the plaintext tokens.
    assert hash_token(session_token) in rows
    assert hash_token(verify_token) in rows


# ---------------------------------------------------------------------------
# Locations CRUD + per-user isolation
# ---------------------------------------------------------------------------

def test_locations_crud_and_isolation(client, env):
    user_a, tok_a = _register_and_verify(client, env, email="a@example.org")
    user_b, tok_b = _register_and_verify(client, env, email="b@example.org")
    assert user_a["id"] != user_b["id"]

    resp = client.post("/api/v2/account/locations", headers=_auth(tok_a),
                       json={"name": "Home", "lat": 49.9, "lon": 6.1})
    assert resp.status_code == 201
    loc_id = resp.get_json()["location"]["id"]

    resp = client.get("/api/v2/account/locations", headers=_auth(tok_a))
    assert [l["name"] for l in resp.get_json()["locations"]] == ["Home"]

    # User B sees none of A's locations and cannot delete them.
    resp = client.get("/api/v2/account/locations", headers=_auth(tok_b))
    assert resp.get_json()["locations"] == []
    resp = client.delete(f"/api/v2/account/locations/{loc_id}", headers=_auth(tok_b))
    assert resp.status_code == 404

    # Validation.
    resp = client.post("/api/v2/account/locations", headers=_auth(tok_a),
                       json={"name": "Bad", "lat": 95.0, "lon": 0.0})
    assert resp.status_code == 400

    # Owner can delete.
    resp = client.delete(f"/api/v2/account/locations/{loc_id}", headers=_auth(tok_a))
    assert resp.status_code == 200
    resp = client.get("/api/v2/account/locations", headers=_auth(tok_a))
    assert resp.get_json()["locations"] == []


# ---------------------------------------------------------------------------
# History / usage / audit
# ---------------------------------------------------------------------------

def test_history_and_usage_recording(client, env, store):
    user, token = _register_and_verify(client, env, email="hist@example.org")
    store.record_analysis(user["id"], "wildfire", 49.9, 6.1,
                          params={"days": 90}, summary={"risk": 42.0})
    store.record_report(user["id"], "decision", "wildfire", 49.9, 6.1,
                        report_meta={"report_id": "abc123"})
    store.log_usage(user["id"], "/api/analyze", {"tier": "registered"})
    # Another user's data must not leak.
    other = store.register_user("other@example.org", "correct horse battery")
    store.record_analysis(other["id"], "flood", 1.0, 2.0)

    resp = client.get("/api/v2/account/history", headers=_auth(token))
    assert resp.status_code == 200
    body = resp.get_json()
    assert len(body["analyses"]) == 1
    assert body["analyses"][0]["summary"] == {"risk": 42.0}
    assert len(body["reports"]) == 1
    assert body["reports"][0]["report_type"] == "decision"

    resp = client.get("/api/v2/account/usage", headers=_auth(token))
    endpoints = [u["endpoint"] for u in resp.get_json()["usage"]]
    assert "/api/analyze" in endpoints


def test_audit_log_records_security_events_without_secrets(client, env, store):
    password = "correct horse battery"
    user, session_token = _register_and_verify(
        client, env, email="audit@example.org", password=password)
    verify_token = _verification_token(env["outbox"])
    client.post("/api/v2/auth/login",
                json={"email": "audit@example.org", "password": password})
    client.post("/api/v2/auth/logout", headers=_auth(session_token))

    entries = store.list_audit(user["id"])
    actions = [e["action"] for e in entries]
    for expected in ("register", "verify", "login", "logout"):
        assert expected in actions
    blob = json.dumps(entries)
    assert password not in blob
    assert session_token not in blob
    assert verify_token not in blob
    assert hash_token(session_token) not in blob


def test_consent_defaults_to_not_given(client, env):
    """GDPR: registering without an explicit consent field must record
    consent=False — consent is never assumed."""
    import sqlite3

    resp = client.post("/api/v2/auth/register",
                       json={"email": "noconsent@example.org",
                             "password": "twelve chars!!"})
    assert resp.status_code == 201
    with sqlite3.connect(env["db"]) as conn:
        row = conn.execute(
            "SELECT meta_json FROM audit_log WHERE action = 'register'"
            " AND target = 'noconsent@example.org'").fetchone()
    assert row is not None
    assert json.loads(row[0])["consent"] is False


# ---------------------------------------------------------------------------
# Account PATCH
# ---------------------------------------------------------------------------

def test_account_patch_display_name(client, env):
    _, token = _register_and_verify(client, env, email="patch@example.org")
    resp = client.patch("/api/v2/account", headers=_auth(token),
                        json={"display_name": "New Name"})
    assert resp.status_code == 200
    assert resp.get_json()["user"]["display_name"] == "New Name"
    resp = client.patch("/api/v2/account", headers=_auth(token), json={})
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Contact endpoint (public)
# ---------------------------------------------------------------------------

def test_contact_validation(client):
    resp = client.post("/api/v2/contact",
                       json={"email": "bad", "message": "hello there world"})
    assert resp.status_code == 400
    resp = client.post("/api/v2/contact",
                       json={"email": "ok@example.org", "message": "short"})
    assert resp.status_code == 400


def test_contact_sends_acknowledgement_via_outbox(client, env):
    resp = client.post("/api/v2/contact",
                       json={"email": "visitor@example.org", "name": "Vis",
                             "message": "I would like to know more about alerts."})
    assert resp.status_code == 201
    eml = _eml_text(env["outbox"], "contact_acknowledgement")
    assert "To: visitor@example.org" in eml
    assert "We received your message" in eml
    # Anti-abuse: the acknowledgement must NOT echo the submitter's message
    # (otherwise the form becomes a spam relay to arbitrary addresses).
    assert "I would like to know more about alerts." not in eml


def test_contact_message_reaches_platform_inbox(client, env):
    resp = client.post("/api/v2/contact",
                       json={"email": "visitor2@example.org", "name": "Vis",
                             "message": "Platform inbox delivery check."})
    assert resp.status_code == 201
    eml = _eml_text(env["outbox"], "contact_message")
    # The submission itself must reach the platform (default: SMTP_FROM).
    assert "To: info@hydrashield.earth" in eml
    assert "Platform inbox delivery check." in eml
    assert "visitor2@example.org" in eml


def test_contact_rate_limit_5_per_hour(client, env):
    payload = {"email": "rl@example.org",
               "message": "Rate limit probe message."}
    # Two contact calls were already consumed by the tests above sharing the
    # per-IP bucket; fill up to the limit and expect the next to be refused.
    statuses = []
    for _ in range(6):
        statuses.append(client.post("/api/v2/contact", json=payload).status_code)
    assert 429 in statuses
    assert statuses[-1] == 429


# ---------------------------------------------------------------------------
# Alerts (account path)
# ---------------------------------------------------------------------------

def test_alerts_crud(client, env):
    _, token = _register_and_verify(client, env, email="alerts@example.org")
    resp = client.post("/api/v2/account/alerts", headers=_auth(token),
                       json={"hazard": "wildfire", "lat": 37.6, "lon": -6.5,
                             "threshold": {"risk_gte": 65}})
    assert resp.status_code == 201
    alert_id = resp.get_json()["alert"]["id"]
    resp = client.get("/api/v2/account/alerts", headers=_auth(token))
    alerts = resp.get_json()["alerts"]
    assert len(alerts) == 1
    assert alerts[0]["threshold"] == {"risk_gte": 65}
    resp = client.delete(f"/api/v2/account/alerts/{alert_id}", headers=_auth(token))
    assert resp.status_code == 200
    resp = client.delete(f"/api/v2/account/alerts/{alert_id}", headers=_auth(token))
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Report metadata block (Stage 7)
# ---------------------------------------------------------------------------

def _report_payload():
    sys.path.insert(0, os.path.dirname(__file__))
    from test_decision_support import _report_payload as payload
    return payload()


def _pdf_text(pdf: bytes) -> str:
    pypdf = pytest.importorskip("pypdf")
    return "\n".join(page.extract_text() or ""
                     for page in pypdf.PdfReader(io.BytesIO(pdf)).pages)


def test_report_content_id_stable():
    from src.dashboard import report as report_module

    payload = _report_payload()
    assert report_module.REPORT_ENGINE_VERSION == "2.0.0"
    rid = report_module.report_content_id(payload, "decision")
    assert rid == report_module.report_content_id(payload, "decision")
    # Volatile generation timestamp does not change the ID.
    changed = dict(payload, generated_at="2030-01-01T00:00:00Z")
    assert report_module.report_content_id(changed, "decision") == rid
    # Different content / report type changes the ID.
    assert report_module.report_content_id(payload, "simple") != rid


def test_report_pdfs_contain_metadata_block():
    pytest.importorskip("reportlab")
    from src.dashboard import report as report_module

    payload = _report_payload()
    rid = report_module.report_content_id(payload, "decision")
    for report_type in ("simple", "decision", "scientific"):
        text = _pdf_text(report_module.build_report_pdf(
            payload, report_type=report_type))
        assert "Report metadata" in text
        assert "Report ID" in text
        assert "Report engine" in text
        assert "2.0.0" in text
        assert "Data sources" in text
        assert "Evidence status" in text
        assert "Validation status" in text
        assert "NOT VALIDATED" in text  # VALIDATION_STATUS kept visible
        # The analysed location is stated in the metadata block.
        assert "Reportville" in text
    # The stable report ID appears (decision type) incl. in the footer.
    text = _pdf_text(report_module.build_report_pdf(payload, report_type="decision"))
    assert rid in text
    assert f"report {rid}" in text


# ---------------------------------------------------------------------------
# Password reset flow
# ---------------------------------------------------------------------------


def _reset_token(outbox_dir):
    _, plain = _eml_parts(outbox_dir, "password_reset")
    match = re.search(r"reset_token=([A-Za-z0-9_\-]+)", plain)
    assert match, "no reset token in password_reset email"
    return match.group(1)


def test_forgot_password_indistinguishable_for_unknown_email(client, env):
    resp = client.post("/api/v2/auth/forgot-password",
                       json={"email": "nobody@example.org"})
    assert resp.status_code == 200
    assert "If the address is registered" in resp.get_json()["message"]
    # No reset email was written for the unknown address.
    assert not list(env["outbox"].glob("*_password_reset_*.eml"))


def test_password_reset_full_flow(client, env):
    user, session = _register_and_verify(client, env, email="reset@example.org",
                                         password="old password 1")
    # Session works before the reset.
    assert client.get("/api/v2/account", headers=_auth(session)).status_code == 200

    resp = client.post("/api/v2/auth/forgot-password",
                       json={"email": "reset@example.org"})
    assert resp.status_code == 200
    token = _reset_token(env["outbox"])

    # Weak replacement is refused and the token is NOT consumed.
    resp = client.post("/api/v2/auth/reset-password",
                       json={"token": token, "password": "short"})
    assert resp.status_code == 400

    resp = client.post("/api/v2/auth/reset-password",
                       json={"token": token, "password": "new password 123"})
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "password_updated"

    # The token is single-use.
    assert client.post("/api/v2/auth/reset-password",
                       json={"token": token, "password": "another password 9"}
                       ).status_code == 400

    # All previous sessions were invalidated.
    assert client.get("/api/v2/account", headers=_auth(session)).status_code == 401

    # Old password fails, new password logs in.
    assert client.post("/api/v2/auth/login",
                       json={"email": "reset@example.org",
                             "password": "old password 1"}).status_code == 401
    resp = client.post("/api/v2/auth/login",
                       json={"email": "reset@example.org",
                             "password": "new password 123"})
    assert resp.status_code == 200


def test_reset_password_rejects_invalid_token(client):
    resp = client.post("/api/v2/auth/reset-password",
                       json={"token": "not-a-real-token", "password": "whatever 1234"})
    assert resp.status_code == 400
