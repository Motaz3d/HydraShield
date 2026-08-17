# HydraShield — Platform Architecture

**Status:** target architecture for the Climate Extreme Intelligence evolution,
grounded in the audited current system. Read together with
`PRODUCT_VISION.md`, `CLIMATE_HAZARDS.md`, `EVIDENCE_ARCHITECTURE.md` and
`IMPLEMENTATION_ROADMAP.md`.

---

## 1. Current architecture (audited 2026-08-17)

```
                        ┌──────────────┐
        browsers ──────▶│ Caddy (TLS)  │
                        └──────┬───────┘
              ┌────────────────┼─────────────────────┐
              │ /api/*         │ /*                  │ app.hydrashield.earth
              ▼                ▼                     ▼
      ┌──────────────┐ ┌───────────────┐   ┌──────────────────┐
      │ Flask API    │ │ Static website│   │ Dash "Command    │
      │ gunicorn     │ │ (9 HTML pages)│   │ Center" (legacy) │
      │ :8051        │ │ vanilla JS    │   │ gunicorn :8050   │
      └──────┬───────┘ └───────────────┘   └────────┬─────────┘
             │                                      │
             └──────────┬───────────────────────────┘
                        ▼
        SQLite (WAL) /data/hydrashield_cache.sqlite3
        tables: cache · analysis_jobs · action_plan_audit · watches · alerts
                        ▲
             watch_checker container (30 min loop:
             check_watches.py + build_risk_snapshot.py)
```

- **Analysis engine:** `src/dashboard/real_analysis.py` — a linear 12-stage
  wildfire pipeline producing one monolithic analysis dict. All context
  blocks (explain, change, exposure, micro, ecology, scenarios,
  recommendations, history, fire_evidence) hang off it.
- **Provenance:** ad-hoc dict convention (`{kind, source, acquired, …}`),
  built in ~10 places, two spellings (`modeled` / `MODELLED`).
- **Frontend:** static site, `dashboard.html` = one scrolling column of
  ≈19 top-level cards; Leaflet map is card #14. No year selector, no hazard
  selector, no color legends.
- **Auth:** none deployed. `src/security/` (HMAC tokens, roles, GDPR
  helpers) is tested but unwired.
- **Legacy/parallel stacks:** Dash dashboard, `standard_formats_api.py`
  (returns sample data — not deployed), ML risk model track (trained, never
  served), `data_fusion.py`, `mapping.py`, `verification.py` (design-stage).

## 2. Target architecture

The evolution introduces a **hazard plugin core** while keeping the proven
wildfire pipeline running underneath.

```
┌──────────────────────────── FRONTEND ───────────────────────────┐
│ website/  (static, vanilla JS)                                   │
│  index.html      — story-driven homepage (1 story, 8 questions)  │
│  intelligence.html — per-hazard pages (wildfire/flood/drought/…) │
│  map.html        — THE MAP (core product): year + hazard +       │
│                    layer + time + source + status filters        │
│  events.html     — historical event intelligence                 │
│  solutions.html  — solutions intelligence                        │
│  economy.html    — economic/financial/insurance intelligence     │
│  reports.html    — report centre                                 │
│  account.html    — login, saved locations, history, alerts       │
└──────────────────────────────┬───────────────────────────────────┘
                               ▼
┌──────────────────────────── API (Flask) ────────────────────────┐
│ /api/…        existing wildfire endpoints (unchanged contracts)  │
│ /api/v2/…     multi-hazard platform API:                         │
│   GET /api/v2/hazards                    hazard registry         │
│   GET /api/v2/hazards/<id>               hazard descriptor       │
│   GET /api/v2/analyze?hazard=&lat=&lon=  hazard analysis         │
│   GET /api/v2/events?hazard=&year=&bbox= historical events       │
│   GET /api/v2/events/<id>                event detail + evidence │
│   GET /api/v2/exposure?lat=&lon=         exposure intelligence   │
│   GET /api/v2/economy?lat=&lon=          economic exposure       │
│   GET /api/v2/solutions?lat=&lon=&hazard= solutions engine       │
│   POST/GET /api/v2/auth/…  /api/v2/account/…   accounts (tiered) │
└──────┬───────────────────────────────────────┬──────────────────┘
       ▼                                       ▼
┌─────────────────────┐           ┌──────────────────────────────┐
│ src/climate/        │           │ src/dashboard/ (existing)    │
│  ontology.py        │           │  real_analysis.py  wildfire  │
│  evidence.py        │◀──────────│  engine (wrapped as the      │
│  events.py          │  evidence │  wildfire hazard plugin)     │
│  registry.py        │  records  │  report.py · history.py · …  │
│  hazards/           │           └──────────────────────────────┘
│   base.py  wildfire │
│   flood.py drought  │           src/security/ (wired in for
│   heat.py  wind.py  │           accounts + API keys)
│   coastal.py        │
│  solutions.py       │           src/prediction/  science core
│  exposure_econ.py   │           src/gis_mapping/ EO access
└──────┬──────────────┘
       ▼
┌──────────────────────── DATA LAYER (SQLite, WAL) ───────────────┐
│ cache · analysis_jobs · action_plan_audit · watches · alerts     │
│ + climate_events · event_evidence · users · organizations ·      │
│   sessions · saved_locations · analysis_history · usage_log      │
└──────────────────────────────────────────────────────────────────┘
```

