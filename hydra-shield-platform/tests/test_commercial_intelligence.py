"""Offline tests for the Commercial Intelligence & Marketing Radar
(marketing/signals, marketing/events, extended leads schema, and the
copilot subcommands in scripts/marketing_status.py).

Fixtures live in tmp_path workspaces only — never in the committed
workspace. Covers: signal/event/lead provenance enforcement, the
no-fabricated-advertising-spend rule, relationship-history vocabulary,
copilot integrity + subcommands, privacy (aggregate-only demand), and the
no-automatic-outreach guarantee.
"""

import json
import os
import subprocess
import sys

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)

import scripts.marketing_status as ms  # noqa: E402


# ---------------------------------------------------------------------------
# Fixture: a tmp marketing workspace with valid base data
# ---------------------------------------------------------------------------

def _write(base, rel, obj):
    path = os.path.join(base, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if isinstance(obj, str):
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(obj)
    else:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(obj, fh)


@pytest.fixture()
def workspace(tmp_path, monkeypatch):
    """Minimal valid workspace: 1 segment, queues, schemas."""
    base = str(tmp_path / "marketing")
    _write(base, "segments/segments.json", {
        "decision_maker_roles_vocabulary": ["CEO", "Risk Manager"],
        "segments": {"insurance": {"pain_points": ["x"],
                                   "relevant_hazards": ["flood"],
                                   "capabilities": ["analysis"],
                                   "decision_maker_roles": ["CEO"],
                                   "content_topics": ["t"], "offer": "o",
                                   "cta": "c", "outreach_style": "s",
                                   "evidence_requirements": "e"}},
    })
    _write(base, "outreach/queue.json", {"rules": ["human review"], "queue": []})
    monkeypatch.setattr(ms, "MARKETING", base)
    return base


def _valid_signal():
    return {
        "id": "sig_test", "organization": "Example Org", "sector": "insurance",
        "country": "DE", "hazards": ["flood"],
        "signal_type": "resilience_programme", "signal_strength": "moderate",
        "source": "Official site", "source_url": "https://example.org/prog",
        "date_observed": "2026-08-01", "date_checked": "2026-08-18",
        "evidence_type": "official_website", "confidence": "medium",
    }


def _valid_event():
    return {
        "event": "Resilience Conf", "organizer": "Org", "location": "Berlin, DE",
        "date": "2026-10-14", "url": "https://example.org/conf",
        "source": "official event page", "sectors": ["insurance"],
        "hazards": ["flood"], "relevance": "high",
        "relevance_reason": "published scope matches", "date_checked": "2026-08-18",
    }


def _valid_lead():
    return {
        "organization": "Example Org", "segment": "insurance", "country": "DE",
        "website": "https://example.org", "contact_type": "organization_generic",
        "source": "https://example.org", "date_checked": "2026-08-18",
        "outreach_status": "qualified", "priority": "high",
        "interactions": [{"date": "2026-08-10", "type": "discovered",
                          "summary": "found via official site"}],
    }


# ---------------------------------------------------------------------------
# Provenance enforcement
# ---------------------------------------------------------------------------


def test_valid_workspace_passes_integrity(workspace):
    _write(workspace, "signals/sig_test.json", _valid_signal())
    _write(workspace, "events/ev.json", _valid_event())
    _write(workspace, "leads/org.json", _valid_lead())
    _segs, _l, _s, _e, _c, problems = ms.workspace_integrity()
    assert problems == []


@pytest.mark.parametrize("missing", ["source_url", "date_checked",
                                     "evidence_type", "date_observed"])
def test_signal_provenance_fields_enforced(workspace, missing):
    sig = _valid_signal()
    del sig[missing]
    _write(workspace, "signals/bad.json", sig)
    problems = ms.workspace_integrity()[-1]
    assert any("bad.json" in p and missing in p for p in problems)


def test_event_provenance_enforced(workspace):
    ev = _valid_event()
    del ev["url"]
    del ev["date_checked"]
    _write(workspace, "events/bad.json", ev)
    problems = ms.workspace_integrity()[-1]
    assert any("bad.json" in p and "url" in p for p in problems)
    assert any("bad.json" in p and "date_checked" in p for p in problems)


def test_lead_required_fields_enforced(workspace):
    lead = _valid_lead()
    del lead["source"]
    del lead["date_checked"]
    _write(workspace, "leads/bad.json", lead)
    problems = ms.workspace_integrity()[-1]
    assert any("bad.json" in p and "source" in p for p in problems)
    assert any("bad.json" in p and "date_checked" in p for p in problems)


def test_no_fabricated_advertising_spend(workspace):
    """Spend-like fields are rejected by the integrity check — only an
    authoritative published figure may ever record spend, and then not in
    this field shape."""
    sig = _valid_signal()
    sig["signal_type"] = "advertising_activity"
    sig["ad_spend_eur"] = 50000
    _write(workspace, "signals/spend.json", sig)
    problems = ms.workspace_integrity()[-1]
    assert any("spend" in p.lower() for p in problems)


def test_relationship_history_vocabulary(workspace):
    lead = _valid_lead()
    lead["interactions"].append({"date": "2026-08-11", "type": "chatted",
                                 "summary": "informal"})
    _write(workspace, "leads/org.json", lead)
    problems = ms.workspace_integrity()[-1]
    assert any("unknown type" in p for p in problems)


def test_unknown_segment_and_sector_flagged(workspace):
    lead = _valid_lead()
    lead["segment"] = "space_tourism"
    _write(workspace, "leads/bad.json", lead)
    sig = _valid_signal()
    sig["sector"] = "space_tourism"
    _write(workspace, "signals/bad.json", sig)
    problems = ms.workspace_integrity()[-1]
    assert any("unknown segment" in p for p in problems)
    assert any("unknown sector" in p for p in problems)


# ---------------------------------------------------------------------------
# Copilot behaviour
# ---------------------------------------------------------------------------


def _run(args, env_extra=None):
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    return subprocess.run([sys.executable,
                           os.path.join(ROOT, "scripts", "marketing_status.py")]
                          + args, capture_output=True, text=True, env=env)


def test_copilot_all_subcommands_run_clean_on_real_workspace():
    """Against the committed (empty-ledger) workspace every subcommand must
    exit 0 with honest output."""
    for cmd in ([], ["signals"], ["sectors"], ["events"], ["priorities"],
                ["followups"], ["content"], ["demand"], ["lessons"],
                ["morning"], ["evening"]):
        result = _run(cmd)
        assert result.returncode == 0, (cmd, result.stdout, result.stderr)
    assert "Segments defined:" in _run([]).stdout


def test_copilot_priorities_and_followups_with_data(workspace):
    lead = _valid_lead()
    lead["next_followup"] = "2020-01-01"  # overdue
    lead["recommended_product"] = "monitoring"
    lead["identified_problem"] = "flood exposure of insured assets"
    _write(workspace, "leads/org.json", lead)
    _write(workspace, "signals/sig.json", _valid_signal())
    _write(workspace, "events/ev.json", _valid_event())
    # Drive the copilot functions directly against the tmp workspace.
    assert ms.cmd_priorities() == 0
    assert ms.cmd_followups() == 0
    assert ms.cmd_signals() == 0
    assert ms.cmd_events() == 0
    assert ms.cmd_sectors() == 0


def test_copilot_no_send_capability():
    """The copilot must not be able to send anything: no SMTP, no HTTP
    client, no network import in the script."""
    src = open(os.path.join(ROOT, "scripts", "marketing_status.py"),
               encoding="utf-8").read()
    for forbidden in ("smtplib", "requests", "urllib.request", "sendmail",
                      "urlopen"):
        assert forbidden not in src, forbidden


def test_demand_is_aggregate_only(tmp_path):
    """The demand view prints counts — never session hashes or user ids."""
    import sqlite3
    db = tmp_path / "a.sqlite3"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE analytics_events (id INTEGER PRIMARY KEY,"
                 " ts TEXT, event TEXT, session_hash TEXT, page TEXT,"
                 " hazard TEXT, lat REAL, lon REAL, feature TEXT,"
                 " referrer TEXT, device TEXT, language TEXT, user_id INTEGER)")
    conn.execute("INSERT INTO analytics_events (ts, event, session_hash, page)"
                 " VALUES ('2026-08-18T00:00:00Z', 'page_view', 'deadbeef', 'map.html')")
    conn.commit()
    conn.close()
    result = _run(["demand"], env_extra={"HYDRASHIELD_CACHE_DB": str(db)})
    assert result.returncode == 0
    assert "deadbeef" not in result.stdout
    assert "Total events: 1" in result.stdout
    assert "map.html" in result.stdout
    assert "aggregate" in result.stdout.lower() or "counts only" in result.stdout


# ---------------------------------------------------------------------------
# Outreach composer (scripts/outreach_composer.py)
# ---------------------------------------------------------------------------

import scripts.outreach_composer as oc  # noqa: E402


def _composer_workspace(tmp_path, monkeypatch):
    base = tmp_path / "marketing"
    (base / "leads").mkdir(parents=True)
    (base / "segments").mkdir(parents=True)
    (base / "outreach").mkdir(parents=True)
    (base / "segments" / "segments.json").write_text(json.dumps({
        "decision_maker_roles_vocabulary": ["Risk Manager"],
        "segments": {"insurance": {"outreach_style": "technical"}},
    }))
    (base / "outreach" / "queue.json").write_text(
        json.dumps({"rules": [], "queue": []}))
    monkeypatch.setattr(oc, "MARKETING", str(base))
    monkeypatch.setattr(oc, "QUEUE", str(base / "outreach" / "queue.json"))
    monkeypatch.setattr(oc, "AUDIT", str(base / "outreach" / "audit.jsonl"))
    return base


def test_composer_requires_evidence():
    """No problem/evidence on the lead → no draft (no generic spam)."""
    with pytest.raises(ValueError):
        oc.compose_draft({"organization": "X"}, {}, "pilot")


def test_composer_draft_personalized_official_sender():
    lead = {"organization": "Stadtwerke Example", "segment": "insurance",
            "decision_maker_role": "Risk Manager",
            "relevant_hazards": ["flood"],
            "identified_problem": "flood exposure of insured assets",
            "evidence": "per-location flood screening with discharge history",
            "recommended_product": "monitoring"}
    draft = oc.compose_draft(lead, {"outreach_style": "technical"},
                             "monitoring pilot", "2026-09-01")
    assert draft["from"] == "info@hydrashield.earth"
    assert "Stadtwerke Example" in draft["body"]
    assert "flood exposure of insured assets" in draft["body"]
    assert "per-location flood screening" in draft["body"]
    assert draft["followup_date"] == "2026-09-01"
    for forbidden in oc.FORBIDDEN_SENDERS:
        assert forbidden not in draft["body"]
        assert forbidden not in draft["from"]


def test_composer_queue_and_audit(tmp_path, monkeypatch):
    base = _composer_workspace(tmp_path, monkeypatch)
    (base / "leads" / "org.json").write_text(json.dumps(
        {"organization": "Example Org", "segment": "insurance",
         "identified_problem": "wildfire exposure",
         "evidence": "FWI-based screening + FIRMS history"}))
    lead = json.loads((base / "leads" / "org.json").read_text())
    draft = oc.compose_draft(lead, {}, "pilot")
    oc.queue_draft("org.json", draft)
    queue = json.loads((base / "outreach" / "queue.json").read_text())
    assert queue["queue"][0]["status"] == "drafted"  # human gate
    assert queue["queue"][0]["from"] == "info@hydrashield.earth"
    audit = (base / "outreach" / "audit.jsonl").read_text().strip()
    assert "draft_created" in audit


def test_composer_never_sends():
    """The composer has no network/SMTP capability at all."""
    src = open(os.path.join(ROOT, "scripts", "outreach_composer.py"),
               encoding="utf-8").read()
    for forbidden in ("smtplib", "requests", "urllib.request", "sendmail"):
        assert forbidden not in src, forbidden


def test_no_personal_gmail_as_sender_anywhere():
    """No HydraShield sender path may use the personal mailboxes. The only
    legitimate occurrence is the FORBIDDEN_SENDERS guard list itself."""
    import re
    pattern = re.compile(r"motaz3d@gmail\.com|motazomarien@gmail\.com")
    for sub in ("src", "website", "scripts", "marketing"):
        for dirpath, _dirs, files in os.walk(os.path.join(ROOT, sub)):
            if "__pycache__" in dirpath:
                continue
            for name in files:
                if not name.endswith((".py", ".js", ".html", ".json")):
                    continue
                path = os.path.join(dirpath, name)
                for lineno, line in enumerate(open(path, encoding="utf-8"), 1):
                    if pattern.search(line) and "FORBIDDEN_SENDERS" not in line:
                        raise AssertionError(
                            f"{path}:{lineno} uses a personal mailbox")


# ---------------------------------------------------------------------------
# Commercial radar (copilot `radar`)
# ---------------------------------------------------------------------------


def test_radar_formula_is_deterministic_and_documented():
    lead = {"organization": "A", "status": "open", "urgency": "high",
            "priority": "high", "commercial_signals": ["sig_test"]}
    signals = [{"id": "sig_test", "organization": "A",
                "signal_strength": "strong"}]
    # urgency 3 + priority 3 + strong signal 3 = 9 (no overdue follow-up)
    assert ms._radar_score(lead, signals) == 9
    lead["next_followup"] = "2020-01-01"
    assert ms._radar_score(lead, signals) == 11
    lead["status"] = "won"
    assert ms._radar_score(lead, signals) < 0  # excluded


def test_radar_runs_on_real_workspace():
    result = _run(["radar"])
    assert result.returncode == 0
    assert "Ranking formula" in result.stdout
