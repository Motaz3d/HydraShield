"""Compliance outreach wave 1: template, data table and sender script
integrity (human-gated, honesty-checked)."""

import json
import os

from src.dashboard import mailer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE_PATH = os.path.join(
    ROOT, "src", "dashboard", "email_templates",
    "outreach_sustainability_compliance.txt")
JSON_PATH = os.path.join(
    ROOT, "marketing", "outreach", "compliance_wave1.json")
SEND_SCRIPT = os.path.join(ROOT, "scripts", "send_compliance_wave1.py")
PREVIEW_SCRIPT = os.path.join(
    ROOT, "scripts", "send_preview_compliance_wave.py")


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
    # No fabricated urgency: deadlines must not be invented in the template.
    assert "guarantee" not in tpl.lower()


def test_template_renders_clean_with_sample_context():
    entry = next(e for e in _entries() if e.get("to_email"))
    rendered = mailer.render_template(
        "outreach_sustainability_compliance", {
            "contact_name": entry["contact_name"],
            "organization": entry["organization"],
            "country": entry["country"],
            "identified_problem": entry["identified_problem"],
            "relevant_capability": entry["relevant_capability"],
            "recommended_product": "",
            "custom_message": entry["custom_message"],
            "unsubscribe_url": mailer.unsubscribe_mailto(),
        })
    assert "{{" not in rendered["subject"]
    assert "{{" not in rendered["text"]
    assert entry["organization"] in rendered["text"]


def test_wave_entries_are_sourced_and_honest():
    entries = _entries()
    assert len(entries) >= 5
    for entry in entries:
        for field in ("slug", "organization", "country", "claim_status",
                      "source", "date_checked", "send_at"):
            assert entry.get(field), (entry.get("slug"), field)
        assert entry["source"].startswith("https://"), entry["slug"]
        # Entries without an email must declare the webform channel — a
        # missing address is never filled in by guessing.
        if not entry.get("to_email"):
            assert entry.get("channel") == "webform", entry["slug"]


def test_sender_script_is_dry_run_by_default_and_human_gated():
    script = _read(SEND_SCRIPT)
    assert '"--send"' in script
    assert "DRY RUN" in script
    assert "webform" in script
    assert "outreach_sustainability_compliance" in script
    assert "is_unsubscribed" in script
    assert "already_sent" in script


def test_preview_script_targets_official_inbox_only():
    script = _read(PREVIEW_SCRIPT)
    assert 'DEFAULT_TO = "info@talaix.com"' in script
    assert "PREVIEW_TO" in script
