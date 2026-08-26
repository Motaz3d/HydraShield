"""
Talaix MCP (Model Context Protocol) server endpoint.

A single HTTP endpoint ``POST /api/mcp`` speaks JSON-RPC 2.0 with a simple
request-response (Streamable-HTTP-style) transport. No SSE in this version.

The endpoint exposes the Talaix evidence engines as MCP tools. All engine
calls run in-process; there are no HTTP self-calls. The endpoint is public
read-only and reuses the existing per-client rate limiter.

Honesty contract: every tool description embeds the platform's limitations
so that AI clients reading the description learn the boundaries before they
call. Engine failures are returned as ``isError: true`` tool results, never
as bare tracebacks.
"""

from __future__ import annotations

import json
import os
from typing import Any, Callable, Dict, List, Optional, Tuple

from flask import Blueprint, Response, request

mcp = Blueprint("mcp", __name__, url_prefix="/api")

SERVER_INFO = {
    "name": "talaix",
    "version": "1.0.0",
    "title": "Talaix Evidence Engine",
}

DEFAULT_PROTOCOL_VERSION = "2025-06-18"


# ---------------------------------------------------------------------------
# Lazy imports (avoid circulars with dashboard.api)
# ---------------------------------------------------------------------------


def _client_key() -> str:
    from .api import _client_key as ck  # type: ignore[attr-defined]

    return ck()


def _rate_limiter_allow(key: str, max_requests: int, window: float) -> bool:
    from .api import _rate_limiter  # type: ignore[attr-defined]

    return _rate_limiter.allow(key, max_requests, window)


# ---------------------------------------------------------------------------
# JSON-RPC helpers
# ---------------------------------------------------------------------------


