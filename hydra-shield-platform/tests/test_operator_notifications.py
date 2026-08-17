"""
Offline tests for operator notifications and sender-alias overrides.

Covers: per-template From aliases (SMTP_FROM_<TEMPLATE>), the generic
operator_notification path (outbox backend, anti-flood bucket), operator
notification on report generation (API wiring), and on watch-alert firing
(check_watches wiring). No SMTP server is ever contacted; no credentials.
"""

import importlib.util
import json
import os
import sys

import pytest

from src.dashboard import mailer


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """Isolated DB + outbox; dev email backend guaranteed."""
    db_path = str(tmp_path / "test.sqlite3")
    monkeypatch.setenv("HYDRASHIELD_CACHE_DB", db_path)
    monkeypatch.setenv("HYDRASHIELD_OUTBOX_DIR", str(tmp_path / "outbox"))
    monkeypatch.delenv("SMTP_HOST", raising=False)
    for var in list(os.environ):
        if var.startswith("SMTP_FROM_"):
            monkeypatch.delenv(var, raising=False)
    from src.dashboard import cache

    cache.default_cache.cache = None  # reset singleton for the tmp DB
    yield {"db": db_path, "outbox": tmp_path / "outbox"}
    cache.default_cache.cache = None


def _eml_text(outbox_dir, template):
    """Raw + decoded plain body of the newest <template> outbox mail
    (raw MIME is quoted-printable and would corrupt plain-text matches)."""
    import email
    import email.policy

    files = sorted(outbox_dir.glob(f"*_{template}_*.eml"))
    assert files, f"no {template} email in outbox"
    raw = files[-1].read_text(encoding="utf-8")
    msg = email.message_from_string(raw, policy=email.policy.default)
    plain = ""
    part = msg.get_body(("plain",))
    if part is not None:
        plain = part.get_content()
    return raw + "\n" + plain


# ---------------------------------------------------------------------------
# Sender alias overrides
# ---------------------------------------------------------------------------


def test_from_for_template_defaults_to_info(env):
    assert mailer.from_for_template("alert") == "info@hydrashield.earth"
    assert mailer.from_for_template("") == "info@hydrashield.earth"


def test_from_for_template_alias_override(env, monkeypatch):
    monkeypatch.setenv("SMTP_FROM_ALERT", "alerts@hydrashield.earth")
    assert mailer.from_for_template("alert") == "alerts@hydrashield.earth"
    # Other templates keep the default.
    assert mailer.from_for_template("welcome") == "info@hydrashield.earth"
    result = mailer.send_mail("u@example.org", "alert", {"message": "m"},
                              subject_override="s")
    content = open(result["path"], encoding="utf-8").read()
    assert "From: alerts@hydrashield.earth" in content


# ---------------------------------------------------------------------------
# operator_notify
# ---------------------------------------------------------------------------


def test_operator_notify_writes_outbox(env):
    mailer._operator_bucket.clear()
    result = mailer.operator_notify(
        "Report generated", "Report type: decision\nLocation: X", kind="test")
    assert result["backend"] == "outbox"
    eml = _eml_text(env["outbox"], "operator_notification")
    assert "To: info@hydrashield.earth" in eml
    assert "Report generated" in eml
    assert "Location: X" in eml


def test_operator_notify_bucket_suppresses_flood(env):
    mailer._operator_bucket.clear()
    for _ in range(mailer._OPERATOR_BUCKET_LIMIT):
        mailer.operator_notify("k", "m", kind="floodtest")
    result = mailer.operator_notify("k", "m", kind="floodtest")
    assert result["backend"] == "suppressed"
    mailer._operator_bucket.clear()


# ---------------------------------------------------------------------------
# Report generation → operator notification (API wiring)
# ---------------------------------------------------------------------------


def test_report_endpoint_notifies_operator(env, monkeypatch):
    from src.dashboard import api as api_module

    fake_analysis = {
        "location": {"name": "Reportopolis", "latitude": 40.0, "longitude": -3.0},
        "generated_at": "2026-08-17T00:00:00Z",
        "analysis": {"risk": {"baseline": 42.0, "class": "Moderate"}},
        "provenance": {},
    }
    monkeypatch.setattr(api_module, "_cached_analysis",
                        lambda lat, lon, name: dict(fake_analysis))
    from src.dashboard import report as report_module

    monkeypatch.setattr(report_module, "build_report_pdf",
                        lambda *a, **kw: b"%PDF-1.4 fake")
    mailer._operator_bucket.clear()

    app = api_module.create_app()
    app.config.update(TESTING=True)
    client = app.test_client()
    resp = client.get("/api/report?lat=40.0&lon=-3.0&type=simple")
    assert resp.status_code == 200

    eml = _eml_text(env["outbox"], "operator_notification")
    assert "Report generated" in eml
    assert "40.0000, -3.0000" in eml  # location as given via lat/lon
    assert "Report type: simple" in eml


# ---------------------------------------------------------------------------
# Watch alert → operator notification (check_watches wiring)
# ---------------------------------------------------------------------------


def _load_check_watches():
    path = os.path.join(os.path.dirname(__file__), "..", "scripts", "check_watches.py")
    spec = importlib.util.spec_from_file_location("check_watches", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_watch_alert_notifies_operator(env, monkeypatch):
    cw = _load_check_watches()

    class FakeStore:
        def list_watches(self):
            return [{"id": "w1" * 16, "location": "Watchville",
                     "lat": 37.6, "lon": -6.5, "email": "sub@example.org",
                     "threshold_risk": 50.0, "last_risk": 10.0}]

        def update_check(self, wid, risk):
            pass

        def record_alert(self, wid, risk, risk_class, channel, payload):
            self.alert = (wid, risk, risk_class, channel)

    class FakeAnalyser:
        def analyse_point(self, lat, lon, name=None):
            return {
                "analysis": {"risk": {"baseline": 65.0, "class": "High"}},
                "fire_danger": {"fwi": 30.0, "class": "High"},
                "generated_at": "2026-08-17T00:00:00Z",
            }

    monkeypatch.setattr(cw, "WatchStore", FakeStore)
    monkeypatch.setattr(cw, "HydraShieldRealAnalyser", FakeAnalyser)
    monkeypatch.setattr(cw, "send_email_alert", lambda *a: False)
    mailer._operator_bucket.clear()

    assert cw.main() == 0
    eml = _eml_text(env["outbox"], "operator_notification")
    assert "Alert condition fired" in eml
    assert "Watchville" in eml
    assert "65.0/100" in eml
    # The subscriber's address is not part of the operator notification body.
    plain = eml.split("\n\n", 1)[-1]
    assert "sub@example.org" not in plain