## 3. Core design decisions

### 3.1 Hazard plugin architecture (`src/climate/hazards/`)

Every hazard implements one interface (`base.HazardModule`):

```python
class HazardModule:
    id: str                    # "wildfire", "flood", "drought", …
    name: str
    def analyze(lat, lon, **kw) -> HazardAnalysis      # current conditions
    def events(lat, lon, radius_km, year=None) -> list[ClimateEvent]
    def explain(analysis) -> list[Factor]              # "why this level?"
    def recommendations(analysis) -> list[dict]        # evidence-linked
    def map_layers(lat, lon, year=None) -> list[LayerSpec]
    def report_sections(analysis) -> list[ReportSection]
```

- The **wildfire plugin wraps** `HydraShieldRealAnalyser` — no rewrite of
  the working engine; the plugin adapts its dict into the shared
  `HazardAnalysis` shape.
- New hazards (flood, drought, heat, wind, coastal) are **foundations built
  on real key-free sources** (Open-Meteo archive/forecast/marine/flood,
  ERA5, OSM, WorldCover, DEM) — never placeholders. Where an analysis
  cannot be computed from real data, the module returns
  `status: unavailable` with an explanation, exactly like the existing
  fire layers without a FIRMS key.
- A hazard is only registered when it has at least one **real, documented
  data source** wired in. No fake hazard boxes.

### 3.2 Typed evidence core (`src/climate/evidence.py`)

Replaces the ad-hoc provenance dict convention with one typed record used
by every module (see `EVIDENCE_ARCHITECTURE.md` for the full schema and
rules). The existing `kind` vocabulary is unified to
`observed | documented | reported | modelled | inferred | unavailable`,
with a legacy-alias mapping so the wildfire pipeline keeps working
unchanged.

### 3.3 Historical event model (`src/climate/events.py`)

A `ClimateEvent` is the platform's unit of historical intelligence:

```
ClimateEvent
  id · hazard · location (lat/lon/area) · start_date · end_date
  classification: OBSERVED | DOCUMENTED | REPORTED | MODELLED | INFERRED | UNKNOWN
  magnitude / severity (per-hazard, source-bound)
  conditions (FWI, weather, discharge, … — observed vs modelled separated)
  exposure summary (links to exposure intelligence)
  evidence: [EvidenceRecord…]   (satellite, official, open data, media)
  cause: documented-only, else UNKNOWN
  containment / response info where documented
  uncertainty: free-form + confidence
  lessons: extracted strictly from the event's own observed/modelled data
```

- Events are **derived from real datasets** (FIRMS detections, ERA5
  extremes, GloFAS discharge) and stored in SQLite (`climate_events`,
  `event_evidence`) with their evidence records attached.
- **Observed evidence is never rewritten by model interpretation.**
  Lessons/model context are stored in separate fields, clearly labelled.
- Years are **never hardcoded** — the API exposes whatever years the
  underlying datasets actually contain.

