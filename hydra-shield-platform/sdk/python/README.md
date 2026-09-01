# Talaix Python SDK

Stdlib-only Python client for the [Talaix](https://talaix.com)
public REST API. No dependencies; Python 3.9+.

```python
from hydrashield import TalaixClient, TalaixError

client = TalaixClient()                     # defaults to https://talaix.com
# client = TalaixClient(api_key="hs_…")     # X-API-Key header (read-only)

hazards = client.hazards()
analysis = client.analyze("wildfire", lat=37.6, lon=-6.5)
if analysis.get("status") == "unavailable":
    print(analysis["unavailable_reason"])        # honest state — data, not an exception
else:
    print(analysis["level"]["label"], analysis["level"]["basis"])

events = client.events("wildfire", 37.6, -6.5, radius_km=50, year=2024)
econ = client.economy(49.6, 6.1)
sols = client.solutions(49.6, 6.1, hazards=["wildfire", "drought"])

pdf = client.report_url(37.6, -6.5)              # URL string; the response is a PDF

try:
    client.analyze("not-a-hazard", 0, 0)
except TalaixError as exc:
    print(exc.status, exc.message)               # 404 Unknown hazard …
```

## Methods

| Method | Endpoint |
|---|---|
| `hazards()` | `GET /api/v2/hazards` |
| `hazard(id)` | `GET /api/v2/hazards/<id>` |
| `analyze(hazard, lat, lon)` | `GET /api/v2/analyze` |
| `events(hazard, lat, lon, radius_km=50, year=None)` | `GET /api/v2/events` |
| `event(id)` | `GET /api/v2/events/<id>` |
| `economy(lat, lon, radius_km=5)` | `GET /api/v2/economy` |
| `solutions(lat, lon, hazards=None)` | `GET /api/v2/solutions` |
| `sources()` | `GET /api/v2/sources` |
| `health()` | `GET /api/health` |
| `risk_grid(south, west, north, east, n=6)` | `GET /api/risk-grid` |
| `risk_snapshot()` | `GET /api/risk-snapshot` |
| `history(lat, lon, days=90)` | `GET /api/history` |
| `report_url(lat, lon, report_type="decision", history=True)` | URL string for `GET /api/report` (PDF) |
| `population_exposure(lat, lon, radius_km=3)` | `GET /api/population-exposure` |
| `smoke_scenario(lat, lon, hours=24)` | `GET /api/smoke-scenario` |

## TX Engine client (`TxClient`)

The same package ships a client for the TX Engine API (`/api/tx/*` — the
uniform TxResult envelope + the standard Job Object for deep analyses;
see `docs/TX_ENGINE.md`):

```python
from hydrashield import TxClient

tx = TxClient()                                   # https://talaix.com
quick = tx.analyze(49.96, 6.03, hazards=["wildfire"], depth="quick")

job = tx.run(49.96, 6.03, depth="deep")           # POST /api/tx/run
result = tx.wait(job["job_id"], on_poll=print)    # poll → TxResult envelope
print(result["analysis_id"], result["status"])
```

| Method | Endpoint |
|---|---|
| `health()` / `version()` / `hazards()` / `sources()` / `registry()` / `products()` | `GET /api/tx/<…>` |
| `analyze(lat, lon, hazards=None, depth="standard", name=None, analyses=None)` | `GET /api/tx/analyze` |
| `run(lat, lon, hazards=None, depth="standard", name=None, analyses=None)` | `POST /api/tx/run` |
| `job(job_id)` | `GET /api/tx/jobs/<id>` |
| `result(job_id)` | `GET /api/tx/jobs/<id>/result` |
| `wait(job_or_id, timeout=600, interval=2, on_poll=None)` | poll → result |

`analyses` requests registered product engines (TX-2+; `insurance`,
`verification`, `sustainability`) next to hazard modules — product results
land in the same `results[]` list stamped `tx_level=2`.

A job that is not finished yet makes `result()` raise `TalaixError` with
HTTP 409; `wait()` raises with the job's real error on failure and HTTP
408 on timeout — never a fabricated result.

## Error semantics

- Non-2xx responses with the stable error shape `{"error", "status"}` raise
  `TalaixError(status, message)`.
- Honest unavailability (`{"status": "unavailable", "unavailable_reason": …}`,
  also on HTTP 503) is returned as **data** — render it, don't catch it.

## CLI

The package also installs a `talaix` command for read-only access to the
public GET endpoints. It is **read-only**: portfolio, claim, case and
report-builder endpoints that require a registered session are not exposed.

```bash
pip install sdk/python          # or `pip install .` inside sdk/python/

# Global flags
export TALAIX_BASE_URL=https://talaix.com   # optional
export TALAIX_API_KEY=hs_…                  # optional metering key

# Service status
talaix health

# List hazards
talaix hazards

# Analyze a hazard at a point
talaix analyze --hazard wildfire --lat 37.6 --lon -6.5

# Physical asset verification
talaix verify --lat 49.75 --lon 6.64 --name "Clervaux"
talaix verify --lat 49.75 --lon 6.64 --pdf report.pdf

# Insurance risk profile
talaix insurance --lat 37.6 --lon -6.5 --radius-km 25

# Map-vs-satellite cross-check
talaix mapcheck --lat 46.0542 --lon 14.4707 --radius-m 300

# Knowledge briefs
talaix briefs
talaix briefs --kind wildfire
talaix briefs br-2024-001

# Sustainability frameworks
talaix frameworks

# Data-source audit registry
talaix sources

# Raw JSON output
talaix --json analyze --hazard wildfire --lat 37.6 --lon -6.5
```

### Exit codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 2 | API error (`TalaixError`) — printed as `error: HTTP <status>: <message>` |
| 3 | Network error / timeout — printed as `error: could not reach <base-url> (<reason>)` |

With `--json`, the API payload (including unavailable states and error bodies)
is printed to stdout; the exit code still reflects the outcome.

## Install / test

The package is self-contained — put `sdk/python/` on your `PYTHONPATH` or
`pip install sdk/python` (minimal `pyproject.toml` included).

```bash
python -m pytest sdk/python/tests/ -q     # offline tests (urllib monkeypatched)
```

Full API contract: `docs/API_V2.md`.
