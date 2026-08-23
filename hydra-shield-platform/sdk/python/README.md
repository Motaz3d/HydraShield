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

## Error semantics

- Non-2xx responses with the stable error shape `{"error", "status"}` raise
  `TalaixError(status, message)`.
- Honest unavailability (`{"status": "unavailable", "unavailable_reason": …}`,
  also on HTTP 503) is returned as **data** — render it, don't catch it.

## Install / test

The package is self-contained — put `sdk/python/` on your `PYTHONPATH` or
`pip install sdk/python` (minimal `pyproject.toml` included).

```bash
python -m pytest sdk/python/tests/ -q     # offline tests (urllib monkeypatched)
```

Full API contract: `docs/API_V2.md`.
