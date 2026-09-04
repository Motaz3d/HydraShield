# Talaix — Implementation Roadmap

**Status:** living plan for the Climate Extreme Intelligence evolution.
Order follows the agreed priorities; each stage ships with tests and a
commit, and never breaks the working wildfire pipeline or production.

Legend: **[DONE]** shipped · **[NEXT]** current work · **[LATER]** planned ·
**[RESEARCH]** needs investigation before build · **[CREDENTIAL]** blocked
on an external key/account.

---

## Stage 0 — Audit & architecture (this document set)

- [DONE] Full audit of backend, frontend, infra/tests/deployment.
- [DONE] Vision & architecture docs: `PRODUCT_VISION.md`,
  `PLATFORM_ARCHITECTURE.md`, `CLIMATE_HAZARDS.md`,
  `EVIDENCE_ARCHITECTURE.md`, `ECONOMIC_INTELLIGENCE.md`,
  `FINANCIAL_INTELLIGENCE.md`, `SOLUTIONS_INTELLIGENCE.md`,
  `USER_AND_SUBSCRIPTION_ARCHITECTURE.md`.

## Stage 1 — Ontology & evidence core

- [DONE] `src/climate/ontology.py` — hazard types, claim status
  (`OBSERVED/DOCUMENTED/REPORTED/MODELLED/INFERRED/UNKNOWN`), temporal
  classes, five evidence classes, cause discipline (DOCUMENTED-or-UNKNOWN).
- [DONE] `src/climate/evidence.py` — `EvidenceRecord` with content hashing,
  media capped at REPORTED, legacy provenance upgrade (`modeled`→`modelled`).
- [DONE] 21 offline tests (`tests/test_climate_core.py`).

## Stage 2 — Multi-hazard framework + historical event model

- [DONE] `src/climate/hazards/base.py` + `registry.py` — plugin contract +
  auto-discovery; a hazard registers only when wired to real data sources.
- [DONE] `WildfireModule` wraps the proven engine (raw payload preserved;
  v1 API untouched).
- [DONE] `src/climate/events.py` — `ClimateEvent` (observed conditions
  structurally separated from modelled context; cause enforced; evidence
  per event) + SQLite `EventStore` (`climate_events`, `event_evidence`).
- [DONE] `/api/v2/hazards`, `/api/v2/hazards/<id>`, `/api/v2/analyze`,
  `/api/v2/events`, `/api/v2/events/<id>`, `/api/v2/sources`.

## Stage 3 — Historical fire intelligence

- [DONE] `src/climate/fire_events.py` — real FIRMS detections (key-gated)
  clustered spatio-temporally; ERA5 observed conditions; FWI modelled
  context; lessons strictly from the event's own data; cause always
  UNKNOWN (no authoritative source); containment UNKNOWN; years never
  hardcoded (VIIRS 2012→present, honestly bounded); `key_required` /
  `unavailable` states. Persisted to the event store.
- [DONE] Map evolution (delivered in Stage 8): dedicated map page, year
  selector built from dataset coverage, hazard selector, layer panel with
  per-layer legend/source/date/resolution/status/provenance,
  observed/modelled filter, lazy layers.

## Stage 4 — Flood / drought / heat / wind / coastal foundations

- [DONE] Flood: GloFAS discharge (Open-Meteo Flood API) + ERA5 extreme
  precipitation + antecedent index + terrain context + OSM exposure.
  Declared: no flood-extent maps, no forecasts.
- [DONE] Drought: standardized precipitation anomaly (30/90/180 d; not
  full SPEI), ERA5-Land soil-moisture anomaly, ET₀ balance, dry spells,
  cropland exposure, historical comparison.
- [DONE] Heat + wind: ERA5 day-of-year climatological percentiles
  (1991–2020 baseline) + spell detection + historical extremes.
- [DONE] Coastal: Marine API waves (observed/forecast labelled), DEM
  low-elevation screening, OSM exposure; sea-level rise only as
  PROJECTED/SCENARIO block (IPCC AR6 approximate ranges).
- [DONE] Key-free fetchers (append-only in `real_data.py`): flood
  discharge, generalised daily climate archive, marine. Source registry
  entries added. 34 offline tests; live smoke verified.
- [RESEARCH] Sentinel-1 flood extent, EFAS/GloFAS direct, Copernicus
  Marine/CDS sea-level products. [CREDENTIAL] CDSE/Copernicus accounts.

## Stage 5 — Economic exposure + solutions intelligence

- [DONE] `exposure_econ.py` — exposure categories from real OSM/ohsome +
  WorldCover data; `monetary_quantification` always `not_quantified` with
  the exact statement; framework slots honestly empty; `/api/v2/economy`.
