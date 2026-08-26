"""Offline tests for the talaix CLI (urllib monkeypatched).

Matches the SDK test style: ``urllib.request.urlopen`` is replaced with a
recorder that returns canned payloads. No network.
"""

from __future__ import annotations

import io
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hydrashield.cli import main  # noqa: E402
from hydrashield.client import TalaixClient  # noqa: E402

BASE = "https://talaix.com"


class _FakeResponse:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def http(monkeypatch):
    """Record requests; respond per queued script (payload or (status, body))."""
    calls = []
    queue = []

    def fake_urlopen(req, timeout=None):
        calls.append({"url": req.full_url, "headers": dict(req.header_items()),
                      "timeout": timeout})
        item = queue.pop(0) if queue else {"ok": True}
        if isinstance(item, tuple):
            status, payload = item
            raise urllib.error.HTTPError(
                req.full_url, status, "error", None,
                io.BytesIO(json.dumps(payload).encode("utf-8")))
        return _FakeResponse(item)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    return calls, queue


def _path(call):
    return call["url"][len(BASE):]


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


def test_health_human(capsys, http):
    calls, queue = http
    queue.append({"status": "ok", "cache": {"entries_live": 123}, "version": "1.0.0"})
    rc = main(["health"])
    captured = capsys.readouterr()
    assert rc == 0
    assert "Talaix API: ok" in captured.out
    assert "123" in captured.out
    assert _path(calls[0]) == "/api/health"


def test_health_json(capsys, http):
    calls, queue = http
    queue.append({"status": "ok", "version": "1.0.0"})
    rc = main(["--json", "health"])
    captured = capsys.readouterr()
    assert rc == 0
    assert json.loads(captured.out)["status"] == "ok"


# ---------------------------------------------------------------------------
# Analyze
# ---------------------------------------------------------------------------


def test_analyze_summary(capsys, http):
    calls, queue = http
    queue.append({
        "hazard_id": "wildfire",
        "status": "ok",
        "level": {"label": "High", "score": 78, "basis": "modelled indicator"},
        "summary": "Dry fuels and strong wind.",
    })
    rc = main(["analyze", "--hazard", "wildfire", "--lat", "37.6", "--lon", "-6.5"])
    captured = capsys.readouterr()
    assert rc == 0
    assert "High" in captured.out
    assert "score 78" in captured.out
    assert "modelled indicator" in captured.out
    assert "Dry fuels" in captured.out
    assert _path(calls[0]) == "/api/v2/analyze?hazard=wildfire&lat=37.6&lon=-6.5"


def test_analyze_unavailable_rendered(capsys, http):
    calls, queue = http
    queue.append({
        "status": "unavailable",
        "unavailable_reason": "upstream source unreachable",
    })
    rc = main(["analyze", "--hazard", "wildfire", "--lat", "37.6", "--lon", "-6.5"])
    captured = capsys.readouterr()
    assert rc == 0
    assert "unavailable" in captured.out
    assert "upstream source unreachable" in captured.out


# ---------------------------------------------------------------------------
# Verify
# ---------------------------------------------------------------------------


def test_verify_prints_checks_and_gaps(capsys, http):
    calls, queue = http
    queue.append({
        "status": "ok",
        "verification_id": "v-123",
        "asset": {"name": "Site", "lat": 49.75, "lon": 6.64},
        "hazard_checks": [
            {"taxonomy_label": "Flood", "claim_status": "MODELLED",
             "level": {"label": "Low"}, "confidence": "medium"},
        ],
        "declared_gaps": [],
    })
    rc = main(["verify", "--lat", "49.75", "--lon", "6.64"])
    captured = capsys.readouterr()
    assert rc == 0
    assert "v-123" in captured.out
    assert "Flood" in captured.out
    assert "MODELLED" in captured.out
    assert "Declared gaps: 0" in captured.out


def test_verify_pdf_download(capsys, http, monkeypatch, tmp_path):
    calls, queue = http
    queue.append({
        "status": "ok",
        "verification_id": "v-123",
        "asset": {"name": "Site", "lat": 49.75, "lon": 6.64},
        "hazard_checks": [],
        "declared_gaps": [],
    })
    monkeypatch.setattr(TalaixClient, "_download", lambda self, url: b"PDFBYTES")
    pdf_path = tmp_path / "report.pdf"
    rc = main(["verify", "--lat", "49.75", "--lon", "6.64", "--pdf", str(pdf_path)])
    captured = capsys.readouterr()
    assert rc == 0
    assert pdf_path.read_bytes() == b"PDFBYTES"
    assert "Wrote 8 bytes" in captured.out


# ---------------------------------------------------------------------------
# Briefs
# ---------------------------------------------------------------------------


