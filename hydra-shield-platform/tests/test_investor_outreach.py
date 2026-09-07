"""Investor outreach wave A/B/C: template, data table and scheduler script
integrity (human-gated, honesty-checked, pacing inside the platform cap)."""

import json
import os
from collections import Counter

from src.dashboard import mailer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE_PATH = os.path.join(
    ROOT, "src", "dashboard", "email_templates", "outreach_investor.txt")
JSON_PATH = os.path.join(
    ROOT, "marketing", "outreach", "investor_waves_abc.json")
SCHED_SCRIPT = os.path.join(ROOT, "scripts", "schedule_investor_waves.py")
PREVIEW_SCRIPT = os.path.join(ROOT, "scripts", "preview_investor_waves.py")


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _entries():
    return json.loads(_read(JSON_PATH))


def test_template_exists_and_carries_honesty_markers():
    tpl = _read(TEMPLATE_PATH)
    assert "evidence" in tpl.lower()
    assert "screening" in tpl.lower()
    assert "not assurance" in tpl.lower()
    assert "{{unsubscribe_url}}" in tpl
    assert "{{contact_name}}" in tpl
    # No fabricated urgency or promises in a fundraising template either.
    assert "guarantee" not in tpl.lower()


def test_template_registered_in_mailer():
    rendered = mailer.render_template("outreach_investor", {})
    assert rendered["subject"]


def test_template_renders_clean_with_sample_context():
    entry = next(e for e in _entries() if e.get("to_email"))
    rendered = mailer.render_template("outreach_investor", {
        "contact_name": entry["contact_name"],
        "organization": entry["organization"],
        "thesis_hook": entry["thesis_hook"],
        "portfolio_overlap": entry["portfolio_overlap"],
        "custom_message": entry["custom_message"],
        "unsubscribe_url": mailer.unsubscribe_mailto(),
    })
    assert "{{" not in rendered["subject"]
    assert "{{" not in rendered["text"]
    assert entry["organization"] in rendered["text"]


def test_wave_entries_are_sourced_and_honest():
    entries = _entries()
    email_entries = [e for e in entries if e.get("to_email")]
    assert len(email_entries) >= 10
    for entry in entries:
        for field in ("slug", "organization", "country", "claim_status",
                      "source", "date_checked"):
            assert entry.get(field), (entry.get("slug"), field)
        assert entry["source"].startswith("https://"), entry["slug"]
        # Entries without an email must declare the webform channel — a
        # missing address is never filled in by guessing.
        if not entry.get("to_email"):
            assert entry.get("channel") == "webform", entry["slug"]
            assert entry.get("form_url", "").startswith("https://"), entry["slug"]
        else:
            assert entry.get("send_at"), entry["slug"]


def test_pacing_leaves_room_for_the_compliance_wave():
    """Investor sends stay <= 13/day so investor + compliance (2-3/day on
    Vultr) together respect the platform DAILY_SEND_CAP of 15."""
    per_day = Counter(
        e["send_at"][:10] for e in _entries() if e.get("to_email"))
    assert per_day, "no email entries with send_at"
    assert max(per_day.values()) <= 13, dict(per_day)


def test_deeptechxl_is_never_in_the_wave():
    """DeepTechXL is handled personally by the operator (deck thread)."""
    slugs = {e["slug"] for e in _entries()}
    orgs = " ".join(e["organization"].lower() for e in _entries())
    assert "deeptechxl" not in slugs
    assert "deeptechxl" not in orgs


def test_scheduler_script_is_dry_run_by_default_and_human_gated():
    script = _read(SCHED_SCRIPT)
    assert '"--schedule"' in script
    assert "DRY RUN" in script
    assert "webform" in script
    assert "outreach_investor" in script
    assert "is_unsubscribed" in script
    assert "already_queued" in script


def test_preview_script_never_sends_or_schedules():
    script = _read(PREVIEW_SCRIPT)
    assert "send_mail" not in script
    assert "schedule_send" not in script
    assert "render_template" in script
