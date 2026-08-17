# HydraShield — Evidence Architecture

**Status:** normative. Every module that makes a claim follows this document.
Implements the evidence philosophy of `PRODUCT_VISION.md` ("show me the
evidence").

---

## 1. Evidence classes

HydraShield recognises exactly five evidence classes:

| Class | Meaning | Examples |
|---|---|---|
| `SCIENTIFIC` | Peer-reviewed or authoritative methodological literature | Van Wagner 1987 FWI equations; Scott & Burgan fuel models |
| `SATELLITE_EO` | Earth-observation measurements | Sentinel-2 NDMI scene; VIIRS/MODIS fire detections |
| `OPEN_DATA_OFFICIAL` | Public datasets from authorities/agencies | ERA5 via Open-Meteo, GloFAS discharge, ESA WorldCover, OSM |
| `MEDIA` | Credible press/public reports | news articles about an event (metadata + link only) |
| `MODELLED` | Output of a declared model with declared inputs | composite risk score, spread scenario, SPI-style anomaly |

**Media never overrides scientific, satellite, or official evidence.**
Media records add context (what was reported, when, by whom); they do not
change observed facts.

## 2. Evidence record schema

Every important claim carries (or links to) an evidence record:

```json
{
  "evidence_id": "sha256-derived stable id",
  "class": "OPEN_DATA_OFFICIAL | SCIENTIFIC | SATELLITE_EO | MEDIA | MODELLED",
  "claim_status": "OBSERVED | DOCUMENTED | REPORTED | MODELLED | INFERRED | UNKNOWN",
  "temporal": "OBSERVED | HISTORICAL | FORECAST | PROJECTED | SCENARIO",
  "source": "Open-Meteo archive (ERA5)",
  "dataset": "ERA5 daily, single level",
  "provider_url": "https://open-meteo.com/",
  "link": "https://archive-api.open-meteo.com/v1/archive?…",
  "location": {"lat": 49.9, "lon": 6.03},
  "reference_period": {"start": "2024-08-01", "end": "2024-08-15"},
  "acquired_at": "2026-08-17T09:00:00Z",
  "method": "daily Tmax percentile vs 1991–2020 climatology, ±7-day window",
  "resolution": "~11 km grid",
  "confidence": "high | medium | low  (+ free-text note)",
  "license": "CC BY 4.0",
  "limitations": "reanalysis, not a station measurement; grid smoothing",
  "content_hash": "sha256 of the payload this claim rests on, where computable"
}
```

Rules:

- `UNKNOWN` is a first-class status: recorded with *why* it is unknown.
- `content_hash` is computed wherever the payload is available (JSON of the
  source response subset the claim rests on). It lets users verify that a
  report and its evidence describe the same bytes.
- Legacy wildfire provenance dicts (`{kind: observed|derived|modeled|…}`)
  map onto this schema via a documented alias table — the working pipeline
  is not broken by the migration:
  `observed→OBSERVED`, `derived→INFERRED` (method declared),
  `modeled→MODELLED`, `forecast→FORECAST/MODELLED`, `unavailable→UNKNOWN`.

## 3. Claim discipline (normative)

1. **Every public numerical claim** has: source, reference period, method,
   and uncertainty where applicable.
2. **Never claim a cause** ("Cause = X") unless an authoritative source
   documents it. Fire cause defaults to `UNKNOWN`; documented causes cite
   the establishing authority.
3. **Never merge disagreeing sensors silently.** Like the existing
   FIRMS layer, record both and explain the disagreement.
4. **Projections/scenarios are visually and structurally separated** from
   observations in API payloads (the `temporal` field) and in the UI.
5. **Media policy:** store metadata (outlet, title, date, URL, language)
   and links. Do not copy article bodies. No scraping of copyrighted
   content. Media is class `MEDIA`, status at most `REPORTED`.
6. **"Cannot be quantified" is a valid output** and is stated explicitly
   (e.g. monetary exposure without a documented valuation basis).

## 4. Event evidence (multi-evidence event records)

Historical events aggregate evidence across classes:

```
ClimateEvent
 ├── satellite evidence   (detections, EO scenes)
 ├── official/open-data   (agency records, reanalysis conditions)
 ├── scientific           (methods used in interpretation)
 ├── media                (reports — context only)
 └── modelled             (HydraShield reconstruction, declared inputs)
```

- Observed evidence is stored **verbatim** (source payload subset +
  hash) and is never rewritten by later model interpretation.
- Model-derived context ("conditions preceding the event", "signals our
  indicators would have shown") lives in separate fields labelled
  `MODELLED` — see `src/climate/events.py` and the lessons engine.
- Official reports are linked (URL + authority + date), not copied.

## 5. Source registry

`config/source_registry.json` remains the public audit trail
(`GET /api/sources`, v2: `GET /api/v2/sources`). For every source:
provider, purpose, coverage, resolution, update frequency, latency,
access, license, limitations, `hydrashield_use`, `integrated_in`, and
status (`integrated | candidate | rejected` — with reasons for rejected).

New sources enter as `candidate` and move to `integrated` only with a
working fetcher + tests.

## 6. "Show me the evidence" UX contract

Every analysis payload, event, report and map layer exposes its evidence:

- API: `provenance` / `evidence` blocks on every response; event detail
  endpoint returns the full evidence list.
- UI: evidence chips on metrics (existing pattern, extended to the new
  statuses), a per-layer provenance panel on the map, and an "Evidence"
  section in every report with the full table + hashes where available.
- Reports carry: report ID, date, location, model version, data version,
  sources, evidence status, validation status.

## 7. Validation status

HydraShield's screening score is **not a validated predictor** until the
validation pipeline (`scripts/run_validation.py`) has produced a passing
`ValidationReport` on real historical data. This status is printed in
every report (existing behaviour) and surfaced by the API. New hazard
scores inherit the same discipline: unvalidated until proven otherwise,
and labelled accordingly.