- [DONE] `solutions.py` + `config/solutions_knowledge.json` — 21 curated,
  sourced entries across 8 classes and all 6 hazards; condition-matched
  `why_it_fits` quoting real site values; limitations + no-guarantee
  disclaimer on every solution; insufficient-data path;
  `/api/v2/solutions`. 16 offline tests.
- [LATER] Technology discovery engine v1 (source-class registry,
  verifiable-only entries).
- [LATER] Population grid integration (GHSL/WorldPop) — [RESEARCH]
  licensing + pipeline.

## Stage 6 — Users, accounts, progressive gating

- [DONE] Schema (users/sessions/organizations/subscriptions/api_keys/
  saved_locations/analysis_history/report_history/alerts/usage/audit) on
  the shared SQLite DB, additive-only.
- [DONE] Auth + account endpoints (register/verify/login/logout/resend/
  account/locations/history/alerts/usage) + public `/api/v2/contact`;
  PBKDF2-HMAC-SHA256 (120 k iters), HMAC-hashed tokens, HttpOnly
  SameSite cookies, per-tier rate limits, anti-enumeration, audit log
  without secrets, GDPR consent recorded. 21 offline tests.
- [DONE] Website account UI (Stage 8: account.html — register/login/
  locations/alerts/history).
- [LATER] Gating touchpoints depth (tier descriptors surfaced in UI
  prompts), CSRF double-submit for browser cookie POSTs (SameSite=Lax
  interim), GDPR data-subject export/erasure endpoints, watch→account
  migration, organization seats/admin UI, payments [CREDENTIAL].

## Stage 7 — Reports + email

- [DONE] `mailer.py` + 7 templates (welcome, verification, report
  ready/delivery, alert, contact ack, subscription confirmation);
  SMTP when configured, safe `.eml` outbox backend otherwise;
  `SMTP_FROM=info@talaix.com`; legacy `SMTP_PASS` honoured;
  watch alerts migrated with behaviour preserved. 10 offline tests.
- [DONE] Report metadata block in all three PDF types (report ID, engine
  version, data sources, evidence-status counts, validation status).
- [LATER] Multi-hazard report sections; report-delivery email for
  accounts; report scheduling for organizations.

## Stage 8 — Website information architecture

- [DONE] Shared chrome (header/footer include) killing 7-way nav
  duplication; primary nav: Intelligence · Map · Events · Solutions ·
  Economy · Reports (+ Account); homepage rebuilt as the 8-question
  story (live snapshot preserved); legacy pages under About.
- [DONE] map.html as the core product: hazard selector from the registry,
  year selector derived from per-dataset temporal coverage (never
  hardcoded), grouped layer panel with per-layer legend/source/
  resolution/status/temporal/provenance, lazy layers, observed/modelled
  evidence filter, honest key_required/unavailable states.
- [DONE] events.html (multi-evidence event cards), intelligence.html
  (six-hazard tabs, generic HazardAnalysis rendering), solutions.html,
  economy.html (prominent not-quantified statement + disclaimers),
  reports.html (report types + metadata explanation), account.html
  (register/login/locations/alerts/history).
- [LATER] Decommission Dash "Command Center" after static app parity
  (remove compose entry + Caddy route; delete `dashboard.py`/
  `components.py` whose scenario simulator uses demo constants —
  recorded here so it is not mistaken for a live path).

## Stage 9 — Financial & insurance intelligence (evidence stage)

- [DONE] Free loss-data integration (2026-09-02): NOAA NCEI Billion-Dollar
  Weather and Climate Disasters wired via the public ArcGIS feature service
  (`USA_Billion_Dollar_Disasters_view`). `src/climate/losses.py` now serves
  documented US national aggregates (1980-2021, CPI-adjusted) tagged with
  source, reference period, geographic scope and licence note. The
  `observed_losses` block in `src/climate/economic_impact.py` surfaces these
  figures for US queries and remains honestly unavailable outside US coverage.
- [DONE] `GET /api/v2/losses/summary` added for the homepage loss-data card,
  returning the contract `{status, items[{label,value,unit,source,
  reference_period}], disclaimer}` with real figures or an honest unavailable
  reason.
- [DONE] Staged-ingest paths documented for EM-DAT (`data/emdat_export.csv`)
  and DesInventar (`data/desinventar_exports/`) — parsed when operator
  provides exports, unavailable with reason when absent.