def test_briefs_list(capsys, http):
    calls, queue = http
    queue.append({
        "briefs": [
            {"date": "2026-08-25", "kind": "wildfire", "title": "Fire season",
             "sources": [{"name": "x"}]},
        ]
    })
    rc = main(["briefs"])
    captured = capsys.readouterr()
    assert rc == 0
    assert "Fire season" in captured.out
    assert _path(calls[0]) == "/api/v2/briefs"


def test_briefs_kind_filter(capsys, http):
    calls, queue = http
    queue.append({"briefs": []})
    rc = main(["briefs", "--kind", "wildfire"])
    assert rc == 0
    assert _path(calls[0]) == "/api/v2/briefs?kind=wildfire"


def test_brief_detail_renders_sources(capsys, http):
    calls, queue = http
    queue.append({
        "title": "Fire season",
        "date": "2026-08-25",
        "kind": "wildfire",
        "sections": [{"heading": "Intro", "text": "Long text here."}],
        "sources": [
            {"name": "ESA", "date": "2026-08-01", "claim_status": "OBSERVED",
             "url": "https://example.com"},
        ],
    })
    rc = main(["briefs", "br-1"])
    captured = capsys.readouterr()
    assert rc == 0
    assert "Fire season" in captured.out
    assert "Intro" in captured.out
    assert "ESA" in captured.out
    assert "https://example.com" in captured.out
    assert _path(calls[0]) == "/api/v2/briefs/br-1"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


def test_api_error_exit_2(capsys, http):
    calls, queue = http
    queue.append((400, {"error": "bad request", "status": 400}))
    rc = main(["health"])
    captured = capsys.readouterr()
    assert rc == 2
    assert "HTTP 400: bad request" in captured.err


def test_api_error_json_still_prints_payload(capsys, http):
    calls, queue = http
    queue.append((400, {"error": "bad request", "status": 400}))
    rc = main(["--json", "health"])
    captured = capsys.readouterr()
    assert rc == 2
    payload = json.loads(captured.out)
    assert payload["error"] == "bad request"
    assert payload["status"] == 400


def test_url_error_exit_3(capsys, http, monkeypatch):
    def boom(*args, **kwargs):
        raise urllib.error.URLError("no route")
    monkeypatch.setattr(urllib.request, "urlopen", boom)
    rc = main(["health"])
    captured = capsys.readouterr()
    assert rc == 3
    assert "could not reach" in captured.err
    assert "no route" in captured.err


# ---------------------------------------------------------------------------
# Env vars
# ---------------------------------------------------------------------------


def test_env_vars(monkeypatch, http):
    calls, queue = http
    monkeypatch.setenv("TALAIX_BASE_URL", "http://localhost:8051")
    monkeypatch.setenv("TALAIX_API_KEY", "env_key")
    queue.append({"status": "ok"})
    main(["health"])
    assert calls[0]["url"] == "http://localhost:8051/api/health"
    assert calls[0]["headers"].get("X-api-key") == "env_key"


# ---------------------------------------------------------------------------
# New client methods (URL construction)
# ---------------------------------------------------------------------------


def test_verify_asset_url(http):
    calls, _ = http
    TalaixClient().verify_asset(49.75, 6.64, name="Site")
    assert _path(calls[0]) == "/api/v2/verification/asset?lat=49.75&lon=6.64&name=Site"


def test_verification_report_url_string():
    client = TalaixClient()
    assert client.verification_report_url(49.75, 6.64) == (
        BASE + "/api/v2/verification/report?lat=49.75&lon=6.64")
    assert client.verification_report_url(49.75, 6.64, name="Site") == (
        BASE + "/api/v2/verification/report?lat=49.75&lon=6.64&name=Site")


def test_insurance_profile_url(http):
    calls, _ = http
    TalaixClient().insurance_profile(37.6, -6.5, radius_km=25)
    assert _path(calls[0]) == "/api/v2/insurance/profile?lat=37.6&lon=-6.5&radius_km=25"


def test_mapcheck_url(http):
    calls, _ = http
    TalaixClient().mapcheck(46.0542, 14.4707, radius_m=500)
    assert _path(calls[0]) == "/api/v2/mapcheck?lat=46.0542&lon=14.4707&radius_m=500"


def test_briefs_url(http):
    calls, _ = http
    TalaixClient().briefs(kind="wildfire")
    assert _path(calls[0]) == "/api/v2/briefs?kind=wildfire"


def test_brief_url(http):
    calls, _ = http
    TalaixClient().brief("br-1")
    assert _path(calls[0]) == "/api/v2/briefs/br-1"


def test_sustainability_frameworks_url(http):
    calls, _ = http
    TalaixClient().sustainability_frameworks()
    assert _path(calls[0]) == "/api/v2/sustainability/frameworks"
