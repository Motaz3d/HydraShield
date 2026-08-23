"""Tests for the central mailer (dev outbox backend + SMTP path) and the
monitoring alert migration. Fully offline: no SMTP server is ever contacted
with real credentials; the SMTP path is tested against a fake smtplib."""

import email as email_lib
import email.policy  # noqa: F401  (registers email_lib.policy)
import os

import pytest

os.environ.setdefault("HYDRASHIELD_CACHE_DB", "/tmp/hydrashield_test_mailer_cache.sqlite3")

from src.dashboard import mailer  # noqa: E402
from src.dashboard import monitoring  # noqa: E402


def _read_eml(path):
    """Return (raw_text, decoded_plain_body) for an outbox .eml file."""
    raw = open(path, encoding="utf-8").read()
    msg = email_lib.message_from_string(raw, policy=email_lib.policy.default)
    body = msg.get_body(("plain",))
    plain = body.get_content() if body else ""
    return raw, plain


@pytest.fixture()
def outbox(tmp_path, monkeypatch):
    """Isolated dev outbox with SMTP disabled."""
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.delenv("SMTP_USER", raising=False)
    monkeypatch.setenv("HYDRASHIELD_OUTBOX_DIR", str(tmp_path / "outbox"))
    return tmp_path / "outbox"


def _eml_files(outbox_dir, template=None):
    pattern = f"*_{template}_*.eml" if template else "*.eml"
    return sorted(outbox_dir.glob(pattern))


# ---------------------------------------------------------------------------
# Dev (outbox) backend
# ---------------------------------------------------------------------------

def test_outbox_backend_writes_eml(outbox):
    result = mailer.send_mail(
        "user@example.org", "welcome", {"display_name": " Ria"})
    assert result["backend"] == "outbox"
    assert os.path.exists(result["path"])
    assert result["path"].startswith(str(outbox))
    raw, plain = _read_eml(result["path"])
    assert "Subject: Welcome to Talaix" in raw
    assert "To: user@example.org" in raw
    assert "From: info@talaix.com" in raw
    assert "welcome to Talaix" in plain
    assert "Hello Ria," in plain


def test_outbox_filename_contains_template_and_hash(outbox):
    result = mailer.send_mail("a@b.org", "alert", {"message": "hi"})
    name = os.path.basename(result["path"])
    assert name.endswith(".eml")
    assert "_alert_" in name


def test_template_variable_substitution(outbox):
    result = mailer.send_mail(
        "u@example.org", "email_verification",
        {"display_name": "", "verify_url": "https://x.test/verify?token=ABC",
         "expires_hours": 24})
    _, plain = _read_eml(result["path"])
    assert "https://x.test/verify?token=ABC" in plain
    assert "24 hours" in plain
    assert "{{" not in plain  # no unresolved placeholders


def test_all_templates_render(outbox):
    context = {
        "display_name": " Kim", "name": " Kim", "message": "body text",
        "verify_url": "https://x.test/?token=t", "expires_hours": 24,
        "location": "Testville", "report_type": "decision",
        "report_id": "abc123", "generated_at": "2026-08-17T00:00:00Z",
        "tier": "subscriber", "status": "active", "started_at": "2026-08-17",
    }
    for template in sorted(mailer._TEMPLATE_NAMES):
        result = mailer.send_mail("u@example.org", template, dict(context))
        assert result["backend"] == "outbox"
        assert result["subject"]
        assert os.path.exists(result["path"])


def test_subject_override(outbox):
    result = mailer.send_mail(
        "u@example.org", "alert", {"message": "m"},
        subject_override="Custom subject")
    assert result["subject"] == "Custom subject"
    content = open(result["path"], encoding="utf-8").read()
    assert "Subject: Custom subject" in content


def test_unknown_template_rejected(outbox):
    with pytest.raises(ValueError):
        mailer.send_mail("u@example.org", "no_such_template", {})


# ---------------------------------------------------------------------------
# SMTP backend (fake smtplib — no network, no real credentials)
# ---------------------------------------------------------------------------

class _FakeSMTP:
    instances = []

    def __init__(self, host, port, timeout=None):
        self.host, self.port = host, port
        self.started_tls = False
        self.logged_in = None
        self.sent = []
        _FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self):
        self.started_tls = True

    def login(self, user, password):
        self.logged_in = (user, password)

    def send_message(self, msg):
        self.sent.append(msg)


def test_smtp_backend_when_configured(outbox, monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.test")
    monkeypatch.setenv("SMTP_USER", "hydra-test-user")
    monkeypatch.setenv("SMTP_PASSWORD", "test-only-placeholder")
    monkeypatch.setenv("SMTP_PORT", "587")
    import smtplib

    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)
    _FakeSMTP.instances.clear()
    result = mailer.send_mail("u@example.org", "welcome", {"display_name": ""})
    assert result["backend"] == "smtp"
    assert result["path"] is None
    smtp = _FakeSMTP.instances[0]
    assert smtp.host == "smtp.example.test" and smtp.port == 587
    assert smtp.started_tls is True
    assert smtp.logged_in == ("hydra-test-user", "test-only-placeholder")
    assert len(smtp.sent) == 1
    assert not list(outbox.glob("*.eml"))  # nothing written to the outbox


def test_smtp_legacy_pass_env_accepted(outbox, monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.test")
    monkeypatch.setenv("SMTP_USER", "hydra-test-user")
    monkeypatch.delenv("SMTP_PASSWORD", raising=False)
    monkeypatch.setenv("SMTP_PASS", "legacy-placeholder")
    import smtplib

    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)
    _FakeSMTP.instances.clear()
    mailer.send_mail("u@example.org", "welcome", {"display_name": ""})
    assert _FakeSMTP.instances[0].logged_in == ("hydra-test-user", "legacy-placeholder")


# ---------------------------------------------------------------------------
# monitoring.send_email_alert migration
# ---------------------------------------------------------------------------

def test_monitoring_alert_flows_through_mailer(outbox, monkeypatch):
    captured = {}

    def _fake_send(to, template, context, subject_override=None):
        captured.update(to=to, template=template, context=context,
                        subject_override=subject_override)
        return {"backend": "smtp", "path": None}

    monkeypatch.setattr(mailer, "send_mail", _fake_send)
    sent = monitoring.send_email_alert(
        "watch@example.org", "Talaix alert: High risk at X", "Risk: 80/100")
    assert sent is True  # smtp backend => delivered
    assert captured["to"] == "watch@example.org"
    assert captured["template"] == "alert"
    assert captured["subject_override"] == "Talaix alert: High risk at X"
    assert captured["context"]["message"] == "Risk: 80/100"


def test_monitoring_alert_dev_backend_records_outbox(outbox):
    sent = monitoring.send_email_alert(
        "watch@example.org", "Talaix alert: High risk at X",
        "Location: X\nRisk: 80/100")
    # Dev backend: recorded in the outbox, never sent; False keeps the
    # caller's db_only channel semantics unchanged.
    assert sent is False
    files = _eml_files(outbox, "alert")
    assert len(files) == 1
    raw, plain = _read_eml(files[0])
    assert "Subject: Talaix alert: High risk at X" in raw
    assert "Risk: 80/100" in plain
