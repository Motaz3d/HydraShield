# Sector Exposure Screening

Physical-risk screening for investors, property owners and governments.

## Purpose & audience

Sector Exposure Screening answers: *given a location, which sectors are most
sensitive to the physical hazards observed there, and what is the location's
physical trajectory over time?* It is designed for:

- investors and asset managers screening acquisitions or portfolio locations,
- property owners and developers evaluating site-level exposure,
- governments and planners assessing territory-level sector relevance.

The output is **screening evidence only**. It is not investment advice, not a
valuation, and not a prediction of losses. Financial metrics are intentionally
**not quantified**.

## Sector knowledge base

The curated sector profiles live in `config/sector_profiles.json`. Each sector
lists the physical hazards it is sensitive to, with a weight (`high`, `medium`,
`low`) and a one-sentence factual rationale.

| Sector | High-weight hazards | Typical focus |
|---|---|---|
| Agriculture | drought, heat | water stress, heat-yield impacts |
| Real estate — residential | flood | flood zones, heat island, WUI |
| Real estate — commercial | flood | flood + coastal + storm exposure |
| Tourism & hospitality | wildfire, coastal | fire smoke, beach erosion, water supply |
| Energy — solar | heat | panel efficiency, soiling, hail |
| Energy — wind | wind | extreme gusts, icing, grid access |
| Logistics & ports | coastal, flood | surge, hinterland flooding, downtime |
| Mining | flood, drought | pit flooding, tailings, water security |
| Forestry & timber | wildfire | fire, blowdown, drought stress |

Only hazards registered in `src/climate/verification.py` (`flood`, `coastal`,
`wildfire`, `heat`, `drought`, `wind`) are used.

## Scoring heuristic

The screening-exposure score is a **declared heuristic**, not a validated risk
model.

- Weight score: `high = 2`, `medium = 1`, `low = 1`.
- Level score from the hazard check:
  - Extreme = 4
  - Severe = 3
  - Moderate = 2
  - Mild / Low = 1
  - None / unknown = 0
- Sector score = Σ(weight × level) over the sector's sensitive hazards.
- Band (fixed thresholds):
  - `lower`    : score 0–4
  - `moderate` : score 5–12
  - `elevated` : score 13–24
  - `high`     : score > 24

Each per-hazard exposure carries the original `claim_status` and `confidence`
from the verification engine, so users can see whether a level is modelled,
observed or unknown.

## Trajectory components

The trajectory panel combines independent real datasets:

| Component | Source | What it shows |
|---|---|---|
| Climate | ERA5 / ERA5-Land via Open-Meteo archive | Mean daily-max temperature anomaly and total precipitation as % of baseline for the most recent complete year versus the 1991–2020 baseline. |
| Forest cover | Hansen/UMD Global Forest Change (GFC) | Tree-cover mean in 2000, loss-year histogram, and whether loss occurred after 2020-12-31 (EUDR-style cutoff). |
| Urban expansion | OpenStreetMap via ohsome API | Building count within 500 m for 2015-01-01 and the latest ohsome extract, with growth %. |
| Population | WorldPop gridded estimates | Estimated population within 3 km, reference year, density and completeness caveats. |

Any component that cannot answer is recorded as a declared gap with a reason;
it is never interpolated or hidden.

## Crime layer

The crime layer uses **official open statistics only**.

- Integrated source: [data.police.uk](https://data.police.uk/) — official UK
  police open data for England, Wales and Northern Ireland.
- For each point inside the GB bounding box the API fetches the last 6 complete
  months of street-level crime, returning total incidents, top categories and
  monthly totals.
- For points **outside** that jurisdiction the response is an honest declared
  gap: *"No official open crime-statistics source is integrated for this
  jurisdiction (only data.police.uk is integrated). Declared gap — not a
  zero-crime statement."*
- No proxy crime score is ever produced.

## Honesty & legal boundary

Every screen carries:

> Physical-risk screening evidence only. This is not investment advice, not a
> valuation, and not a prediction. Crime figures come from official statistics
> only where an open official source exists; financial metrics are not
> quantified.

The engine:

- never emits "invest / don't invest" verdicts,
- never predicts losses,
- never computes NOI, cap rates or valuations,
- declares every unavailable hazard, trajectory component or crime source as a
gap.

## API reference

### `GET /api/v2/sector-screen/`

Public endpoint, 20 requests/minute per IP.

Parameters:

- `lat` (required) — latitude
- `lon` (required) — longitude
- `sectors` (optional) — comma-separated sector ids from the KB; defaults to all
- `name` (optional) — display name for the location

Responses:

- `200 OK` — full sector screen JSON.
- `400 Bad Request` — missing/invalid lat/lon or unknown sector id; the 400 body
  includes `valid_sectors` when a sector id is rejected.
- `429 Too Many Requests` — rate limit exceeded.
- `502 Bad Gateway` — the screen engine failed in a way that could not be
  isolated into a declared gap.

Example:

```bash
curl 'https://talaix.com/api/v2/sector-screen/?lat=51.5&lon=-0.1&sectors=logistics_ports,real_estate_commercial'
```

## Frontend

The public page is `website/sector.html` with `website/js/sector.js`. It:

- resolves a location via the shared `HS.resolveLocation` helper,
- lets users toggle sectors,
- renders per-sector exposure cards, the trajectory panel, the crime panel,
  declared gaps and methodology notes,
- supports `?location=` URL prefill.

Navigation: Sector Exposure appears under Solutions → By solution, and a
quiet cross-link is added to `for-investors.html`.

## Roadmap

- More official crime-statistics sources per country as open APIs are verified
  (each will be declared in the source registry; non-coverage remains a gap).
- Longer land-cover trajectories as more historical vintages are integrated.
- Additional sector profiles if they can be grounded in the same hazard
  vocabulary without invented studies.
