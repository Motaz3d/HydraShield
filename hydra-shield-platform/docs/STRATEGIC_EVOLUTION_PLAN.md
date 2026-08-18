# HydraShield — Strategic Evolution Plan

**Status:** active plan, executed in controlled phases. Phase 1 (audit) and
Phase 2 (product story) shipped in `6a419bd`. The business-evolution
Phases A–H below shipped in `cde9aea` (A), `066c8fc` (B+E backend),
`cc6f1c0` (E docs), `74e446f` (C), `11e2300` (D), `c87d96a` (F) and the
G/H commit. All LOCAL ONLY — nothing pushed, nothing deployed.

## Execution status board

### ALREADY IMPLEMENTED

- Six-hazard evidence platform, accounts/subscriptions, SMS/email alerts,
  webhooks, API keys, provenance + registries, reports (pre-existing).
- **Phase 1–2** — audit + product story (`docs/PRODUCT_STORY.md`,
  homepage ten-question narrative, legacy pages reframed, official
  mailbox, contact form wired to the real endpoint).
- **Phase A — Solutions Intelligence** (`cde9aea`): extended KB (economic
  sectors, confidence, quantification status, accessed dates), six
  solution packages with why_together, fit bands, inferred site sectors,
  resilience-economics block (all not_quantified), UI rendering.
- **Phase B — product analytics** (`066c8fc`): first-party event store +
  beacon, privacy by construction (hashed pseudonyms, ~11 km coordinates,
  no IPs, DNT, whitelist), 12-month retention, session erasure,
  `privacy.html`.
- **Phase E — admin analytics** (`066c8fc` + `cc6f1c0`): admin-only
  aggregate endpoints (summary/top/daily) + API docs. Visual dashboard
  page remains NEXT.
- **Phase C — marketing workspace + segmentation** (`74e446f`):
  `marketing/` knowledge base, 19 segments, lead schema + empty ledger,
  human-gated outreach queue.
- **Phase D — LinkedIn architecture** (`11e2300`): pillars, campaigns A–G,
  calendar, drafts, compliance rules.
- **Phase F — conversion UX** (`c87d96a`): contextual dismissible CTAs on
  intelligence/events/map/solutions/reports; CONVERSION_STRATEGY.md.
- **Phase G — AI copilot** (this phase): copilot protocol in
  `marketing/README.md`, `scripts/marketing_status.py` (workspace status
  + integrity check), CONTENT_STRATEGY.md (demand-driven backlog loop).
- **Phase H — integration readiness** (this phase):
  `docs/EXTERNAL_INTEGRATIONS.md` activation matrix.
- **Commercial Intelligence & Marketing Radar**: CommercialSignal +
  EventSignal ledgers with enforced provenance (source, URL,
  date_observed, date_checked, evidence_type, confidence), qualitative
  activity levels (never fabricated spend), lead schema v2 (qualification
  + relationship history vocabulary), the copilot's operator subcommands
  (signals/sectors/events/priorities/followups/content/demand/lessons/
  morning/evening), aggregate-only demand view, daily workflow
  (marketing/WORKFLOW.md), and the classified future-integrations table.

### NEXT (highest first)

1. **Annual Climate Extreme Intelligence Report** (strategic Phase 3) —
   requires a real research pass with dated institutional sources.
2. Visual admin dashboard page over the analytics aggregates.
3. Server-side events for remaining funnel steps (subscription_started,
   sms_enabled, alert_created are declared; wire at the real moments).
4. Lead research pass for 2–3 pilot segments (municipalities, insurance)
   — real organizations, public sources, schema-checked.
5. QGIS Phase 0 spike (strategic Phase 9).

### RESEARCH REQUIRED

- Annual-report source capture (WMO/IPCC/UNDRR/Copernicus/JRC/NASA/NOAA/
  ESA/World Bank/national agencies), dated and archived.
- Regional market verification (Luxembourg/EU, Gulf, China, North America)
  from official programme sources before any market claim.
- LinkedIn official API capabilities/permissions — only if API posting is
  ever considered.

### CREDENTIAL REQUIRED (unchanged)

- `FIRMS_MAP_KEY` (wildfire events), `SMTP_*` (production email),
  `HYDRASHIELD_SECRET_KEY`, `SMS_*` (real SMS delivery) — server env only.

### DEFERRED

