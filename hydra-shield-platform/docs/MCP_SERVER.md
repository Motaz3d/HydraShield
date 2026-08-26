# Talaix MCP Server

The Talaix platform exposes a [Model Context Protocol](https://modelcontextprotocol.io/) (MCP) server so that MCP-compatible AI assistants can call the Talaix evidence engine as remote tools.

The server is intentionally lightweight: a single HTTP endpoint that speaks JSON-RPC 2.0 with a simple request-response transport. It adds no new dependencies — the protocol layer is implemented by hand in Flask.

## Endpoint

```
POST /api/mcp
Content-Type: application/json
```

The endpoint also accepts `GET /api/mcp` for discovery; it returns a small JSON document with the server name, version, transport note and tool list.

## Transport

- **Streamable-HTTP style request/response.** Each POST is one JSON-RPC request or batch; the response is the matching JSON-RPC response.
- **No SSE in this version.** Streaming updates, subscriptions and server-to-client notifications are not implemented yet.
- **Public read-only.** No authentication is required; the endpoint reuses the same per-IP rate limiter as the public REST API (30 requests/minute per client).

## Connecting an MCP client

Most MCP clients that support remote HTTP servers can be pointed at the URL below.

```json
{
  "mcpServers": {
    "talaix": {
      "url": "https://talaix.com/api/mcp"
    }
  }
}
```

The server implements the standard MCP lifecycle methods:

- `initialize` — handshake; returns `protocolVersion`, `capabilities` and `serverInfo`.
- `notifications/initialized` — client lifecycle notification; server returns `204 No Content`.
- `ping` — keep-alive; returns `{}`.
- `tools/list` — list the 9 available tools with JSON Schema input schemas.
- `tools/call` — invoke a tool by name with arguments.

## Example exchange

### Initialize

Request:

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "initialize",
  "params": {
    "protocolVersion": "2025-06-18",
    "capabilities": {},
    "clientInfo": {"name": "example-client", "version": "1.0.0"}
  }
}
```

Response:

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "protocolVersion": "2025-06-18",
    "capabilities": {"tools": {"listChanged": false}},
    "serverInfo": {
      "name": "talaix",
      "version": "1.0.0",
      "title": "Talaix Evidence Engine"
    }
  }
}
```

### tools/list

Request:

```json
{"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
```

Response (truncated):

```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "result": {
    "tools": [
      {
        "name": "talaix_hazards",
        "description": "List the hazard modules registered in the Talaix evidence engine...",
        "inputSchema": {"type": "object", "properties": {}}
      },
      {
        "name": "talaix_analyze",
        "description": "Run a per-hazard screening analysis for a location...",
        "inputSchema": {
          "type": "object",
          "required": ["hazard", "lat", "lon"],
          "properties": {
            "hazard": {"type": "string", "enum": ["wildfire", "flood", ...]},
            "lat": {"type": "number", "minimum": -90, "maximum": 90},
            "lon": {"type": "number", "minimum": -180, "maximum": 180},
            "name": {"type": "string"}
          }
        }
      }
    ]
  }
}
```

### tools/call — verify an asset

Request:

```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "method": "tools/call",
  "params": {
    "name": "talaix_verify_asset",
    "arguments": {"lat": 45.42, "lon": 12.33, "name": "Example site"}
  }
}
```

Response:

```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "result": {
    "content": [
      {
        "type": "text",
        "text": "{ \"verification_id\": \"…\", \"asset\": {...}, \"hazard_checks\": [...], ... }"
      }
    ],
    "isError": false
  }
}
```

The `text` field contains a JSON-stringified payload with an indent of 1, so clients can parse it to access structured fields.

## Tools

| Tool | Purpose | Honesty constraint |
|------|---------|-------------------|
| `talaix_hazards` | List registered hazard modules with availability, temporal coverage and sources. | A hazard appears only when backed by a real, documented data source. |
| `talaix_analyze` | Per-hazard screening analysis for a location. | Levels are screening indicators unless explicitly labelled validated; unavailable layers are reported with a reason. |
| `talaix_verify_asset` | Green Finance verification (EU Taxonomy DNSH vocabulary). | **Not** a Second Party Opinion, **not** an ESMA-registered external review, **not** investment advice. |
| `talaix_insurance_profile` | Per-peril levels + long-term event history. | **No loss quantification**: no AAL/PML, no ground-up loss estimate, no pricing signal. |
| `talaix_mapcheck` | Open-maps vs satellite cross-verification. | Verdicts are `consistent` / `discrepancy_detected` / `cannot_assess`; proprietary maps are not fetched; a discrepancy is a signal to verify, not proof of error. |
| `talaix_briefs` | List published evidence briefs / framework explainers. | Only published briefs are returned. |
| `talaix_brief` | One full brief with sources and citations. | Returns an error for unknown or unpublished briefs. |
| `talaix_sustainability_frameworks` | CSRD/ESRS, EU Taxonomy, SB 261/253, China CSDS reference + coverage map. | Explicitly declares what is **not** covered (GHG, governance, social standards, assurance). |
| `talaix_sources` | Data-source audit registry. | Every source is listed with status, limitations and the reason for rejection where applicable. |

## Error handling

JSON-RPC protocol errors use the standard codes:

| Code | Meaning |
|------|---------|
| `-32700` | Parse error |
| `-32600` | Invalid request |
| `-32601` | Method not found |
| `-32602` | Invalid params |
| `-32603` | Internal error (also used for rate-limit exceeded) |

Tool-level failures — unknown hazard, engine unavailable, missing brief, etc. — are returned as `tools/call` results with `"isError": true` and a JSON error payload inside the `text` field. They are **not** JSON-RPC protocol errors, because the tool call itself succeeded at the protocol layer.

## Honesty contract

All tool descriptions embed the platform's limitations so that an AI client reading the tool list learns the boundaries before invoking anything:

- Talaix sells **evidence, not accreditation**.
- Hazard levels are **screening indicators** unless explicitly labelled validated.
- **Loss quantification is never provided.**
- **Unavailable data is declared, never invented.**
- Green Finance verification is a physical-evidence layer, not an ESMA-registered external review.
- Map Check uses only open sources; proprietary maps are not fetched.

## Roadmap / out of scope

This first release deliberately keeps the transport simple. Planned follow-ups:

- **SSE streaming** for long-running engine calls and progressive results.
- **MCP resources** for individual evidence briefs and PDF reports.
- **stdio wrapper** in the Python SDK so the same engines can be exposed locally.

## Implementation notes

- File: `src/dashboard/mcp_api.py`
- Registered in: `src/dashboard/api.py`
- Engines are called **in-process**; there are no HTTP self-calls.
- Rate limiter: same `_rate_limiter` used by the REST API, key prefix `mcp:`.
