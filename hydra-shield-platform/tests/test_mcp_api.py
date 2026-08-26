"""Tests for the Talaix MCP server endpoint.

Fully offline: all engines and registries are monkeypatched so no network
requests are made.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict

import pytest

os.environ["HYDRASHIELD_CACHE_DB"] = "/tmp/hydrashield_test_mcp_cache.sqlite3"
if os.path.exists(os.environ["HYDRASHIELD_CACHE_DB"]):
    os.remove(os.environ["HYDRASHIELD_CACHE_DB"])

from src.climate import registry  # noqa: E402
from src.dashboard.api import create_app  # noqa: E402


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _fresh_registry(monkeypatch):
    """Drop the cached registry before/after each test."""
    registry.reset_for_tests()
    yield
    registry.reset_for_tests()


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """Isolated DB per test; clear rate limiter."""
    db_path = tmp_path / "mcp.sqlite3"
    monkeypatch.setenv("HYDRASHIELD_CACHE_DB", str(db_path))
    import src.dashboard.cache as cache_mod
    import src.dashboard.api as api_module

    monkeypatch.setattr(cache_mod, "_default_cache", None)
    api_module._rate_limiter._hits.clear()
    return {"db": db_path}


@pytest.fixture()
def client(env):
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture(autouse=True)
def _stub_engines(monkeypatch):
    """Stub every engine the MCP server calls in-process."""

    def fake_descriptors():
        return [
            {
                "id": "wildfire",
                "name": "Wildfire",
                "analysis": {"available": True, "reason": None},
                "events": {"available": True, "reason": None},
            },
            {
                "id": "flood",
                "name": "Flood",
                "analysis": {"available": True, "reason": None},
                "events": {"available": True, "reason": None},
            },
        ]

    def fake_ids():
        return ["wildfire", "flood"]

    class _FakeWildfireModule:
        id = "wildfire"
        name = "Wildfire"

        def availability(self):
            return True, None

        def analyze(self, lat, lon, name=None):
            return _hazard_analysis("wildfire", lat, lon, name)

    class _FakeFloodModule:
        id = "flood"
        name = "Flood"

        def availability(self):
            return True, None

        def analyze(self, lat, lon, name=None):
            return _hazard_analysis("flood", lat, lon, name)

    def fake_get(hazard_id: str):
        if hazard_id == "wildfire":
            return _FakeWildfireModule()
        if hazard_id == "flood":
            return _FakeFloodModule()
        return None

    monkeypatch.setattr(registry, "descriptors", fake_descriptors)
    monkeypatch.setattr(registry, "ids", fake_ids)
    monkeypatch.setattr(registry, "get", fake_get)

    # Underlying engines (MCP handlers call these in-process).
    monkeypatch.setattr(
        "src.climate.verification.verify_asset",
        lambda lat, lon, name=None: {"verification_id": "v123", "asset": {"lat": lat, "lon": lon, "name": name}},
    )
    monkeypatch.setattr(
        "src.climate.insurance.build_risk_profile",
        lambda lat, lon, name=None, radius_km=50.0: {
            "profile_id": "p123",
            "asset": {"lat": lat, "lon": lon, "name": name},
            "perils": [],
            "loss_quantification": "not_quantified",
        },
    )
    monkeypatch.setattr(
        "src.climate.mapcheck.check_map_vs_satellite",
        lambda lat, lon, radius_m=300: {
            "check_id": "m123",
            "location": {"lat": lat, "lon": lon, "radius_m": radius_m},
            "status": "ok",
        },
    )

    fake_briefs_config = {
        "briefs": [
            {
                "id": "b1",
                "status": "published",
                "kind": "evidence_brief",
                "title": "Brief",
                "date": "2026-08-01",
                "summary": "summary",
                "sources": [],
            }
        ],
        "note": "note",
    }
    monkeypatch.setattr("src.climate.briefs.load_briefs", lambda path=None: fake_briefs_config)

    monkeypatch.setattr(
        "src.climate.sustainability.SUSTAINABILITY_FRAMEWORKS",
        [{"id": "csrd", "name": "CSRD"}],
    )
    monkeypatch.setattr(
        "src.climate.sustainability.ESRS_COVERAGE",
        [{"area": "E1", "coverage": "covered_by_evidence"}],
    )
    monkeypatch.setattr(
        "src.climate.sustainability.EVIDENCE_STANDARD",
        {"name": "Test Standard"},
    )


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


def _rpc(method: str, params: Any = None, rpc_id: Any = 1):
    payload: Dict[str, Any] = {"jsonrpc": "2.0", "id": rpc_id, "method": method}
    if params is not None:
        payload["params"] = params
    return payload


def _post(client, payload):
    return client.post("/api/mcp", json=payload)


def _asset(args: Dict[str, Any]) -> Dict[str, Any]:
    return {"lat": args["lat"], "lon": args["lon"], "name": args.get("name")}


def _hazard_analysis(hazard: str, lat: float, lon: float, name: Any):
    from src.climate.hazards.base import HazardAnalysis, HazardLevel

    return HazardAnalysis(
        hazard=hazard,
        location={"lat": lat, "lon": lon, "name": name},
        status="ok",
        summary=f"{hazard} screening ok",
        level=HazardLevel(
            label="Moderate",
            score=0.5,
            score_max=1.0,
            basis="modelled screening indicator",
            validated=False,
        ),
        evidence=[{"source": "Fake", "dataset": "Fake"}],
    )


def _tool_result(payload: Any, is_error: bool = False) -> Dict[str, Any]:
    return {
        "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False, indent=1)}],
        "isError": is_error,
    }


def _text_payload(result: Dict[str, Any]) -> Any:
    content = result["content"]
    assert len(content) == 1
    return json.loads(content[0]["text"])


# -----------------------------------------------------------------------------
# Lifecycle
# -----------------------------------------------------------------------------


def test_initialize_returns_server_info_and_echoes_protocol_version(client):
    resp = _post(client, _rpc("initialize", {"protocolVersion": "2025-06-18"}))
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["jsonrpc"] == "2.0"
    assert body["id"] == 1
    result = body["result"]
    assert result["protocolVersion"] == "2025-06-18"
    assert result["capabilities"] == {"tools": {"listChanged": False}}
    assert result["serverInfo"]["name"] == "talaix"
    assert result["serverInfo"]["version"] == "1.0.0"
    assert result["serverInfo"]["title"] == "Talaix Evidence Engine"


def test_initialize_uses_default_protocol_version_when_not_supplied(client):
    resp = _post(client, _rpc("initialize", {}))
    assert resp.get_json()["result"]["protocolVersion"] == "2025-06-18"


def test_notifications_initialized_returns_204(client):
    resp = _post(client, {"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert resp.status_code == 204
    assert resp.get_data(as_text=True) == ""


def test_ping_returns_empty_object(client):
    resp = _post(client, _rpc("ping"))
    assert resp.status_code == 200
    assert resp.get_json()["result"] == {}


# -----------------------------------------------------------------------------
# tools/list
# -----------------------------------------------------------------------------


def test_tools_list_has_nine_tools_with_names_and_schemas(client):
    resp = _post(client, _rpc("tools/list"))
    assert resp.status_code == 200
    tools = resp.get_json()["result"]["tools"]
    assert len(tools) == 9
    names = {t["name"] for t in tools}
    expected = {
        "talaix_hazards",
        "talaix_analyze",
        "talaix_verify_asset",
        "talaix_insurance_profile",
        "talaix_mapcheck",
        "talaix_briefs",
        "talaix_brief",
        "talaix_sustainability_frameworks",
        "talaix_sources",
    }
    assert names == expected
    for t in tools:
        assert "description" in t
        assert isinstance(t["description"], str)
        assert "inputSchema" in t
        assert t["inputSchema"]["type"] == "object"


# -----------------------------------------------------------------------------
# tools/call — each tool
# -----------------------------------------------------------------------------


def test_call_talaix_hazards(client):
    resp = _post(client, _rpc("tools/call", {"name": "talaix_hazards", "arguments": {}}))
    assert resp.status_code == 200
    result = resp.get_json()["result"]
    assert result["isError"] is False
    payload = _text_payload(result)
    assert "hazards" in payload
    assert len(payload["hazards"]) == 2


def test_call_talaix_analyze(client):
    resp = _post(
        client,
        _rpc("tools/call", {"name": "talaix_analyze", "arguments": {"hazard": "wildfire", "lat": 45.0, "lon": 12.0}}),
    )
    assert resp.status_code == 200
    result = resp.get_json()["result"]
    assert result["isError"] is False
    payload = _text_payload(result)
    assert payload["hazard"] == "wildfire"
    assert payload["status"] == "ok"


def test_call_talaix_verify_asset(client):
    resp = _post(
        client,
        _rpc("tools/call", {"name": "talaix_verify_asset", "arguments": {"lat": 45.0, "lon": 12.0, "name": "Site"}}),
    )
    result = resp.get_json()["result"]
    assert result["isError"] is False
    payload = _text_payload(result)
    assert payload["verification_id"] == "v123"


def test_call_talaix_insurance_profile(client):
    resp = _post(
        client,
        _rpc(
            "tools/call",
            {"name": "talaix_insurance_profile", "arguments": {"lat": 45.0, "lon": 12.0, "radius_km": 25.0}},
        ),
    )
    result = resp.get_json()["result"]
    assert result["isError"] is False
    payload = _text_payload(result)
    assert payload["profile_id"] == "p123"
    assert payload["loss_quantification"] == "not_quantified"


def test_call_talaix_mapcheck(client):
    resp = _post(
        client,
        _rpc(
            "tools/call",
            {"name": "talaix_mapcheck", "arguments": {"lat": 45.0, "lon": 12.0, "radius_m": 100}},
        ),
    )
    result = resp.get_json()["result"]
    assert result["isError"] is False
    payload = _text_payload(result)
    assert payload["check_id"] == "m123"
    assert payload["location"]["radius_m"] == 100


def test_call_talaix_briefs(client):
    resp = _post(client, _rpc("tools/call", {"name": "talaix_briefs", "arguments": {"kind": "evidence_brief"}}))
    result = resp.get_json()["result"]
    assert result["isError"] is False
    payload = _text_payload(result)
    assert payload["briefs"][0]["id"] == "b1"


def test_call_talaix_brief(client):
    resp = _post(client, _rpc("tools/call", {"name": "talaix_brief", "arguments": {"id": "b1"}}))
    result = resp.get_json()["result"]
    assert result["isError"] is False
    payload = _text_payload(result)
    assert payload["brief"]["id"] == "b1"


def test_call_talaix_sustainability_frameworks(client):
    resp = _post(client, _rpc("tools/call", {"name": "talaix_sustainability_frameworks", "arguments": {}}))
    result = resp.get_json()["result"]
    assert result["isError"] is False
    payload = _text_payload(result)
    assert "frameworks" in payload


def test_call_talaix_sources(client):
    resp = _post(client, _rpc("tools/call", {"name": "talaix_sources", "arguments": {}}))
    result = resp.get_json()["result"]
    assert result["isError"] is False
    payload = _text_payload(result)
    assert "sources" in payload


# -----------------------------------------------------------------------------
# Error handling
# -----------------------------------------------------------------------------


def test_unknown_tool_returns_is_error_true(client):
    resp = _post(client, _rpc("tools/call", {"name": "talaix_no_such_tool", "arguments": {}}))
    assert resp.status_code == 200
    result = resp.get_json()["result"]
    assert result["isError"] is True
    payload = _text_payload(result)
    assert "Unknown tool" in payload["error"]


def test_unknown_method_returns_minus_32601(client):
    resp = _post(client, _rpc("tools/no_such_method"))
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["error"]["code"] == -32601
    assert "Method not found" in body["error"]["message"]


def test_invalid_params_lat_out_of_range_returns_minus_32602(client):
    resp = _post(
        client,
        _rpc("tools/call", {"name": "talaix_analyze", "arguments": {"hazard": "wildfire", "lat": 999.0, "lon": 12.0}}),
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["error"]["code"] == -32602
    assert "lat/lon out of range" in body["error"]["message"]


def test_missing_required_argument_returns_minus_32602(client):
    resp = _post(client, _rpc("tools/call", {"name": "talaix_brief", "arguments": {}}))
    body = resp.get_json()
    assert body["error"]["code"] == -32602


# -----------------------------------------------------------------------------
# Batch
# -----------------------------------------------------------------------------


def test_batch_of_two_calls_returns_array_of_two_results(client):
    batch = [
        _rpc("tools/call", {"name": "talaix_ping_wrapped", "arguments": {}}, rpc_id=1),
        _rpc("ping", rpc_id=2),
    ]
    batch[0]["params"]["name"] = "talaix_hazards"
    resp = _post(client, batch)
    assert resp.status_code == 200
    body = resp.get_json()
    assert isinstance(body, list)
    assert len(body) == 2
    assert body[0]["id"] == 1
    assert body[0]["result"]["isError"] is False
    assert body[1]["id"] == 2
    assert body[1]["result"] == {}


# -----------------------------------------------------------------------------
# Discovery GET
# -----------------------------------------------------------------------------


def test_get_discovery_returns_metadata(client):
    resp = client.get("/api/mcp")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["name"] == "talaix"
    assert body["version"] == "1.0.0"
    assert "POST JSON-RPC 2.0" in body["transport"]
    assert "no sse" in body["transport"].lower()
    assert body["endpoint"] == "/api/mcp"
    assert body["tools_count"] == 9
    assert "talaix_analyze" in body["tools"]