- Platform-side polygon analysis endpoint; API-key public rate budgets;
  Gmail mailbox reading (OAuth design first); payment provider;
  X/YouTube/newsletter channels (architecture mirrors LinkedIn when a real
  cadence exists).

---

**Direction (authoritative):** HydraShield evolves from a climate-risk
analysis website into **Climate Extreme Intelligence**: Earth observation +
official open data + historical evidence → hazard intelligence → population /
settlement / business / infrastructure exposure → economic → finance &
insurance → sustainable solutions → monitoring → alerts/SMS → subscribers →
business, government and research customers → climate resilience.

Binding constraints for every phase:

- **Real data only.** No fabricated numbers, leads, companies, funding
  opportunities, market sizes, or investor names — anywhere, including
  marketing content.
- **Evidence vocabulary is part of the brand.** Every statement is one of
  OBSERVED · HISTORICAL · FORECAST · MODELLED · PROJECTED · SCENARIO ·
  INFERRED · UNKNOWN (temporal class) and OBSERVED · DOCUMENTED · REPORTED ·
  MODELLED · INFERRED · UNKNOWN (claim status). Marketing follows the same
  discipline as the product (no "predicts disasters", "prevents fires",
  "most accurate", "guarantees protection").
- **No external sending.** Outreach infrastructure (leads, drafts, queues)
  is built locally; actual email/LinkedIn/social sending is a separate,
  explicit activation step.
- **Conversion through value, not obstruction.** Free tier stays genuinely
  useful; no dark patterns.

---

## Phase 1 — Audit (done)

Verified by reading the deployed code and pages (2026-08-18).

**Already aligned (preserve):**

- Platform architecture: six equal hazard modules behind the registry
  (`src/climate/registry.py`), real-data-only with honest
  `unavailable`/`key_required` states; provenance + evidence records with
  controlled vocabularies (`src/climate/ontology.py`); source registry
  (`config/source_registry.json`) with integrated/candidate/rejected states.
- Product pages: `intelligence.html` (Analyze this place), `map.html`,
  `events.html` (Historical Event Intelligence), `economy.html`,
  `solutions.html`, `reports.html` — multi-hazard, evidence-labelled.
- Accounts/subscriptions/alerts: session + API-key auth, progressive tiers,
  SMS pipeline with phone verification, quiet hours, dedupe, unsubscribe;
  email via verified Workspace SMTP; alert engine with meaningful
  transitions; periodic checker in production (`watch_checker` service).
- Footer brand text already states the Climate Extreme Intelligence promise.

**Gaps found (fixed in Phase 2):**

1. Homepage did not answer the full narrative chain — missing *historical
   intelligence* and *finance/insurance meaning*; population exposure not
   explicit; evidence chips showed claim classes only (no temporal classes).
2. `problem.html` — wildfire-only narrative with **unsourced statistics**
   ("78 days longer fire season", "2x burned area", "~€20K/hour") — a direct
   violation of the evidence-first marketing rule.
3. `technology.html` — meta description claimed "predict and prevent
   catastrophic wildfires"; "Advanced Prediction" section claimed
   "high accuracy" fire prediction — forbidden claim classes.
4. `solution.html` — hydration-barrier "Life-First Shielding" framing
   presented an R&D programme as the product.
5. `applications.html` — wildfire testbed scenarios only; no sector view.
6. Footer contact pointed to a personal Gmail instead of the official
   `info@hydrashield.earth` mailbox.

**Deferred findings (later phases):** QGIS plugin (architecture done —
`docs/QGIS_INTEGRATION_ARCHITECTURE.md`, Phase 0 pending); no polygon
analysis endpoint; API keys are read-only; rate limiting is per-IP
in-memory; FIRMS key absent in production (wildfire events honestly
unavailable).

## Phase 2 — Product story (done, this change set)

- `docs/PRODUCT_STORY.md` — the canonical story: promise, evidence
  vocabulary, six equal hazards, the extreme→evidence→exposure→economy→
  action chain, personas, and the claim rules every page must follow.
- Homepage rebuilt on the ten-question narrative (what is happening → where
  → which hazard → who is exposed → what happened historically → what could
  happen → economic meaning → finance/insurance meaning → what can be done
  → what evidence supports it), without overloading the page.