class JsonRpcError(Exception):
    def __init__(self, code: int, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def _rpc_response(rpc_id: Any, result: Any) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": rpc_id, "result": result}


def _rpc_error(rpc_id: Any, code: int, message: str) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": code, "message": message}}


def _parse_request(body: bytes) -> Any:
    if not body:
        raise JsonRpcError(-32700, "Parse error: empty request body")
    try:
        data = json.loads(body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise JsonRpcError(-32700, f"Parse error: {exc}") from exc
    return data


def _validate_single_request(data: Any) -> Tuple[Any, str, Any]:
    if not isinstance(data, dict):
        raise JsonRpcError(-32600, "Invalid Request: message must be an object")
    if data.get("jsonrpc") != "2.0":
        raise JsonRpcError(-32600, "Invalid Request: jsonrpc must be '2.0'")
    method = data.get("method")
    if not isinstance(method, str) or not method:
        raise JsonRpcError(-32600, "Invalid Request: method must be a non-empty string")
    params = data.get("params")
    if params is not None and not isinstance(params, (dict, list)):
        raise JsonRpcError(-32600, "Invalid Request: params must be an object or array")
    rpc_id = data.get("id")
    return rpc_id, method, params if params is not None else {}


# ---------------------------------------------------------------------------
# Argument validation helpers
# ---------------------------------------------------------------------------


def _require_latlon(args: Dict[str, Any]) -> Tuple[float, float]:
    lat_raw = args.get("lat")
    lon_raw = args.get("lon")
    try:
        lat = float(lat_raw)  # type: ignore[arg-type]
        lon = float(lon_raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise JsonRpcError(-32602, "lat and lon must be numbers")
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        raise JsonRpcError(-32602, "lat/lon out of range")
    return lat, lon


def _optional_string(args: Dict[str, Any], key: str) -> Optional[str]:
    value = args.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise JsonRpcError(-32602, f"{key} must be a string")
    value = value.strip()
    return value or None


def _optional_radius_km(args: Dict[str, Any]) -> float:
    value = args.get("radius_km", 50.0)
    try:
        radius = float(value)
    except (TypeError, ValueError):
        raise JsonRpcError(-32602, "radius_km must be a number")
    if not (1.0 <= radius <= 500.0):
        raise JsonRpcError(-32602, "radius_km must be between 1 and 500")
    return radius


def _optional_radius_m(args: Dict[str, Any]) -> int:
    value = args.get("radius_m", 300)
    try:
        radius = int(value)
    except (TypeError, ValueError):
        raise JsonRpcError(-32602, "radius_m must be an integer")
    if not (50 <= radius <= 2000):
        raise JsonRpcError(-32602, "radius_m must be between 50 and 2000")
    return radius


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------


def _tool_result(payload: Any, is_error: bool = False) -> Dict[str, Any]:
    return {
        "content": [
            {"type": "text", "text": json.dumps(payload, ensure_ascii=False, indent=1)}
        ],
        "isError": is_error,
    }


def _handle_hazards(_args: Dict[str, Any]) -> Dict[str, Any]:
    from ..climate import registry

    return _tool_result({"hazards": registry.descriptors()})


def _handle_analyze(args: Dict[str, Any]) -> Dict[str, Any]:
    from ..climate import registry

    hazard_id = args.get("hazard")
    if not isinstance(hazard_id, str) or not hazard_id:
        raise JsonRpcError(-32602, "hazard must be a non-empty string")
    hazard_id = hazard_id.strip().lower()
    valid_ids = registry.ids()
    if hazard_id not in valid_ids:
        return _tool_result(
            {
                "error": f"Unknown hazard '{hazard_id}'.",
                "valid_hazards": valid_ids,
            },
            is_error=True,
        )
    module = registry.get(hazard_id)
    lat, lon = _require_latlon(args)
    name = _optional_string(args, "name")

    available, reason = module.availability()
    if not available:
        return _tool_result(
            {
                "hazard": hazard_id,
                "status": "unavailable",
                "unavailable_reason": reason,
            },
            is_error=True,
        )

    result = module.analyze(lat, lon, name=name)
    return _tool_result(result.to_dict(include_raw=False))


def _handle_verify_asset(args: Dict[str, Any]) -> Dict[str, Any]:
    from ..climate.verification import verify_asset

    lat, lon = _require_latlon(args)
    name = _optional_string(args, "name")
    return _tool_result(verify_asset(lat, lon, name=name))


def _handle_insurance_profile(args: Dict[str, Any]) -> Dict[str, Any]:
    from ..climate.insurance import build_risk_profile

    lat, lon = _require_latlon(args)
    name = _optional_string(args, "name")
    radius_km = _optional_radius_km(args)
    return _tool_result(build_risk_profile(lat, lon, name=name, radius_km=radius_km))


def _handle_mapcheck(args: Dict[str, Any]) -> Dict[str, Any]:
    from ..climate.mapcheck import check_map_vs_satellite

    lat, lon = _require_latlon(args)
    radius_m = _optional_radius_m(args)
    try:
        result = check_map_vs_satellite(lat, lon, radius_m=radius_m)
    except ValueError as exc:
        return _tool_result({"error": str(exc)}, is_error=True)
    return _tool_result(result)


def _handle_briefs(args: Dict[str, Any]) -> Dict[str, Any]:
    from ..climate.briefs import load_briefs, list_briefs

    kind = _optional_string(args, "kind")
    if kind is not None and kind not in {"framework_explainer", "evidence_brief"}:
        raise JsonRpcError(-32602, "kind must be framework_explainer or evidence_brief")
    config = load_briefs()
    return _tool_result({"briefs": list_briefs(kind=kind, config=config), "note": config.get("note")})


def _handle_brief(args: Dict[str, Any]) -> Dict[str, Any]:
    from ..climate.briefs import get_brief

    brief_id = args.get("id")
    if not isinstance(brief_id, str) or not brief_id:
        raise JsonRpcError(-32602, "id must be a non-empty string")
    brief = get_brief(brief_id)
    if brief is None:
        return _tool_result({"error": f"Unknown brief '{brief_id}'"}, is_error=True)
    return _tool_result({"brief": brief})


def _handle_sustainability_frameworks(_args: Dict[str, Any]) -> Dict[str, Any]:
    from ..climate.sustainability import (
        DISCLAIMER,
        ESRS_COVERAGE,
        EVIDENCE_STANDARD,
        SUSTAINABILITY_FRAMEWORKS,
    )

    return _tool_result(
        {
            "frameworks": SUSTAINABILITY_FRAMEWORKS,
            "coverage_map": ESRS_COVERAGE,
            "evidence_standard": EVIDENCE_STANDARD,
            "disclaimer": DISCLAIMER,
        }
    )


def _handle_sources(_args: Dict[str, Any]) -> Dict[str, Any]:
    import json as _json

    registry_path = os.path.join(
        os.path.dirname(__file__), "..", "..", "config", "source_registry.json"
    )
    try:
        with open(registry_path, "r", encoding="utf-8") as fh:
            registry_doc = _json.load(fh)
    except (OSError, _json.JSONDecodeError) as exc:
        return _tool_result({"error": f"Source registry unavailable: {exc}"}, is_error=True)
    return _tool_result(registry_doc)


# ---------------------------------------------------------------------------
# Tool registry and schemas
# ---------------------------------------------------------------------------


def _base_point_schema(required_name: bool = False) -> Dict[str, Any]:
    required = ["lat", "lon"]
    if required_name:
        required.append("name")
    return {
        "type": "object",
        "required": required,
        "properties": {
            "lat": {
                "type": "number",
                "minimum": -90.0,
                "maximum": 90.0,
                "description": "Latitude in decimal degrees.",
            },
            "lon": {
                "type": "number",
                "minimum": -180.0,
                "maximum": 180.0,
                "description": "Longitude in decimal degrees.",
            },
            "name": {
                "type": "string",
                "description": "Optional human-readable asset or site name.",
            },
        },
    }


def _hazard_enum() -> List[str]:
    """Current hazard ids; registry is lazy, so read at schema-build time."""
    from ..climate import registry

    try:
        return registry.ids()
    except Exception:
        return []


_TOOL_SPECS: List[Dict[str, Any]] = [
    {
        "name": "talaix_hazards",
        "description": (
            "List the hazard modules registered in the Talaix evidence engine. "
            "Each entry includes id, name, analysis availability, events availability, "
            "temporal coverage and declared sources. A hazard appears only when backed "
            "by a real, documented data source."
        ),
        "inputSchema": {"type": "object", "properties": {}},
        "handler": _handle_hazards,
    },
    {
        "name": "talaix_analyze",
        "description": (
            "Run a per-hazard screening analysis for a location. Returns status, "
            "summary, level, evidence and provenance. Levels are screening indicators "
            "unless explicitly labelled validated. Unknown or unavailable hazards are "
            "reported honestly with a reason."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["hazard", "lat", "lon"],
            "properties": {
                "hazard": {
                    "type": "string",
                    "enum": _hazard_enum(),
                    "description": "Hazard id from talaix_hazards.",
                },
                "lat": {"type": "number", "minimum": -90.0, "maximum": 90.0},
                "lon": {"type": "number", "minimum": -180.0, "maximum": 180.0},
                "name": {"type": "string", "description": "Optional location name."},
            },
        },
        "handler": _handle_analyze,
    },
    {
        "name": "talaix_verify_asset",
        "description": (
            "Green Finance verification against the EU Taxonomy DNSH physical-risk "
            "vocabulary. Returns per-hazard claim status, confidence, declared gaps, "
            "framework context and a verification id. This is a physical-evidence "
            "screening layer — NOT a Second Party Opinion, NOT an ESMA-registered "
            "external review, and NOT investment advice."
        ),
        "inputSchema": _base_point_schema(),
        "handler": _handle_verify_asset,
    },
    {
        "name": "talaix_insurance_profile",
        "description": (
            "Insurance and environmental risk profile: current per-peril levels plus "
            "long-term event history for a location. Explicitly excludes loss "
            "quantification (no AAL/PML, no ground-up loss estimate, no pricing signal). "
            "Levels are screening indicators unless labelled validated."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["lat", "lon"],
            "properties": {
                "lat": {"type": "number", "minimum": -90.0, "maximum": 90.0},
                "lon": {"type": "number", "minimum": -180.0, "maximum": 180.0},
                "name": {"type": "string", "description": "Optional location name."},
                "radius_km": {
                    "type": "number",
                    "minimum": 1.0,
                    "maximum": 500.0,
                    "default": 50.0,
                    "description": "Radius in kilometres for historical-event lookup.",
                },
            },
        },
        "handler": _handle_insurance_profile,
    },
    {
        "name": "talaix_mapcheck",
        "description": (
            "Cross-verify open map data (OpenStreetMap green features) against open "
            "satellite observation (Sentinel-2 NDVI + ESA WorldCover). Returns "
            "consistent / discrepancy_detected / cannot_assess verdicts with possible "
            "causes. Proprietary maps (Google/Apple/Bing) are NOT fetched. A "
            "discrepancy is a signal to verify, not proof of a map error."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["lat", "lon"],
            "properties": {
                "lat": {"type": "number", "minimum": -90.0, "maximum": 90.0},
                "lon": {"type": "number", "minimum": -180.0, "maximum": 180.0},
                "radius_m": {
                    "type": "integer",
                    "minimum": 50,
                    "maximum": 2000,
                    "default": 300,
                    "description": "Search radius in metres around the point.",
                },
            },
        },
        "handler": _handle_mapcheck,
    },
    {
        "name": "talaix_briefs",
        "description": (
            "List published evidence briefs and framework explainers from the Talaix "
            "Knowledge Arm. Each entry contains id, kind, title, date, summary and "
            "source count."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "kind": {
                    "type": "string",
                    "enum": ["framework_explainer", "evidence_brief"],
                    "description": "Optional filter by brief kind.",
                },
            },
        },
        "handler": _handle_briefs,
    },
    {
        "name": "talaix_brief",
        "description": (
            "Retrieve one full published evidence brief by id, including its sources "
            "and citations. Returns an error if the brief does not exist or is not "
            "published."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["id"],
            "properties": {
                "id": {"type": "string", "description": "Brief identifier."},
            },
        },
        "handler": _handle_brief,
    },
    {
        "name": "talaix_sustainability_frameworks",
        "description": (
            "Return the sustainability reporting frameworks reference: CSRD/ESRS, "
            "EU Taxonomy DNSH, California SB 261/253, China CSDS, the ESRS coverage "
            "map, and the Talaix Evidence Standard criteria. Includes explicit "
            "declarations of what is NOT covered (GHG, governance, social standards, "
            "assurance)."
        ),
        "inputSchema": {"type": "object", "properties": {}},
        "handler": _handle_sustainability_frameworks,
    },
    {
        "name": "talaix_sources",
        "description": (
            "Return the data-source audit registry: every source evaluated by Talaix "
            "with status (integrated / candidate / rejected), provider, purpose, "
            "coverage, resolution, update frequency, access method, license and "
            "declared limitations."
        ),
        "inputSchema": {"type": "object", "properties": {}},
        "handler": _handle_sources,
    },
]

_TOOL_MAP: Dict[str, Dict[str, Any]] = {t["name"]: t for t in _TOOL_SPECS}


def _refresh_hazard_enum() -> None:
    """Update the analyze schema's hazard enum before serving tools/list."""
    for tool in _TOOL_SPECS:
        if tool["name"] == "talaix_analyze":
            tool["inputSchema"]["properties"]["hazard"]["enum"] = _hazard_enum()
            break


# ---------------------------------------------------------------------------
# Method dispatch
# ---------------------------------------------------------------------------


def _handle_initialize(params: Dict[str, Any]) -> Dict[str, Any]:
    client_version = params.get("protocolVersion") if isinstance(params, dict) else None
    return {
        "protocolVersion": client_version or DEFAULT_PROTOCOL_VERSION,
        "capabilities": {"tools": {"listChanged": False}},
        "serverInfo": SERVER_INFO,
    }


def _handle_ping(_params: Any) -> Dict[str, Any]:
    return {}


def _handle_tools_list(_params: Any) -> Dict[str, Any]:
    _refresh_hazard_enum()
    tools = [
        {"name": t["name"], "description": t["description"], "inputSchema": t["inputSchema"]}
        for t in _TOOL_SPECS
    ]
    return {"tools": tools}


def _handle_tools_call(params: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(params, dict):
        raise JsonRpcError(-32602, "tools/call params must be an object")
    name = params.get("name")
    if not isinstance(name, str) or not name:
        raise JsonRpcError(-32602, "tools/call requires params.name")
    arguments = params.get("arguments") or {}
    if not isinstance(arguments, dict):
        raise JsonRpcError(-32602, "tools/call arguments must be an object")

    tool = _TOOL_MAP.get(name)
    if tool is None:
        return _tool_result({"error": f"Unknown tool '{name}'"}, is_error=True)

    handler: Callable[[Dict[str, Any]], Dict[str, Any]] = tool["handler"]
    return handler(arguments)


_METHODS: Dict[str, Callable[[Any], Any]] = {
    "initialize": _handle_initialize,
    "ping": _handle_ping,
    "tools/list": _handle_tools_list,
    "tools/call": _handle_tools_call,
}


def _dispatch_method(rpc_id: Any, method: str, params: Any) -> Optional[Dict[str, Any]]:
    """Dispatch a single JSON-RPC method. Returns response dict or None for notifications."""
    if rpc_id is None and method == "notifications/initialized":
        return None  # notification: no response body

    handler = _METHODS.get(method)
    if handler is None:
        raise JsonRpcError(-32601, f"Method not found: {method}")

    result = handler(params)
    if rpc_id is None:
        return None  # notification
    return _rpc_response(rpc_id, result)


def _process_single(data: Any) -> Optional[Dict[str, Any]]:
    rpc_id, method, params = _validate_single_request(data)
    return _dispatch_method(rpc_id, method, params)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@mcp.route("/mcp", methods=["GET"])
def mcp_discovery():
    """GET /api/mcp — small discovery JSON for humans and diagnostics."""
    _refresh_hazard_enum()
    return {
        "name": SERVER_INFO["name"],
        "version": SERVER_INFO["version"],
        "title": SERVER_INFO["title"],
        "transport": "POST JSON-RPC 2.0; no SSE in this version",
        "endpoint": "/api/mcp",
        "tools_count": len(_TOOL_SPECS),
        "tools": [t["name"] for t in _TOOL_SPECS],
    }


@mcp.route("/mcp", methods=["POST"])
def mcp_endpoint():
    """POST /api/mcp — JSON-RPC 2.0 MCP endpoint."""
    if not _rate_limiter_allow(f"mcp:{_client_key()}", 30, 60.0):
        return _rpc_error(None, -32603, "Rate limit exceeded (30 requests/minute)")

    try:
        data = _parse_request(request.get_data(cache=False))
    except JsonRpcError as exc:
        return Response(
            json.dumps(_rpc_error(None, exc.code, exc.message)),
            status=200,
            mimetype="application/json",
        )

    if isinstance(data, list):
        if not data:
            return Response(
                json.dumps(_rpc_error(None, -32600, "Invalid Request: empty batch")),
                status=200,
                mimetype="application/json",
            )
        responses: List[Dict[str, Any]] = []
        for item in data:
            try:
                resp = _process_single(item)
                if resp is not None:
                    responses.append(resp)
            except JsonRpcError as exc:
                # Batch items that are themselves invalid still need an id when possible.
                item_id = item.get("id") if isinstance(item, dict) else None
                responses.append(_rpc_error(item_id, exc.code, exc.message))
            except Exception as exc:  # noqa: BLE001 — honest internal-error envelope
                item_id = item.get("id") if isinstance(item, dict) else None
                responses.append(_rpc_error(item_id, -32603, f"Internal error: {exc}"))
        return Response(
            json.dumps(responses, ensure_ascii=False),
            status=200,
            mimetype="application/json",
        )

    try:
        response = _process_single(data)
    except JsonRpcError as exc:
        return Response(
            json.dumps(_rpc_error(data.get("id") if isinstance(data, dict) else None, exc.code, exc.message)),
            status=200,
            mimetype="application/json",
        )
    except Exception as exc:  # noqa: BLE001
        return Response(
            json.dumps(
                _rpc_error(
                    data.get("id") if isinstance(data, dict) else None,
                    -32603,
                    f"Internal error: {exc}",
                )
            ),
            status=200,
            mimetype="application/json",
        )

    if response is None:
        return "", 204

    return Response(
        json.dumps(response, ensure_ascii=False),
        status=200,
        mimetype="application/json",
    )