- [DONE] Curated `observed_events` in `config/loss_registry.json` (v1: July
  2021 European floods, August 2002 Elbe floods, July 2018 Attica wildfires)
  — published official/primary-source figures with full honesty tags,
  matched to a location by country-scope bounding boxes (smallest bbox
  wins). The three classic report types render them in a "Documented
  disaster losses" section (`src/dashboard/report.py`, wired in
  `src/dashboard/api.py`); the section declares the gap when no documented
  figure covers the location. See `docs/ECONOMIC_INTELLIGENCE.md` §8-§10.
- [DONE] Talaix Loss Screening Estimate v1 (`src/climate/loss_estimate.py`
  + `config/loss_estimate_benchmarks.json`): the engine's own ESTIMATED
  monetary function — exposed-value range computed from real mapped
  building counts × declared benchmark bands (per-country replacement
  cost, floor-area assumption), matched by smallest containing country
  bbox. Expected-loss slot honestly `not_available` (no damage-ratio
  model). Served as a strictly separated sub-block in the three classic
  reports and at `GET /api/v2/losses/estimate`. Never merged with
  DOCUMENTED figures.
- [DONE] Estimate propagated to all output surfaces (2026-09-04): the three
  classic report types, the Insurance Environmental Risk Profile PDF
  (strictly separated from the loss-not-quantified rule), the
  `/api/v2/economic-impact` engine payload (new `loss_screening_estimate`
  block + `block_status`), and the homepage live loss-context card
  (ESTIMATED card for the top monitored area, fed by the estimate
  endpoint). Acquisition study for purchasable loss/valuation APIs and
  free upgrades: `docs/LOSS_DATA_ACQUISITION.md`.
- [DONE] Commercial sources (Munich Re NatCatSERVICE, Swiss Re sigma) marked
  `planned` with status note: "Commercial licence to be procured after first
  platform revenue (operator decision 2026-09-02)".
- [LATER] Evidence pack assembly per asset/location (exposure profile +
  hazard frequency + resilience profile + uncertainty) with disclaimers;
  scenario-exposure slot wired to the projected-data stage.
- [LATER] Adaptation cost ranges from sourced KB figures only.

## Stage 10 — Platform & API infrastructure

- [DONE] CI test gating: the offline suite runs in GitHub Actions before
  any deploy; post-deploy health check fails the workflow on an unhealthy
  stack.
- [DONE] API-first foundation (see `docs/API_FIRST_STRATEGY.md`,
  `docs/API_V2.md`): stable versioned contract (additive-only);
  `X-API-Key` read-only subscriber keys (create/list/revoke, HMAC-hashed);
  CORS for public GET endpoints via `HYDRASHIELD_CORS_ORIGINS`;
  HMAC-signed webhooks (SSRF-guarded, at-least-once, recorded statuses);
  significant-change trigger (declared 24 h/7 d delta heuristic, never a
  validated anomaly model) wired into the alert engine.
- [DONE] Developer interfaces: Python SDK (`sdk/python`, stdlib-only),
  JavaScript SDK + `<hydrashield-risk>` Web Component (`sdk/js`, deployed
  mirror `website/sdk/hydrashield.js`), `website/embed.html` demo,
  offline tests for both SDKs.
- [DONE] Products & partnerships strategy
  (`docs/PRODUCTS_AND_PARTNERSHIPS.md`): property risk, climate due
  diligence, insurance, finance, infrastructure, agriculture, supply
  chain, ESG/CSRD, government — all on the same engine; build-vs-partner
  discipline; continuous dataset→API→product pipeline.
- [LATER] Webhook retry/backoff worker; usage metering dashboards;
  `/api/v2` OpenAPI spec generation from the contract doc; multi-hazard
  significant-change series; standard formats (CAP) productionisation.
- [LATER] PostgreSQL evaluation when multi-tenant volume justifies it.
- [LATER] Climate Intelligence API / Evidence API productisation
  (strategic direction — see PRODUCT_VISION §7).

## Cross-cutting quality gates (every stage)

- Real data only; no-fake-data sweep (`grep`-enforced conventions + code
  review checklist in PRs).
- Every new claim carries provenance per `EVIDENCE_ARCHITECTURE.md`.
- Offline tests for all new logic; live-network smoke stays in
  `test_real_integration.py` (manual).
- Docker build green before any production push; production deploys only
  via `main` after green CI.

## External credentials register

| Credential | Unlocks | Status |
|---|---|---|
| `FIRMS_MAP_KEY` (free) | historical fire events layer | already supported |
| SMTP_* (talaix.com mailbox) | production email | configured at deploy time |
| `HYDRASHIELD_SECRET_KEY` | production token security | configured at deploy time |
| CDSE / Copernicus account | Sentinel-1 flood extent, CLMS | research stage |
| Copernicus Marine / CDS account | sea-level/ocean products | research stage |
| Payment provider | subscriptions billing | later stage |
