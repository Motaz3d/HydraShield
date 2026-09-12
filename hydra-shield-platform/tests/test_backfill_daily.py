"""Tests for scripts/backfill_daily.py."""

import importlib.util
import json
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest


def _load_module(tmp_path, monkeypatch):
    """Import the backfill script into an isolated test environment."""
    db_path = tmp_path / "backfill.sqlite3"
    outbox_dir = tmp_path / "outbox"
    leads_dir = tmp_path / "leads"
    outreach_dir = tmp_path / "outreach"
    leads_dir.mkdir(parents=True)
    outreach_dir.mkdir(parents=True)

    monkeypatch.setenv("HYDRASHIELD_CACHE_DB", str(db_path))
    monkeypatch.setenv("HYDRASHIELD_OUTBOX_DIR", str(outbox_dir))
    for var in ("SMTP_HOST", "SMTP_USER", "HUNTER_API_KEY", "IMAP_HOST"):
        monkeypatch.delenv(var, raising=False)

    script_path = Path(__file__).resolve().parent.parent / "scripts" / "backfill_daily.py"
    spec = importlib.util.spec_from_file_location("backfill_daily", str(script_path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    mod.LEADS_DIR = str(leads_dir)
    mod.OUTREACH_DIR = str(outreach_dir)
    # Use a small, deterministic send window for slot tests.
    mod._WINDOW_START_H = 8
    mod._WINDOW_END_H = 18

    return mod, db_path, leads_dir, outreach_dir


@pytest.fixture()
def backfill_mod(tmp_path, monkeypatch):
    return _load_module(tmp_path, monkeypatch)


@pytest.fixture()
def store(backfill_mod):
    mod, db_path, *_ = backfill_mod
    from src.dashboard.marketing_store import MarketingStore

    return MarketingStore(str(db_path))


def _write_lead(leads_dir, slug, lead):
    path = Path(leads_dir) / f"{slug}.json"
    path.write_text(json.dumps(lead), encoding="utf-8")


def _make_lead(slug, segment, country="NL", org=None, problem="problem", role=""):
    return {
        "slug": slug,
        "organization": org or slug.replace("-", " ").title(),
        "segment": segment,
        "country": country,
        "website": f"https://www.{slug}.example",
        "identified_problem": problem,
        "decision_maker_role": role,
    }


def _add_contact(store, slug, email, verification="OBSERVED"):
    store.add_contacts(slug, [{"email": email, "verification": verification,
                               "source": "https://www.example.com"}])


def test_deficit_math_with_existing_scheduled_rows(backfill_mod, store):
    mod, db_path, leads_dir, _ = backfill_mod
    day = datetime(2026, 9, 12, 10, 0, 0)

    for i in range(3):
        slug = f"consultant-{i}"
        _write_lead(leads_dir, slug, _make_lead(slug, "consultants"))
        _add_contact(store, slug, f"info@{slug}.example")

    plan = mod._plan_day(day, 3, store, mod._load_leads(),
                         mod._contacts_by_slug(store), {}, day)
    assert plan["deficit"] == 3
    assert len(plan["entries"]) == 3

    # Schedule one of them manually.
    store.schedule_send(
        "consultant-0", "info@consultant-0.example", "team",
        "outreach_environmental_consulting", {"organization": "A"},
        "2026-09-12T09:00:00",
    )
    plan = mod._plan_day(day, 3, store, mod._load_leads(),
                         mod._contacts_by_slug(store), {}, day)
    assert plan["deficit"] == 2
    assert len(plan["entries"]) == 2


def test_priority_order_across_segments(backfill_mod, store):
    mod, db_path, leads_dir, _ = backfill_mod
    day = datetime(2026, 9, 12, 10, 0, 0)

    _write_lead(leads_dir, "consultant-a", _make_lead("consultant-a", "consultants"))
    _add_contact(store, "consultant-a", "info@consultant-a.example")
    _write_lead(leads_dir, "compliance-a", _make_lead("compliance-a", "sustainability_compliance"))
    _add_contact(store, "compliance-a", "info@compliance-a.example")
    _write_lead(leads_dir, "eudr-a", _make_lead("eudr-a", "eudr_operators"))
    _add_contact(store, "eudr-a", "info@eudr-a.example")
    _write_lead(leads_dir, "lab-a", _make_lead("lab-a", "research_centers"))
    _add_contact(store, "lab-a", "info@lab-a.example")

    plan = mod._plan_day(day, 3, store, mod._load_leads(),
                         mod._contacts_by_slug(store), {}, day)
    slugs = [e["slug"] for e in plan["entries"]]
    assert slugs[0] == "compliance-a"
    assert "eudr-a" in slugs
    assert "consultant-a" in slugs
    assert "lab-a" not in slugs


def test_dedup_and_idempotency_on_rerun(backfill_mod, store):
    mod, db_path, leads_dir, _ = backfill_mod
    day = datetime(2026, 9, 12, 10, 0, 0)

    for i in range(5):
        slug = f"c-{i}"
        _write_lead(leads_dir, slug, _make_lead(slug, "consultants"))
        _add_contact(store, slug, f"info@{slug}.example")

    plan1 = mod._plan_day(day, 3, store, mod._load_leads(),
                          mod._contacts_by_slug(store), {}, day)
    assert len(plan1["entries"]) == 3
    mod._write_day(plan1, store, dry=False)

    plan2 = mod._plan_day(day, 3, store, mod._load_leads(),
                          mod._contacts_by_slug(store), {}, day)
    assert len(plan2["entries"]) == 0

    rows = store.list_scheduled(status="scheduled")
    assert len(rows) == 3
    slugs = {r["lead_slug"] for r in rows}
    assert len(slugs) == 3


def test_exclusions_filter_out_bad_leads(backfill_mod, store):
    mod, db_path, leads_dir, _ = backfill_mod
    day = datetime(2026, 9, 12, 10, 0, 0)

    cases = {
        "emailed": "consultants",
        "unsubscribed": "consultants",
        "nonobserved": "consultants",
        "dpo": "consultants",
        "already-scheduled": "consultants",
    }
    for slug, segment in cases.items():
        _write_lead(leads_dir, slug, _make_lead(slug, segment))

    _add_contact(store, "emailed", "info@emailed.example")
    store.add_interaction("emailed", type="email", summary="sent")

    _add_contact(store, "unsubscribed", "info@unsubscribed.example")
    store.unsubscribe("unsubscribed")

    _add_contact(store, "nonobserved", "info@nonobserved.example", verification="invalid")

    _add_contact(store, "dpo", "dpo@example.com")

    _add_contact(store, "already-scheduled", "info@already-scheduled.example")
    store.schedule_send(
        "already-scheduled", "info@already-scheduled.example", "team",
        "outreach_environmental_consulting", {"organization": "X"},
        "2099-01-01T09:00:00",
    )

    plan = mod._plan_day(day, 10, store, mod._load_leads(),
                         mod._contacts_by_slug(store), {}, day)
    slugs = {e["slug"] for e in plan["entries"]}
    assert not slugs.intersection(cases.keys())


def test_slot_placement_after_existing_rows_and_window(backfill_mod, store):
    mod, db_path, leads_dir, _ = backfill_mod
    day = datetime(2026, 9, 12, 10, 0, 0)

    slug = "late-consultant"
    _write_lead(leads_dir, slug, _make_lead(slug, "consultants"))
    _add_contact(store, slug, f"info@{slug}.example")

    # Existing approved wave row at 09:00.
    store.schedule_send(
        "existing", "info@existing.example", "team",
        "outreach_environmental_consulting", {"organization": "Existing"},
        "2026-09-12T09:00:00",
    )

    plan = mod._plan_day(day, 3, store, mod._load_leads(),
                         mod._contacts_by_slug(store), {}, day)
    assert len(plan["entries"]) == 1
    assert plan["entries"][0]["send_at"] == "2026-09-12T09:05:00"


def test_window_ended_skips_today(backfill_mod, store):
    mod, db_path, leads_dir, _ = backfill_mod
    mod._WINDOW_START_H = 7
    mod._WINDOW_END_H = 10
    now = datetime(2026, 9, 12, 11, 0, 0)  # window already ended

    slug = "morning-consultant"
    _write_lead(leads_dir, slug, _make_lead(slug, "consultants"))
    _add_contact(store, slug, f"info@{slug}.example")

    plan = mod._plan_day(now, 3, store, mod._load_leads(),
                         mod._contacts_by_slug(store), {}, now)
    assert plan["skipped"] is True
    assert "window has ended" in plan["reason"]
    assert len(plan["entries"]) == 0


def test_non_strategy_segments_never_selected_and_reported(backfill_mod, store):
    mod, db_path, leads_dir, _ = backfill_mod
    day = datetime(2026, 9, 12, 10, 0, 0)

    _write_lead(leads_dir, "lab-a", _make_lead("lab-a", "research_centers"))
    _add_contact(store, "lab-a", "info@lab-a.example")

    leads = mod._load_leads()
    contacts = mod._contacts_by_slug(store)
    emailed, excluded, scheduled_any, outreach_slugs = mod._gather_exclusions(store)
    pool = mod._emailable_pool(leads, contacts, emailed, excluded,
                               scheduled_any, outreach_slugs)

    assert pool["research_centers"]["emailable"] == 1

    plan = mod._plan_day(day, 3, store, leads, contacts, pool, day)
    assert all(e["slug"] != "lab-a" for e in plan["entries"])


def test_newly_enabled_segments_selected_with_correct_templates(backfill_mod, store):
    mod, db_path, leads_dir, _ = backfill_mod
    day = datetime(2026, 9, 12, 10, 0, 0)

    segments = [
        ("insurance", "outreach_insurance"),
        ("banking", "outreach_banking"),
        ("real_estate", "outreach_real_estate"),
        ("governments", "outreach_governments"),
        ("investment", "outreach_investment"),
    ]
    for slug, segment in [(s, s) for s, _ in segments]:
        _write_lead(leads_dir, slug, _make_lead(slug, segment))
        _add_contact(store, slug, f"info@{slug}.example")

    plan = mod._plan_day(day, 10, store, mod._load_leads(),
                         mod._contacts_by_slug(store), {}, day)
    expected = {seg: tpl for seg, tpl in segments}
    selected = {e["slug"]: e["template"] for e in plan["entries"]}
    for seg, tpl in expected.items():
        assert seg in selected, f"{seg} not selected"
        assert selected[seg] == tpl, f"{seg} got {selected[seg]} expected {tpl}"


def test_workdays_skip_weekends(backfill_mod):
    mod, *_ = backfill_mod
    # 2026-09-12 is a Saturday, 2026-09-13 a Sunday.
    workdays, weekends = mod._workdays(datetime(2026, 9, 12, 10, 0, 0), 2)
    assert [d.date().isoformat() for d in workdays] == ["2026-09-14", "2026-09-15"]
    assert [d.date().isoformat() for d in weekends] == ["2026-09-12", "2026-09-13"]
    # A Friday start plans Friday + Monday, never the weekend.
    workdays, weekends = mod._workdays(datetime(2026, 9, 11, 10, 0, 0), 2)
    assert [d.date().isoformat() for d in workdays] == ["2026-09-11", "2026-09-14"]
    assert all(d.weekday() < 5 for d in workdays)
