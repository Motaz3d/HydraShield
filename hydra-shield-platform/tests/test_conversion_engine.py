"""Tests for the conversion engine (website/js/convert.js) and its
analytics integration.

The JS logic is exercised in Node with stubbed browser globals
(tests/harness_convert.js); the analytics whitelist is exercised through
the ingest endpoint.
"""

import json
import os
import subprocess

import pytest

os.environ["HYDRASHIELD_CACHE_DB"] = "/tmp/hydrashield_test_conversion.sqlite3"
if os.path.exists(os.environ["HYDRASHIELD_CACHE_DB"]):
    os.remove(os.environ["HYDRASHIELD_CACHE_DB"])

ROOT = os.path.dirname(__file__)


def test_conversion_thresholds_escalate_in_order():
    """The central conversion policy: no CTA below 2 high-value actions,
    then account → monitor → professional at the declared thresholds."""
    result = subprocess.run(
        ["node", os.path.join(ROOT, "harness_convert.js")],
        capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert out["thresholds"] == {"account_nudge": 2, "monitor_nudge": 3,
                                 "strong_nudge": 5, "business_nudge": 8}
    assert out["tier_at_zero"] is None
    assert out["tier_after_1"] is None
    assert out["tier_after_2"] == "tier_account"
    assert out["tier_after_3"] == "tier_monitor"
    assert out["tier_after_5"] == "tier_professional"
    assert out["tier_after_8"] == "tier_business"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("HYDRASHIELD_CACHE_DB", str(tmp_path / "api.sqlite3"))
    import src.dashboard.cache as cache_mod
    monkeypatch.setattr(cache_mod, "_default_cache", None)
    from src.dashboard.api import create_app

    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def test_conversion_events_accepted_by_whitelist(client):
    for event in ("cta_viewed", "cta_clicked", "funding_viewed",
                  "monitor_started", "sms_interest", "subscription_viewed"):
        resp = client.post("/api/v2/analytics/event",
                           json={"event": event, "page": "intelligence.html"})
        assert resp.status_code == 202, event
        assert resp.get_json()["recorded"] == 1, event


def test_unknown_conversion_event_rejected(client):
    resp = client.post("/api/v2/analytics/event",
                       json={"event": "cta_forced_click_autoplay"})
    assert resp.get_json()["recorded"] == 0


def test_alert_deep_links_carry_location_and_hazard():
    """The 'get alerts' CTAs deep-link into the account SMS flow with the
    analyzed location + hazard (relevant-hazard alerts over generic)."""
    intel = open(os.path.join(ROOT, "..", "website", "js",
                              "intelligence.js"), encoding="utf-8").read()
    assert "account.html?location=" in intel
    assert "&hazard=" in intel and "#sms" in intel
    ev = open(os.path.join(ROOT, "..", "website", "js",
                           "events.js"), encoding="utf-8").read()
    assert "account.html?location=" in ev and "#sms" in ev
    acct = open(os.path.join(ROOT, "..", "website", "js",
                             "account.js"), encoding="utf-8").read()
    assert "prefillRuleFromUrl" in acct and "pendingRuleHazard" in acct


def test_all_high_value_surfaces_run_tier_escalation():
    """Every high-value surface must call HSConvert.evaluate — regression
    guard for conversion coverage."""
    import re
    for page in ("intelligence", "events", "map", "solutions", "economy",
                 "reports", "funding"):
        src = open(os.path.join(ROOT, "..", "website", "js",
                                f"{page}.js"), encoding="utf-8").read()
        assert "HSConvert.evaluate" in src, page
        assert "HSConvert.show" in src, page
