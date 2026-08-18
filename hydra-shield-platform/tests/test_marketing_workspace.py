"""Offline tests for the marketing workspace (marketing/) integrity and
the copilot status script (scripts/marketing_status.py).

The workspace is the persistent marketing knowledge base: segments must
parse and stay within vocabularies, leads must follow the schema's
honesty rules (source + date_checked required), campaigns must reference
real segments, and the status script must run clean against the committed
workspace.
"""

import json
import os
import subprocess
import sys

ROOT = os.path.join(os.path.dirname(__file__), "..")
MARKETING = os.path.join(ROOT, "marketing")
sys.path.insert(0, ROOT)

from scripts.marketing_status import workspace_integrity  # noqa: E402

HAZARDS = {"wildfire", "flood", "drought", "heat", "wind", "coastal",
           "dust", "volcanic"}


def _load(name):
    with open(os.path.join(MARKETING, name), encoding="utf-8") as fh:
        return json.load(fh)


def test_segments_parse_and_stay_in_vocabulary():
    data = _load(os.path.join("segments", "segments.json"))
    segments = data["segments"]
    assert len(segments) >= 15
    vocab = set(data["decision_maker_roles_vocabulary"])
    for name, seg in segments.items():
        for field in ("pain_points", "relevant_hazards", "capabilities",
                      "decision_maker_roles", "content_topics", "offer",
                      "cta", "outreach_style", "evidence_requirements"):
            assert seg.get(field), (name, field)
        assert set(seg["relevant_hazards"]) <= HAZARDS, name
        assert set(seg["decision_maker_roles"]) <= vocab, name


def test_campaigns_reference_real_segments():
    segments, _leads, _signals, _events, campaigns, problems = \
        workspace_integrity()
    assert len(campaigns) >= 5
    assert problems == [], problems
    assert segments  # non-empty


def test_leads_ledger_is_real_or_empty():
    """No fabricated leads: any committed lead must carry the schema's
    required honesty fields. An empty ledger is valid by design."""
    leads_dir = os.path.join(MARKETING, "leads")
    for name in os.listdir(leads_dir):
        if not name.endswith(".json") or name == "schema.json":
            continue
        lead = _load(os.path.join("leads", name))
        for field in ("organization", "segment", "country", "website",
                      "source", "date_checked"):
            assert lead.get(field), (name, field)


def test_outreach_queue_is_human_gated():
    queue_doc = _load(os.path.join("outreach", "queue.json"))
    assert queue_doc.get("queue") == [] or isinstance(queue_doc["queue"], list)
    rules = " ".join(queue_doc.get("rules") or [])
    assert "human" in rules.lower()


def test_status_script_runs_clean():
    result = subprocess.run(
        [sys.executable, os.path.join(ROOT, "scripts", "marketing_status.py")],
        capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Segments defined:" in result.stdout
    assert "INTEGRITY PROBLEMS" not in result.stdout