### 3.4 Exposure → economy → finance layering

- `src/dashboard/exposure.py` (OSM/ohsome) already provides hazard-agnostic
  exposure counts — it is reused as-is.
- `src/climate/exposure_econ.py` adds the **economic exposure framework**:
  structured categories (people/buildings/agriculture/energy/transport/
  critical facilities/…), populated only from real mapped data, with the
  explicit sentence *"economic exposure cannot currently be quantified from
  available data"* wherever a monetary valuation has no documented basis.
  See `ECONOMIC_INTELLIGENCE.md` and `FINANCIAL_INTELLIGENCE.md`.

### 3.5 Solutions engine (`src/climate/solutions.py`)

Generalises the existing `ecology.py` pattern (site conditions → curated,
sourced knowledge base → matched recommendations with honest "insufficient
data" path) to all hazards and solution classes. Knowledge base:
`config/solutions_knowledge.json`. See `SOLUTIONS_INTELLIGENCE.md`.

### 3.6 Users, accounts, gating

New tables + Flask blueprint, reusing `src/security/api_security.py`
primitives. Progressive value-based gating (anonymous → email → account →
subscriber → organization). See `USER_AND_SUBSCRIPTION_ARCHITECTURE.md`.

### 3.7 API versioning

Existing `/api/…` contracts are frozen (frontend + any consumers keep
working). All multi-hazard functionality lands under `/api/v2/…`.
The wildfire-only endpoints remain the v1 face of the wildfire plugin.

### 3.8 Frontend information architecture

Primary navigation: **Intelligence · Map · Events · Solutions · Economy ·
Reports** (+ Account). The homepage tells one story in order:
what is happening → where → who/what is exposed → what could happen →
economic meaning → what can be done → evidence → call to action.
The map becomes a dedicated page and the core product, with
year/hazard/layer/time/source/status selectors and lazy layers — every
layer carrying legend, source, date, resolution, status and provenance.

### 3.9 Deployment & safety

- Topology unchanged (Caddy + api + website + watch_checker). The Dash
  app is **deprecated** (see roadmap); it stays up until the static app
  fully replaces it, then compose entry removal is a separate stage.
- **CI gating:** the offline test suite (227 tests) runs in GitHub Actions
  *before* the deploy step. No green tests, no production deploy.
- Schema changes are additive-only per release; the SQLite file is shared
  by api + watch_checker, so migrations must be backward-compatible and
  idempotent (`CREATE TABLE IF NOT EXISTS`, `ALTER … ADD COLUMN` guarded).

## 4. Reuse map (what we keep building on)

| Existing asset | Role in target architecture |
|---|---|
| `cache.py` TTLCache + `@cached` | unchanged, shared by all hazards |
| `jobs.py` staged jobs | reused; hazard id added to job payload |
| `real_data.py` fetcher scaffolding + Open-Meteo/ERA5 fetchers | base for all new hazard fetchers |
| `fwi.py` pure-series index pattern | template for drought/heat/wind indices |
| `exposure.py` OSM/ohsome | exposure layer for all hazards |
| `grid.py` batched grid pattern | per-hazard map grids |
| `history.py` ERA5→periods→lessons template | generalized into events engine |
| `fire_evidence.py` multi-sensor evidence | template for event evidence records |
| `report.py` 3-audience PDF machinery | extended with new sections |
| `source_registry.json` + `/api/sources` | grows per new dataset; served at v2 too |
| `monitoring.py` watches + SMTP alerts | gains `hazard` column |
| `security/api_security.py` | wired in for accounts |
| Docker/Caddy/compose topology | unchanged |
| 227-test offline suite | extended per stage; wired into CI |

## 5. Explicitly out of scope for now

- PostgreSQL migration (SQLite WAL is adequate at current scale; revisit
  when multi-tenant volume justifies it).
- Data-center / DaaS infrastructure (strategic direction only — §7 of
  PRODUCT_VISION).
- Regulated financial products, premium calculation, actuarial modelling.
- EFFIS/GWIS, Sentinel-1 SAR, CDSE integrations (candidates in the source
  registry; require their own stage + possibly credentials).
- Media scraping (metadata + links only, per evidence policy).