- Legacy pages reframed: `problem.html` (the climate-extreme evidence gap,
  unsourced numbers removed), `solution.html` (the intelligence platform;
  the wildfire protection programme kept as one honestly-labelled R&D
  track), `technology.html` (real-data technology; "predict and prevent"
  removed), `applications.html` (sectors × hazards).
- Footer: official mailbox; full evidence vocabulary (claim + temporal).
- README synced.

## Phase 3 — Annual Climate Extreme Intelligence Report (next)

Deliverable: `docs/ANNUAL_CLIMATE_EXTREME_REPORT.md` + generation
architecture. Rules: authoritative institutional sources only (WMO, IPCC,
UNDRR, UNEP, FAO, Copernicus, EC/JRC, NASA, NOAA, ESA, World Bank, national
agencies); monetary figures only with value/currency/year/source/method/
uncertainty, otherwise "Not quantified from available authoritative data";
media as secondary evidence only; per-hazard sections + population and
infrastructure exposure + year-over-year changes. Requires real research
pass with dated source capture before any edition is drafted.

## Phase 4 — Market, regional & funding intelligence (docs only)

Deliverables: `docs/MARKET_STRATEGY.md`, `docs/REGIONAL_MARKETS.md`,
`docs/FUNDING_STRATEGY.md`. Regions: Luxembourg/EU, Gulf/Arab markets,
China, North America, wider Europe. Official primary sources only
(European Commission, EIB/EIF, EEA, EU funding portals, national
governments, World Bank, ADB, AIIB, Gulf investment agencies, Chinese
official programmes, UN institutions). No unsupported market-size claims;
funding records carry programme/deadline/eligibility/source/date-checked.

## Phase 5 — Customer Need Intelligence (data model + docs)

Deliverables: `docs/CUSTOMER_INTELLIGENCE.md` + local CRM schema (Lead,
Prospect, Opportunity, Contact, Campaign, Message, Interaction, Follow-up,
Conversion) as SQLite tables additive to the existing accounts DB, with a
`src/dashboard/bd/` module. Segment taxonomy: insurance, real estate,
construction, banking, investment, asset management, energy, logistics,
ports, agriculture, food, manufacturing, tourism, telecoms, data centers,
infrastructure, municipalities, governments, research, universities, NGOs.
No invented people — publicly available professional information only;
every record carries a source and date-checked.

## Phase 6 — Marketing/outreach automation architecture

Deliverables: `docs/MARKETING_AUTOMATION.md` + campaign queue tables +
draft-generation workflow with a mandatory HUMAN REVIEW gate before any
send. Segments stay separate (government / insurance / construction /
real-estate / finance / investors / research / universities /
infrastructure / energy / logistics). Pipeline: data → target → segment →
pain discovery → personalized draft → human review → send → response →
follow-up → conversion → retention. Sending itself is out of scope until
explicitly activated.

## Phase 7 — SEO/content architecture

Deliverables: `docs/SEO_STRATEGY.md` + `docs/SOCIAL_MEDIA_STRATEGY.md`.
Topic clusters around the six hazards + exposure + finance/insurance +
resilience; landing/country/hazard/annual-report/historical-event/research
page plan; evidence-based articles only; LinkedIn/X/YouTube/newsletter
content types with draft queues (no auto-publishing).

## Phase 8 — Subscription conversion UX

Every major surface gets an honest "Subscribe to monitor this" path
(analysis → save & monitor; events → track this area; map → create alert;
economy → save analysis; solutions → save plan; reports → full report with
account; SMS → enable alerts). Builds on the existing progressive gating;
no dark patterns; free tier stays useful.

## Phase 9 — QGIS Phase 0

Spike per `docs/QGIS_INTEGRATION_ARCHITECTURE.md` §16: minimal plugin
skeleton, `/api/v2/hazards` via QgsNetworkAccessManager + QgsTask, one
Processing algorithm, QgsAuthManager flow, Bandit/detect-secrets clean.
Local only; no repository submission.

## Phase 10 — Advanced automation

Only after Phases 3–9 are verified: assisted lead research workflows,
follow-up draft generation, interaction history analysis. External sending
remains an explicit activation step, auditable and per-message authorized.

---

## Cross-phase verification gates (unchanged platform discipline)

Full offline test suite · real-data integration · no-fake-data sweep ·
secret scan · Docker build · API/auth/SMS/email/report tests ·
documentation consistency. Local-first git; push/deploy only on explicit
instruction.
