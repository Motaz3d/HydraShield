"""Offline tests for the TX Engine client (hydrashield.tx) — urllib mocked.

No network: ``urllib.request.urlopen`` is replaced with a recorder that
returns canned payloads. Mirrors tests/test_client.py; re-exported into the
main suite by ``tests/test_sdk_tx.py``.
"""

import io
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hydrashield import TalaixError, TxClient  # noqa: E402

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
        calls.append({
            "url": req.full_url,
            "method": req.get_method(),
            "headers": dict(req.header_items()),
            "data": req.data.decode("utf-8") if req.data else None,
            "timeout": timeout,
        })
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
# Introspection URLs
# ---------------------------------------------------------------------------

def test_tx_health_url(http):
    calls, _ = http
    TxClient().health()
    assert _path(calls[0]) == "/api/tx/health"


def test_tx_version_url(http):
    calls, _ = http
    TxClient().version()
    assert _path(calls[0]) == "/api/tx/version"


def test_tx_hazards_url(http):
    calls, _ = http
    TxClient().hazards()
    assert _path(calls[0]) == "/api/tx/hazards"


def test_tx_sources_url(http):
    calls, _ = http
    TxClient().sources()
    assert _path(calls[0]) == "/api/tx/sources"


def test_tx_registry_url(http):
    calls, _ = http
    TxClient().registry()
    assert _path(calls[0]) == "/api/tx/registry"


def test_tx_api_key_header(http):
    calls, _ = http
    TxClient(api_key="hs_test").health()
    assert calls[0]["headers"].get("X-api-key") == "hs_test"


# ---------------------------------------------------------------------------
# analyze — repeated hazard params, depth, name
# ---------------------------------------------------------------------------

def test_tx_analyze_url_minimal(http):
    calls, _ = http
    TxClient().analyze(49.96, 6.03)
    assert _path(calls[0]) == "/api/tx/analyze?lat=49.96&lon=6.03&depth=standard"


def test_tx_analyze_url_full(http):
    calls, _ = http
    TxClient().analyze(49.96, 6.03, hazards=["wildfire", "flood"],
                       depth="deep", name="Clervaux")
    assert _path(calls[0]) == (
        "/api/tx/analyze?lat=49.96&lon=6.03&depth=deep"
        "&hazard=wildfire&hazard=flood&name=Clervaux"
    )


# ---------------------------------------------------------------------------
# run / job / result — the standard Job Object
# ---------------------------------------------------------------------------

def test_tx_run_posts_json_body(http):
    calls, queue = http
    queue.append({"job_id": "TXJ-20260901-abcd1234", "status": "queued"})
    job = TxClient().run(49.96, 6.03, hazards=["wildfire"], depth="deep",
                         name="Clervaux")
    assert job["job_id"] == "TXJ-20260901-abcd1234"
    call = calls[0]
    assert call["method"] == "POST"
    assert _path(call) == "/api/tx/run"
    assert json.loads(call["data"]) == {
        "lat": 49.96, "lon": 6.03, "depth": "deep",
        "hazards": ["wildfire"], "name": "Clervaux",
    }
    assert call["headers"].get("Content-type") == "application/json"


def test_tx_run_minimal_body_omits_optional_keys(http):
    calls, queue = http
    queue.append({"job_id": "J", "status": "queued"})
    TxClient().run(1.0, 2.0)
    assert json.loads(calls[0]["data"]) == {"lat": 1.0, "lon": 2.0,
                                            "depth": "standard"}


def test_tx_job_and_result_urls(http):
    calls, queue = http
    queue.append({"job_id": "J1", "status": "running"})
    queue.append({"analysis_id": "TX-20260901-x", "status": "ok"})
    client = TxClient()
    client.job("J1")
    client.result("J1")
    assert _path(calls[0]) == "/api/tx/jobs/J1"
    assert _path(calls[1]) == "/api/tx/jobs/J1/result"


def test_tx_result_not_ready_raises_409(http):
    _, queue = http
    queue.append((409, {"error": "Job J1 is not finished (status=running).",
                        "status": "running"}))
    with pytest.raises(TalaixError) as excinfo:
        TxClient().result("J1")
    assert excinfo.value.status == 409
    assert "not finished" in excinfo.value.message


def test_tx_job_unknown_raises_404(http):
    _, queue = http
    queue.append((404, {"error": "Unknown job_id: NOPE"}))
    with pytest.raises(TalaixError) as excinfo:
        TxClient().job("NOPE")
    assert excinfo.value.status == 404


# ---------------------------------------------------------------------------
# wait — polling semantics
# ---------------------------------------------------------------------------

def test_tx_wait_polls_then_returns_result(http):
    _, queue = http
    queue.append({"job_id": "J1", "status": "running",
                  "progress": {"completed": 1, "total": 3}})
    queue.append({"job_id": "J1", "status": "succeeded"})
    queue.append({"analysis_id": "TX-20260901-ok", "status": "ok"})
    seen = []
    result = TxClient().wait("J1", interval=0, on_poll=seen.append)
    assert result["analysis_id"] == "TX-20260901-ok"
    assert [s["status"] for s in seen] == ["running", "succeeded"]


def test_tx_wait_accepts_job_payload(http):
    _, queue = http
    queue.append({"job_id": "J1", "status": "succeeded"})
    queue.append({"analysis_id": "TX-x", "status": "ok"})
    result = TxClient().wait({"job_id": "J1"}, interval=0)
    assert result["analysis_id"] == "TX-x"


def test_tx_wait_failed_job_raises_honest_error(http):
    _, queue = http
    queue.append({"job_id": "J1", "status": "failed",
                  "error": "upstream exploded"})
    with pytest.raises(TalaixError) as excinfo:
        TxClient().wait("J1", interval=0)
    assert "upstream exploded" in excinfo.value.message


def test_tx_wait_timeout_raises_408(http):
    _, queue = http
    for _ in range(20):
        queue.append({"job_id": "J1", "status": "running"})
    with pytest.raises(TalaixError) as excinfo:
        TxClient().wait("J1", timeout=0.01, interval=0)
    assert excinfo.value.status == 408
    assert "not finished" in excinfo.value.message
