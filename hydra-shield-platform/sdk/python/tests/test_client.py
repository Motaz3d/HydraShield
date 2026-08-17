"""Offline tests for the HydraShield Python SDK (urllib monkeypatched).

No network: ``urllib.request.urlopen`` is replaced with a recorder that
returns canned payloads. Run directly (``pytest sdk/python/tests/``) or via
the main suite (``tests/test_sdk_python.py`` re-exports these tests).
"""

import io
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hydrashield import HydraShieldClient, HydraShieldError  # noqa: E402

BASE = "https://hydrashield.earth"


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
# URL construction (exact query strings)
# ---------------------------------------------------------------------------

def test_hazards_url(http):
    calls, _ = http
    HydraShieldClient().hazards()
    assert _path(calls[0]) == "/api/v2/hazards"


def test_hazard_url(http):
    calls, _ = http
    HydraShieldClient().hazard("wildfire")
    assert _path(calls[0]) == "/api/v2/hazards/wildfire"


def test_analyze_url(http):
    calls, _ = http
    HydraShieldClient().analyze("wildfire", 37.6, -6.5)
    assert _path(calls[0]) == "/api/v2/analyze?hazard=wildfire&lat=37.6&lon=-6.5"


def test_events_url_with_year(http):
    calls, _ = http
    HydraShieldClient().events("wildfire", 37.6, -6.5, radius_km=50, year=2024)
    assert _path(calls[0]) == (
        "/api/v2/events?hazard=wildfire&lat=37.6&lon=-6.5"
        "&radius_km=50&year=2024")


def test_events_url_without_year(http):
    calls, _ = http
    HydraShieldClient().events("flood", 49.75, 6.64)
    assert _path(calls[0]) == (
        "/api/v2/events?hazard=flood&lat=49.75&lon=6.64&radius_km=50")


def test_event_url(http):
    calls, _ = http
    HydraShieldClient().event("wf-2024-00042")
    assert _path(calls[0]) == "/api/v2/events/wf-2024-00042"


def test_economy_url(http):
    calls, _ = http
    HydraShieldClient().economy(49.6, 6.1)
    assert _path(calls[0]) == "/api/v2/economy?lat=49.6&lon=6.1&radius_km=5"


def test_solutions_url_with_hazards(http):
    calls, _ = http
    HydraShieldClient().solutions(49.6, 6.1, hazards=["wildfire", "drought"])
    assert _path(calls[0]) == (
        "/api/v2/solutions?lat=49.6&lon=6.1&hazards=wildfire%2Cdrought")


def test_solutions_url_without_hazards(http):
    calls, _ = http
    HydraShieldClient().solutions(49.6, 6.1)
    assert _path(calls[0]) == "/api/v2/solutions?lat=49.6&lon=6.1"


def test_sources_url(http):
    calls, _ = http
    HydraShieldClient().sources()
    assert _path(calls[0]) == "/api/v2/sources"


def test_health_url(http):
    calls, _ = http
    HydraShieldClient().health()
    assert _path(calls[0]) == "/api/health"


def test_risk_grid_url(http):
    calls, _ = http
    HydraShieldClient().risk_grid(49.9, 5.9, 50.1, 6.1)
    assert _path(calls[0]) == (
        "/api/risk-grid?south=49.9&west=5.9&north=50.1&east=6.1&n=6")


def test_risk_snapshot_url(http):
    calls, _ = http
    HydraShieldClient().risk_snapshot()
    assert _path(calls[0]) == "/api/risk-snapshot"


def test_history_url(http):
    calls, _ = http
    HydraShieldClient().history(37.6, -6.5)
    assert _path(calls[0]) == "/api/history?lat=37.6&lon=-6.5&days=90"


def test_report_url_string(http):
    client = HydraShieldClient()
    assert client.report_url(37.6, -6.5) == (
        BASE + "/api/report?lat=37.6&lon=-6.5&type=decision&history=1")
    assert client.report_url(37.6, -6.5, report_type="simple", history=False) == (
        BASE + "/api/report?lat=37.6&lon=-6.5&type=simple")


def test_population_exposure_url(http):
    calls, _ = http
    HydraShieldClient().population_exposure(37.6, -6.5)
    assert _path(calls[0]) == (
        "/api/population-exposure?lat=37.6&lon=-6.5&radius_km=3")


def test_smoke_scenario_url(http):
    calls, _ = http
    HydraShieldClient().smoke_scenario(37.6, -6.5)
    assert _path(calls[0]) == "/api/smoke-scenario?lat=37.6&lon=-6.5&hours=24"


def test_custom_base_url_trailing_slash(http):
    calls, _ = http
    HydraShieldClient(base_url="http://localhost:8051/").health()
    assert calls[0]["url"] == "http://localhost:8051/api/health"


# ---------------------------------------------------------------------------
# Error semantics
# ---------------------------------------------------------------------------

def test_error_body_raises_on_4xx(http):
    _, queue = http
    queue.append((404, {"error": "Unknown hazard 'xyz'. See /api/v2/hazards.",
                        "status": 404}))
    with pytest.raises(HydraShieldError) as excinfo:
        HydraShieldClient().analyze("xyz", 0, 0)
    assert excinfo.value.status == 404
    assert "Unknown hazard" in excinfo.value.message


def test_error_body_raises_on_5xx(http):
    _, queue = http
    queue.append((502, {"error": "Analysis failed: upstream", "status": 502}))
    with pytest.raises(HydraShieldError) as excinfo:
        HydraShieldClient().risk_snapshot()
    assert excinfo.value.status == 502


def test_error_body_raises_on_429(http):
    _, queue = http
    queue.append((429, {"error": "Rate limit exceeded", "status": 429}))
    with pytest.raises(HydraShieldError) as excinfo:
        HydraShieldClient().health()
    assert excinfo.value.status == 429


def test_unavailable_503_returned_as_data(http):
    """Honest unavailable states are data, never exceptions."""
    _, queue = http
    queue.append((503, {"hazard": "wildfire", "status": "unavailable",
                        "unavailable_reason": "upstream source unreachable"}))
    result = HydraShieldClient().analyze("wildfire", 37.6, -6.5)
    assert result["status"] == "unavailable"
    assert "unavailable_reason" in result


def test_snapshot_unavailable_503_returned_as_data(http):
    _, queue = http
    queue.append((503, {"status": "unavailable", "reason": "no snapshot"}))
    result = HydraShieldClient().risk_snapshot()
    assert result["status"] == "unavailable"


# ---------------------------------------------------------------------------
# Headers
# ---------------------------------------------------------------------------

def test_api_key_header_sent(http):
    calls, _ = http
    HydraShieldClient(api_key="hs_test_key").hazards()
    assert calls[0]["headers"].get("X-api-key") == "hs_test_key"


def test_no_api_key_header_by_default(http):
    calls, _ = http
    HydraShieldClient().hazards()
    assert "X-api-key" not in calls[0]["headers"]


def test_user_agent_header(http):
    calls, _ = http
    HydraShieldClient().hazards()
    ua = calls[0]["headers"].get("User-agent", "")
    assert ua.startswith("hydrashield-python-sdk/")


def test_timeout_passed_to_urlopen(http):
    calls, _ = http
    HydraShieldClient(timeout=7).hazards()
    assert calls[0]["timeout"] == 7
