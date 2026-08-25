# Insurance & Environmental Risk

Talaix Insurance Environmental Risk Profiles combine current per-peril hazard
levels with long-term historical event records for insured assets. The product
is aimed at underwriters and reinsurers as an evidence-based screening layer.

## Purpose

- Provide a pre-catastrophe-model evidence view of an insured asset or
  portfolio.
- Combine (a) current hazard levels from the Green Finance Verification
  engine with (b) historical events from each hazard module's `events()` API.
- Support regulatory and prudential contexts (EIOPA stress tests, Solvency II)
  with explicit boundaries on what is not covered.

## Inputs

- **Asset location**: `lat`, `lon`, optional `name`.
- **Search radius**: default 50 km, valid range 1–500 km. Event searches are
  executed within this radius.
- **Portfolio**: list of `{name, lat, lon}` assets, optional shared radius.

## Peril mapping

| Hazard id | Insurance peril label |
|-----------|----------------------|
| flood | Flood (riverine / pluvial) |
| wildfire | Wildfire |
| wind | Windstorm |
| heat | Heatwave |
| drought | Drought |
| coastal | Coastal / storm surge |

Only perils registered in `src.climate.registry` are checked. Missing or
unavailable perils are declared as gaps.

## Events / time dimension

For each peril, the engine calls `module.events(lat, lon, radius_km=...)`. The
result is mapped to:

- `events_status`: `ok`, `unavailable` or `key_required`.
- `events_count`: number of events returned.
- `events_summary`: first 5 events trimmed to safe scalar fields
  (id, date/year, name/title, severity).
- `events_reason`: honest reason when events are unavailable.
- `temporal_coverage`: declared dataset coverage from the module when
  available.

Unavailable event datasets are recorded as declared gaps, never invented.

## Loss quantification rule

Monetary loss quantification is **not provided**. The profile explicitly
states:

- No ground-up loss estimate.
- No exceedance-probability curve.
- No AAL/PML or scenario loss number.

This is a hazard-level and event-history data layer only.

## Frameworks

- **EIOPA climate and natural-catastrophe stress tests** — regulatory context.
  The profile's per-peril levels and event history provide the physical-
  evidence layer; it is not a scenario or loss model.
- **Solvency II** — prudential context. Can inform underwriting risk
  identification; does not replace internal model or standard-formula
  calculations.
- **Protection gap / EIOPA nat-cat dashboard** — market context. Evidence-
  based screening can help close data gaps on exposed assets.

## Disclaimer

Talaix Insurance Environmental Risk Profiles are screening-level data products
for underwriters and reinsurers. This is **NOT** a vendor catastrophe model,
**NOT** a rate-making or pricing tool, and **NOT** actuarial advice. Levels
are screening indicators unless explicitly labelled validated. Event records
are limited to the declared dataset coverage per peril.

## Relation to Green Finance Verification

Both features use the same `src.climate.verification` engine for current
hazard levels. Insurance & Environmental Risk adds the time dimension via
`module.events()` and uses an insurance peril vocabulary.

## API reference

All endpoints are mounted under `/api/v2/insurance`.

### `GET /api/v2/insurance/profile`

Single-asset risk profile.

Query parameters:

- `lat` — latitude (`-90` to `90`).
- `lon` — longitude (`-180` to `180`).
- `name` — optional asset name.
- `radius_km` — event search radius, default `50`, valid `1`–`500`.

Rate limit: 20/minute.

Response: the full `build_risk_profile` JSON.

### `GET /api/v2/insurance/profile/report`

PDF version of the single-asset profile. Same query parameters. Rate limit:
10/minute. Returns `503` if `reportlab` is not installed.

### `POST /api/v2/insurance/portfolio`

Batch portfolio check. Requires the `registered` role.

Request body:

```json
{
  "name": "optional portfolio name",
  "assets": [
    {"name": "Trier plant", "lat": 49.75, "lon": 6.64},
    {"name": "A Coruña terminal", "lat": 43.3, "lon": -8.4}
  ],
  "radius_km": 50
}
```

Limits: 25 assets for `registered`, 100 for `subscriber` and above.

Response:

```json
{
  "portfolio_id": "…",
  "count": 2,
  "ok_count": 2,
  "portfolio_summary": {
    "site_count": 2,
    "ok_count": 2,
    "level_distribution": {"flood": {"High": 2}},
    "total_declared_gaps": 0
  },
  "results": […]
}
```

### `GET /api/v2/insurance/portfolio/<portfolio_id>`

Return the full stored portfolio record. Owner or admin only. `404` for
unknown IDs, `403` for other users' portfolios.

## Roadmap

- Accumulation indicators across a portfolio.
- Exposure-weighted portfolio metrics.
- ERA5-based long-term danger series per peril.
