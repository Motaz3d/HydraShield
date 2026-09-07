"""Next outreach waves (CSRD companies, insurance fresh batch, consultants
channel): data-table integrity, sourcing, honesty and pacing discipline."""

import json
import os
from collections import Counter

from src.dashboard import mailer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTREACH = os.path.join(ROOT, "marketing", "outreach")
SCHED_SCRIPT = os.path.join(ROOT, "scripts", "schedule_wave.py")
BUILDER_SCRIPT = os.path.join(ROOT, "scripts", "build_consultants_wave1.py")

WAVES = {
    "csrd_companies_wave1.json": "outreach_sustainability_compliance",
    "insurance_fresh_wave.json": "outreach_insurance",
    "consultants_wave1.json": "outreach_environmental_consulting",
}


def _entries(name):
    with open(os.path.join(OUTREACH, name), encoding="utf-8") as fh:
        return json.load(fh)


def test_every_entry_is_sourced_and_honest():
    for name in WAVES:
        for entry in _entries(name):
            for field in ("slug", "organization", "country", "claim_status",
                          "source", "date_checked"):
                assert entry.get(field), (name, entry.get("slug"), field)
            assert entry["source"].startswith("http"), (name, entry["slug"])
            # No email → must be an explicit webform entry; never guessed.
            if not entry.get("to_email"):
                assert entry.get("channel") == "webform", entry["slug"]
                assert entry["form_url"].startswith("https://"), entry["slug"]
            else:
                assert entry.get("send_at"), entry["slug"]


def test_each_email_renders_clean_in_its_template():
    for name, template in WAVES.items():
        entry = next(e for e in _entries(name) if e.get("to_email"))
        rendered = mailer.render_template(template, {
            "contact_name": entry["contact_name"],
            "organization": entry["organization"],
            "country": entry.get("country") or "",
            "identified_problem": entry.get("identified_problem") or "",
            "relevant_capability": entry.get("relevant_capability") or "",
            "recommended_product": "",
            "custom_message": entry.get("custom_message") or "",
            "unsubscribe_url": mailer.unsubscribe_mailto(),
        })
        assert "{{" not in rendered["subject"]
        assert "{{" not in rendered["text"]
        assert entry["organization"] in rendered["text"]


def test_pacing_respects_daily_cap_and_sequence():
    """Per-day sends across ALL waves stay moderate; consultants start only
    after the investor + CSRD/insurance waves finish (operator decision)."""
    investor = json.load(open(os.path.join(
        OUTREACH, "investor_waves_abc.json"), encoding="utf-8"))
    per_day = Counter()
    for data in (investor, *( _entries(n) for n in WAVES )):
        for e in data:
            if e.get("to_email") and e.get("send_at"):
                per_day[e["send_at"][:10]] += 1
    assert per_day, "nothing paced"
    worst = max(per_day.values())
    assert worst <= 15, dict(per_day)
    consultant_days = sorted(
        d for d in per_day if d >= "2026-09-14")
    assert min(e["send_at"] for e in _entries("consultants_wave1.json")
               if e.get("send_at")) >= "2026-09-14"
    assert consultant_days, "consultants not sequenced after the other waves"


def test_no_dpo_or_privacy_mailboxes_anywhere():
    for name in WAVES:
        for entry in _entries(name):
            email = entry.get("to_email")
            if not email:
                continue
            local = email.split("@")[0].lower()
            assert not local.startswith(("dpo", "datenschutz", "privacy",
                                         "protecciondatos", "gdpr")), \
                (name, email)


def test_no_recipient_overlap_between_waves():
    seen = {}
    for name in ("investor_waves_abc.json", *WAVES):
        data = (json.load(open(os.path.join(OUTREACH, name), encoding="utf-8"))
                if name == "investor_waves_abc.json" else _entries(name))
        for e in data:
            em = (e.get("to_email") or "").lower()
            if em:
                assert em not in seen, (em, "in", seen[em], "and", name)
                seen[em] = name


def test_scheduler_is_dry_run_default_and_human_gated():
    script = open(SCHED_SCRIPT, encoding="utf-8").read()
    assert '"--schedule"' in script
    assert "DRY RUN" in script
    assert "webform" in script
    assert "is_unsubscribed" in script
    assert "already_queued" in script


def test_consultants_builder_filters_and_sources():
    script = open(BUILDER_SCRIPT, encoding="utf-8").read()
    assert "OBSERVED" in script           # only verified contacts
    assert "_BAD_LOCAL" in script         # DPO/privacy mailboxes excluded
    assert "_DROP" in script              # explicit drop list (Big-4, QIDs)
    assert 'verification=\'OBSERVED\'' in script or 'verification="OBSERVED"' in script
