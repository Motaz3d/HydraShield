# HydraShield — Implementation Roadmap

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

- [NEXT] `src/climate/ontology.py` — hazard/event/exposure/evidence
  dataclasses; classification vocabularies (`OBSERVED … UNKNOWN`,
  temporal `OBSERVED/HISTORICAL/FORECAST/PROJECTED/SCENARIO`).
- [NEXT] `src/climate/evidence.py` — typed evidence record, content
  hashing, legacy provenance alias mapping (`modeled`→`modelled`, …).
- [NEXT] Tests (offline).

## Stage 2 — Multi-hazard framework + historical event model

- [NEXT] `src/climate/hazards/base.py` + `registry.py` — plugin interface
  (`analyze / events / explain / recommendations / map_layers /
  report_sections`), hazard registry, `/api/v2/hazards`.
- [NEXT] Wildfire plugin wrapping `HydraShieldRealAnalyser` (no rewrite of
  the working engine).
- [NEXT] `src/climate/events.py` — `ClimateEvent` + SQLite store
  (`climate_events`, `event_evidence`), evidence attached per event,
  classification + cause discipline (`UNKNOWN` unless documented).
- [NEXT] Tests (offline).

## Stage 3 — Historical fire intelligence

- [NEXT] Event derivation from real FIRMS detections (key-gated) + ERA5
  fire-weather conditions (always available): multi-day event clustering,
  per-day conditions (FWI, wind, RH, rain), observed-vs-modelled
  separation, lessons extraction strictly from the event's own data.
- [NEXT] `/api/v2/events?hazard=wildfire&lat&lon&radius_km&year=` —
  any year the datasets cover; no hardcoded year list; honest
  `unavailable`/`key_required` states.
- [LATER] Map evolution: dedicated map page, year selector (built from
  dataset coverage), hazard selector, layer panel with per-layer
  legend/source/date/resolution/status/provenance, observed/modelled
  filter, lazy layers.

## Stage 4 — Flood / drought / heat / wind / coastal foundations

- [NEXT] Flood foundation: Open-Meteo Flood API (GloFAS discharge) +
  ERA5 extreme-precipitation analysis + terrain + OSM waterway exposure.
- [NEXT] Drought foundation: ERA5/ERA5-Land precipitation deficit,
  soil-moisture anomaly, ET₀ balance, NDMI vegetation stress, WorldCover
  cropland exposure.
- [NEXT] Heat + wind foundations: ERA5 climatological percentiles + spell
  detection (declared methods).
- [NEXT] Coastal foundation: Open-Meteo Marine API waves + DEM low-lying
  screening + OSM coastal infrastructure; sea-level only as labelled
  `PROJECTED/SCENARIO` from published sources.
- [NEXT] `/api/v2/analyze?hazard=…` for each; honest `unavailable` paths.
- [RESEARCH] Sentinel-1 flood extent, EFAS/GloFAS direct, Copernicus
  Marine/CDS sea-level products. [CREDENTIAL] CDSE/Copernicus accounts.

## Stage 5 — Economic exposure + solutions intelligence

- [NEXT] `src/climate/exposure_econ.py` — exposure categories from real
  mapped data; explicit `not_quantified` monetary statement;
  `/api/v2/economy`.
- [NEXT] `src/climate/solutions.py` + `config/solutions_knowledge.json` —
  curated, sourced, condition-matched solutions across hazards with
  limitations + no-guarantee disclaimer; `/api/v2/solutions`.
- [LATER] Technology discovery engine v1 (source-class registry,
  verifiable-only entries).
- [LATER] Population grid integration (GHSL/WorldPop) — [RESEARCH]
  licensing + pipeline.

## Stage 6 — Users, accounts, progressive gating

- [NEXT] Schema (users/sessions/organizations/subscriptions/api_keys/
  saved_locations/analysis_history/report_history/alerts/usage/audit),
  PBKDF2 password hashing, hashed tokens, `require_role`, per-tier limits.
- [NEXT] Auth + account endpoints (register/verify/login/locations/
  history/alerts/usage), `/api/v2/contact`.
- [LATER] Website account UI + gating touchpoints ("save", "history",
  "full report" prompts) wired to tier descriptors.
- [LATER] Organization seats/admin UI; payments via provider
  [CREDENTIAL].

## Stage 7 — Reports + email

- [NEXT] `src/dashboard/mailer.py` + templates (welcome, verification,
  report ready/delivery, alert, contact ack, subscription confirmation);
  dev outbox backend (`data/outbox/`) when SMTP unset;
  `SMTP_FROM=info@hydrashield.earth`; legacy `SMTP_PASS` honoured.
- [NEXT] Watch alerts routed through the mailer (behaviour unchanged).
- [NEXT] Report metadata block (report ID, model/data versions, evidence
  + validation status) in all PDFs; multi-hazard report sections.
- [LATER] Report-delivery email for accounts; report scheduling for
  organizations.

## Stage 8 — Website information architecture

- [NEXT] Primary nav: Intelligence · Map · Events · Solutions · Economy ·
  Reports (+ Account). Homepage rebuilt as the 8-question story. Per-hazard
  intelligence pages. Shared header/footer partial (build-free JS include)
  to kill 7-way nav duplication. Consolidate divergent inline design
  systems into `style.css`.
- [NEXT] Map as dedicated core page (see Stage 3).
- [LATER] Decommission Dash "Command Center" after static app parity
  (remove compose entry + Caddy route; delete `dashboard.py`/
  `components.py` whose scenario simulator uses demo constants —
  recorded here so it is not mistaken for a live path).

## Stage 9 — Financial & insurance intelligence (evidence stage)

- [LATER] Evidence pack assembly per asset/location (exposure profile +
  hazard frequency + resilience profile + uncertainty) with disclaimers;
  scenario-exposure slot wired to the projected-data stage.
- [LATER] Adaptation cost ranges from sourced KB figures only.
- [RESEARCH] Documented valuation/loss datasets (e.g. EM-DAT access
  terms) before any monetary figure ever appears. [CREDENTIAL] possibly.

## Stage 10 — Platform & API infrastructure

- [NEXT] CI test gating: offline test suite runs in GitHub Actions before
  any deploy to Vultr.
- [LATER] API keys + usage metering for subscriber API access;
  `/api/v2` OpenAPI description; versioned dataset stamps on responses.
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
| SMTP_* (hydrashield.earth mailbox) | production email | configured at deploy time |
| CDSE / Copernicus account | Sentinel-1 flood extent, CLMS | research stage |
| Copernicus Marine / CDS account | sea-level/ocean products | research stage |
| Payment provider | subscriptions billing | later stage |
