# HydraShield — QGIS Integration Architecture

**Status:** design only — no implementation yet. This document evaluates a
HydraShield QGIS plugin / Processing provider as a strategic distribution
channel, based on a full inventory of the deployed platform API
(`src/dashboard/api.py`, `src/climate/api_v2.py`, `src/dashboard/auth_api.py`,
`src/dashboard/sms_api.py`) and on official QGIS sources, fact-checked
2026-08-18 against: the plugins.qgis.org publish rules, the 2016 QGIS
plugin-licensing post, the QGIS user-manual authentication chapter, the
QGIS visual changelog, QEP 409 (plugin security scanning) and the Plugins
Website v4.0.0 announcements.

Norms carried over from the platform: real data only; honest unavailable
states; provenance on everything; conversion through value, not obstruction;
no credentials in project files, Git, or logs.

---

## 1. Why QGIS is a strategic channel

QGIS is the default desktop GIS for exactly the audiences HydraShield serves:
municipal GIS officers, civil-protection analysts, environmental consultants,
insurers, researchers, and utility/land-asset teams. These users already work
in QGIS all day; they will not open a website to re-check a place they have
as a layer. A QGIS plugin puts HydraShield's evidence *inside* their existing
workflow, on their own assets:

```
QGIS
  ↓
HydraShield Plugin
  ↓
HydraShield API  (https://hydrashield.earth/api)
  ↓
Climate Intelligence
  ↓
Evidence / Exposure / Economy / Solutions / Reports
```

The plugin is a **client**, not a port: all computation, data access and
provenance stay on the platform. The plugin adds QGIS-native affordances —
map-click analysis, "analyze the selected polygons", results as styled QGIS
layers, batch/modeler integration — that the website cannot offer.

The channel is also a conversion funnel: every analysis result is one click
away from "save & monitor this area", which is where accounts and
subscriptions begin (§10).

---

## 2. What the platform already offers a QGIS client

Verified against the deployed code (production-verified 2026-08-18). Base URL
`https://hydrashield.earth`. All public endpoints are GET, JSON, per-IP
rate-limited; all carry honest `unavailable` / `key_required` states instead
of fabricated data.

### 2.1 Endpoint matrix relevant to the plugin

| Plugin capability | Endpoint | Auth | Rate limit | Response format |
|---|---|---|---|---|
| Hazard registry | `GET /api/v2/hazards` | none | none | JSON descriptors: `id, name, tagline, enabled, analysis{available,reason}, events{…}, temporal_coverage, sources[{name,url}], provenance` |
| Layer declarations | `GET /api/v2/hazards/<id>` | none | none | descriptor + `map_layers` (LayerSpec: label, group, kind, endpoint template, legend, source, url, resolution, status, temporal) |
| Point analysis | `GET /api/v2/analyze?hazard&lat&lon&name` | none | 30/min/IP | `HazardAnalysis`: status, summary, `level{label,score,basis,validated}`, blocks, evidence, provenance |
| Historical events | `GET /api/v2/events?hazard&lat&lon&radius_km&year` | none | 10/min/IP | JSON records with `lat, lon, event_id, dates, severity, classification` |
| Fire-danger grid | `GET /api/risk-grid?south&west&north&east&n` | none | 10/min/IP | **GeoJSON FeatureCollection** of styled cell polygons (max 1.5° span, n 2–7) + provenance |
| Live risk snapshot | `GET /api/risk-snapshot` | none | 60/min/IP | Top-risk monitored areas ranking |
| Population / exposure | `GET /api/population-exposure?lat&lon&radius_km` | none | 20/min/IP | Cell rectangles `{s,w,n,e,population}` + per-hazard-class breakdown |
| Critical facilities | `GET /api/exposure-features?lat&lon&radius_m` | none | 20/min/IP | Point features `{lat,lon,category,name}` (hospitals, schools, …) |
| Active fires | `GET /api/fires?lat&lon&days&radius_km` | none | 20/min/IP | FIRMS detections per sensor (honest `unavailable` without server key) |
| Smoke corridors | `GET /api/smoke[-scenario]?lat&lon&…` | none | 20/min/IP | Corridor polygon vertex lists (observed vs MODELLED strictly separated) |
| Economic exposure | `GET /api/v2/economy?lat&lon&radius_km&hazard` | none | 20/min/IP | Structured exposure profile; monetary always honestly `not_quantified` |
| Solutions | `GET /api/v2/solutions?lat&lon&hazards=a,b` | none | 20/min/IP | Site-fitted solution options with limitations/maturity |
| Reports (PDF) | `GET /api/report?lat&lon&type=simple\|decision\|scientific` | none | 10/min/IP | `application/pdf` with content-hashed report ID |
| Register / login | `POST /api/v2/auth/register`, `POST /api/v2/auth/login` | none | 20/h, 30/15min per IP | Session token (Bearer) |
| Saved locations | `GET/POST/DELETE /api/v2/account/locations` | session | tier budget | JSON; 50-location cap with 403 upgrade descriptor |
| Alert rules (monitoring) | `GET/POST/DELETE /api/v2/alerts/rules` | session, `registered`+ | tier budget; caps 2/25/100 by tier | JSON rules: hazard + lat/lon + threshold |
| SMS pipeline | `POST /api/v2/alerts/phone[ /verify]`, `GET/PATCH /alerts/preferences`, `POST /alerts/unsubscribe` | session, `registered`+ | 10/h sensitive ops | verification code delivered only via SMS/outbox |
| Alert history | `GET /api/v2/alerts/history` | session | — | alert records + per-channel delivery states |
| API keys | `POST /api/v2/account/api-keys` | session, **`subscriber`** | — | `hs_…` key, plaintext shown once |
| Webhooks | `GET/POST/DELETE /api/v2/account/webhooks` | session, `registered`+ | — | signed outbound deliveries (`alert_fired`, `significant_change`) |

### 2.2 Platform facts that shape the design

- **Two credential types.** Session tokens (`Authorization: Bearer`,
  30-day TTL, full account access) and API keys (`X-API-Key: hs_…`,
  subscriber-issued, revocable, **read-only GET/HEAD/OPTIONS — the server
  answers 403 on mutations**). Passwords are never needed by any read
  endpoint. (`auth_api.py:81-129`, `accounts.py:466-545`)
- **Tiers (verbatim):** `anonymous, visitor, registered, subscriber,
  professional, business, municipality, government, admin`
  (`accounts.py:52-62`). Today only three hard gates exist in code: API-key
  creation (`subscriber`), benchmark runs (`admin`), and everything
  account-related (`registered`). Tier budgets for authenticated mutations:
  120/600/1200 req/min for registered/subscriber/business
  (`accounts.py:68-78`).
- **Insufficient tier → 403 with a machine-readable `upgrade` descriptor**
  (`{"required_role","your_role","unlocks"}`) — the plugin renders this as a
  native, honest upgrade prompt. (`auth_api.py:132-159`)
- **Provenance is first-class.** Every analysis carries per-component
  provenance `{kind, source, acquired, resolution, limitations}` and
  evidence records with controlled vocabularies (`OBSERVED/DOCUMENTED/
  REPORTED/MODELLED/INFERRED/UNKNOWN`; `OBSERVED/HISTORICAL/FORECAST/
  PROJECTED/SCENARIO`). The plugin must render these, not hide them.
- **No raster/tile service exists.** Spatial products are: GeoJSON grid
  polygons, point records, cell rectangles, corridor polygons, and the NDMI
  matrix + bounds inside `/api/analyze` (the web map rasterizes it
  client-side; the plugin will do the same into a QGIS raster/mesh).
  LayerSpecs of `kind:"raster"` without an endpoint are *declared, not
  wired* — the plugin must show them as such, exactly like the web map.
- **`standard_formats_api.py` is a non-deployed scaffold** returning sample
  data. Never integrate against it.
- **Rate limits are per-IP, in-memory per gunicorn worker** — effectively
  multiplied by worker count, but the plugin must treat the documented
  per-IP numbers as the contract and cache aggressively (§8).
- **CORS is irrelevant** (non-browser client); no CORS preflight concerns.

---

## 3. Ecosystem scan — what already exists (duplication check)

Searched plugins.qgis.org (2026-08): climate (39 hits), flood (62), hazard
(22), fire (21), heat (20), weather (17), drought (7), wildfire (5),
Open-Meteo (3).

**Closest neighbours — neither duplicates HydraShield:**

- *"Physical climate risk assessment for GIS features"* (2026-06, 0 votes) —
  aggregates ThinkHazard/WRI Aqueduct/NASA public indices for ESG reporting.
  Closest analogue; not a multi-hazard analysis engine with evidence,
  economy, solutions, reports and alerting.
- *"External wildfire risk analysis for urbanizations (FIRE-SCENE Pilot 1)"*
  (2026-07, experimental, 0 votes) — single-hazard regional pilot.

**By domain:** wildfire plugins are FIRMS/burn-severity data viewers; flood
is hydraulic modelling prep (TUFLOW/HEC-RAS ecosystems) and national WMS
catalogs; drought/heat are index calculators (SPI, UTCI) or GEE fetchers;
climate plugins download point time series (NASA POWER, Open-Meteo) without
hazard scoring, exposure, or economics. **InaSAFE** does local deterministic
impact scenarios (humanitarian). Nothing offers multi-hazard point/polygon
analysis via an external API with accounts and progressive subscription
gating. **No alerting/monitoring-as-a-service plugin exists at all.**

Commercial-SaaS precedents in the official repo (relevant for §12):
Planet Explorer, Sentinel Hub, Google Earth Engine, MapTiler — all require
external accounts and are published without issue.

Conclusion: a HydraShield plugin fills an empty niche. Per repo rules, the
submission should proactively name the two closest neighbours above and
state the difference.

---

## 4. Product concept — plugin capabilities

Every requested capability maps to an existing, deployed endpoint:

| User action in QGIS | Backing endpoint(s) | Tier needed |
|---|---|---|
| Analyze a clicked point | `/api/v2/analyze` | anonymous |
| Analyze a selected polygon | §5.4 (client-side point strategy today; platform polygon endpoint = roadmap) | anonymous |
| Analyze a whole selected layer | Processing batch over features (§5.3) | anonymous (rate-limited); practical volumes → subscriber |
| Select hazards | `/api/v2/hazards` registry (never hardcoded) | anonymous |
| Current hazard intelligence | `/api/v2/analyze`, `/api/risk-grid`, `/api/risk-snapshot` | anonymous |
| Historical events | `/api/v2/events` (year selector from `temporal_coverage`) | anonymous |
| Add HydraShield map layers | LayerSpec endpoints: risk-grid GeoJSON, events points, fires, exposure features, population cells, smoke corridors, NDMI grid | anonymous |
| Inspect provenance | provenance/evidence blocks rendered in the dock + layer metadata | anonymous |
| Population / exposure | `/api/population-exposure`, `/api/exposure-features`, `/api/exposure-summary` | anonymous |
| Economic exposure | `/api/v2/economy` | anonymous |
| Request solutions | `/api/v2/solutions` | anonymous |
| Generate reports | `/api/report` (PDF, three types) | anonymous today |
| Save a location | `POST /api/v2/account/locations` | **registered** |
| Monitor a location | `POST /api/v2/alerts/rules` | **registered** (2-rule cap) → **subscriber** (25) |
| Subscribe to alerts (SMS/email) | `/api/v2/alerts/*` phone verification, preferences | **registered**; serious use → **subscriber** |
| Team/API usage | `X-API-Key` + webhooks | **business/government** |

The free tier is genuinely useful: full six-hazard analysis, events, layers,
provenance, economy, solutions and even PDF reports work anonymously, bounded
only by per-IP rate limits. Gating appears exactly at persistence and
monitoring — the moments of added value.

---

## 5. Architecture evaluation

### 5.1 Option A — classic QGIS Python plugin (dock + map tools)

A dock widget browsing the hazard registry, a `QgsMapToolEmitPoint` for
click-to-analyze, and layer tools. Strengths: best UX for interactive
exploration, provenance browsing, account flows. Weaknesses alone: no
modeler/batch composition — "analyze this layer of 400 assets" would be a
custom loop.

### 5.2 Option B — QGIS Processing provider

`hasProcessingProvider=yes`; algorithms such as `hydrashield:analyze_point`,
`analyze_features`, `events_near_point`, `risk_grid_for_extent`. Inputs are
feature sources/extents; outputs are feature sinks → real QGIS layers.
Strengths: batch processing, Graphical Modeler composition, background
execution via `QgsProcessingAlgRunnerTask`, and the official repository
explicitly recommends Processing sub-plugins. Weaknesses alone: poor surface
for browsing provenance, managing account/session, and conversational
upgrade prompts.

### 5.3 Recommendation — one plugin, Processing-first with a thin dock

A single plugin package (`hydrashield`) that registers **both**:

1. **Processing provider** (the engine): every analysis capability as an
   algorithm. "Analyze selected layer" is then free — QGIS runs the
   feature-source algorithm over selected features in batch, with progress,
   cancellation, and per-feature output rows. This is the plugin's
   technical core and its unique value vs. the website.
2. **Dock widget + map tool** (the funnel): hazard browser with availability
   states, click-to-analyze, provenance/evidence inspector, layer toggles
   mirroring the web map, and the account/upgrade surfaces (§10).

Results are added as **memory/scratch layers** (never written into the
user's data), styled from the LayerSpec legends (e.g. risk classes
Low `#22c55e` … Extreme `#ef4444`), with provenance copied into layer
metadata/abstract so it survives project saves.

### 5.4 Polygon honesty note (design constraint)

The platform API analyzes **points** today. For "analyze this polygon" the
plugin must not fake area statistics. Phase-1 behavior: evaluate the
polygon's representative point (labelpt), clearly labelled *"representative
point of <feature>"*, plus optional multi-point sampling via the batch
algorithm (one API call per sample point, rate-limit bounded). A real
polygon/area endpoint is a **platform-side roadmap item**; the plugin UI
must say so instead of implying area statistics exist.

---

## 6. Technical approach

- **Language/runtime:** Python, PyQGIS API only. **Zero third-party pip
  dependencies** (repo rules: no binaries, dependencies must be declared and
  user-installed — avoided entirely). HTTP via `QgsNetworkAccessManager`
  (`blockingGet/blockingPost` inside worker threads) so QGIS proxy, SSL and
  auth settings apply — the repo's explicit recommendation over
  requests/urllib.
- **Threading:** all network calls inside `QgsTask` /
  `QgsProcessingAlgRunnerTask`; never on the GUI thread; layer/project
  mutation only in `finished()` (main thread); `context.takeResultLayer()`
  before adding processing outputs to the project.
- **CRS:** geometries transformed to EPSG:4326 client-side
  (`QgsCoordinateTransform`) before any API call; outputs created in the
  calling layer's CRS.
- **Client identity:** `User-Agent: hydrashield-qgis/<version>
  (+https://hydrashield.earth)` — mirrors the Python SDK convention.
- **Error model:** platform `{"error","status"}` bodies, honest
  `unavailable`/`key_required` payloads, and 403 `upgrade` descriptors map
  to distinct plugin UI states — never generic failure dialogs.
- **Configuration:** `QgsSettings` for base URL (default
  `https://hydrashield.earth`), last-used hazard, and the **authcfg ID** —
  nothing else sensitive.

## 7. Authentication & token security

Requirement: *the plugin never stores passwords or API secrets in project
files.* Design:

- **QgsAuthManager is the only credential store.** The HydraShield token
  (API key, or session token for account operations) lives as an
  authentication configuration (APIHeader/Basic method) in the encrypted
  `qgis-auth.db`, protected by the user's QGIS master password (optionally
  OS keychain-integrated). The plugin and `.qgz` projects reference only the
  7-character **authcfg ID** — designed by QGIS exactly for this.
- **Credential entry:** the dock embeds `QgsAuthConfigSelect` (the official
  selector). A "Create key" button deep-links to the HydraShield account
  page; the user pastes the `hs_…` key once into the auth config. The
  plugin never sees or stores a password; registration happens on the
  website (GDPR-cleaner, §13).
- **Platform-side work item (phase 2):** today's API keys are read-only
  (GET-only). "Save location / monitor / alert rules" from the plugin need
  either a session token (30-day TTL, re-login monthly — poor UX) or, the
  recommended path, **scoped API keys** (e.g. `scope=account:write`)
  issued at subscriber/business tier. This is a small, additive platform
  change in `auth_api.py`/`accounts.py` and is listed in the phased plan —
  until it lands, the plugin's account actions use a login dialog that
  stores only the resulting *session token* in QgsAuthManager (never the
  password) and handle 401 expiry by prompting re-login.
- **Sharing safety:** a `.qgz` shared with a colleague carries only the
  authcfg ID; their own QGIS must hold their own config. No credential can
  leak through project files, expressions, or layer metadata (provenance
  blocks contain sources, never headers).

## 8. Caching, rate limits, offline behavior

- **Client-side cache** (SQLite in the plugin profile dir, keyed by
  endpoint+params): respect server TTL signals — risk-grid is server-cached
  1 h, point analysis 15 min, the risk snapshot 30 min (`cache.py`,
  `grid.py`). Default client TTLs: registry 24 h, analysis 15 min,
  events 1 h, grids 1 h. A "refresh" action always forces re-fetch.
  Cache is honest: entries display their acquisition timestamp.
- **Rate-limit discipline:** per-IP budgets (§2.1) are the contract; the
  batch algorithm enforces client-side throttling (max in-flight tasks,
  progressive backoff on 429 with `feedback`-visible messaging) and a
  per-run cap for anonymous users (e.g. 25 features) with the honest
  message "larger batches need an API key" — conversion through value at
  the exact moment of need.
- **Offline behavior:** no connectivity → the plugin works as a *viewer of
  cached results* (layers already in the project keep their data and
  provenance; the dock shows last-fetch timestamps and an explicit offline
  state). Nothing is fabricated, extrapolated, or hidden.

## 9. Provenance & the honesty contract in QGIS

The platform's evidence discipline must survive into QGIS visibly:

- Every generated layer gets `metadata.abstract` populated with source,
  acquisition time, resolution, temporal class and limitations; styles come
  from the LayerSpec legend.
- The dock's provenance inspector renders the evidence records
  (`OBSERVED/DOCUMENTED/MODELLED/…` chips, provider links) for the selected
  analysis — parity with the website.
- `key_required` / `unavailable` layers are addable but render the honest
  state banner (like map.js), never silently empty.
- Screening-indicator labelling ("not a validated predictor") appears on
  every level display and in every exported layout template the plugin
  ships.

## 10. User journeys & conversion paths

Progressive value; no aggressive blocking. The canonical funnel:

1. **Anonymous — discover.** Install from the official repo → click a point
   → full real analysis with level, evidence, provenance. Add the
   fire-danger grid for the current extent. Download a PDF report.
   *Value first, no account wall.*
2. **The save moment.** "Save & monitor this area" on any result →
   explains: free account keeps locations, history, and 2 alert rules →
   register on hydrashield.earth → paste API token into the QGIS auth
   config (once). *Account created at the moment of intent.*
3. **The monitoring moment.** A saved area shows "Enable SMS alerts" →
   phone verification flow → rule created. Hitting the 2-rule cap shows the
   platform's own 403 `upgrade` descriptor → *subscriber* (25 rules, SMS +
   email, alert history).
4. **The professional moment.** Batch analysis of an asset layer beyond the
   anonymous cap, API key for scripts, full scientific reports →
   *professional/subscriber*.
5. **The organization moment.** Multiple recipients, team seats, webhooks
   into municipal systems, many monitored areas → *business/government*.

Every gated UI state is rendered from the server's 403 upgrade descriptor —
the plugin never invents its own pricing or entitlement claims.

## 11. Monetization mapping (plugin view)

| Tier | In the plugin |
|---|---|
| Free / anonymous | Point & polygon-preview analysis, all six hazards, map layers, events, provenance, economy, solutions, PDF reports — per-IP rate limits and batch cap (25 features/run) |
| Registered (free account) | Save locations, analysis history, 2 alert rules (email/SMS after phone verification), token in auth manager |
| Professional / subscriber | 25 alert rules, SMS + email, alert history in-plugin, API key (scripts + higher batch practicality), all report types with delivery |
| Business / Government | 100 rules, multiple recipients & seats, webhooks, API-first usage, monitoring dashboards (web), priority data roadmaps |

No pricing is hardcoded anywhere — the plugin displays only what the server
returns. Billing itself stays on the website (payment provider is a separate
roadmap item).

## 12. Licensing implications

- **QGIS is GPLv2+; the official repository requires plugin code to be
  GPL-compatible and source-available.** The HydraShield plugin will be
  **GPLv2+**, developed in a public repo (a `qgis-plugin/` directory in the
  main repo or a sibling repo), with a plain-text LICENSE file in the
  package.
- **The backend stays proprietary — this is established practice.** The GPL
  obligation attaches to the plugin's code, not the remote service.
  Precedents published in the official repo: Planet Explorer, Sentinel Hub
  (requires a Copernicus Data Space or Sentinel Hub account), Google Earth
  Engine, MapTiler. Repo rules only require that account/subscription needs are
  **disclosed in the plugin description** — ours will state: *"Core analysis
  works without an account; saving locations, monitoring and SMS alerts
  require a free HydraShield account; higher limits require a
  subscription."*
- **Dependency policy:** stdlib + PyQGIS only → no third-party license
  conflicts, no binaries, package far under the 20 MB limit.
- HydraShield *data* provenance includes per-dataset licenses (e.g.
  Copernicus, ESA WorldCover, OSM/ODbL) — the provenance inspector surfaces
  them; the plugin adds no data of its own.

## 13. GDPR & privacy

- The plugin sends **coordinates and hazard choices** to the API — the
  minimum necessary; no project contents, file paths, or layer names leave
  the machine (place names are resolved server-side only when the user
  types them).
- **No telemetry, no analytics, no phone-home** beyond the API calls the
  user explicitly triggers. (Also the safest reading of the repository's
  2026 security direction — see §17 risks.)
- Account creation and email/phone data entry happen **on the website**,
  under the existing consent texts (GDPR-compliant registration already
  shipped); the plugin stores only the resulting token in QgsAuthManager.
- Alert rules/saved locations are account data server-side, deletable via
  the existing account endpoints (and the account page); the plugin exposes
  the same delete actions.
- The plugin's metadata and description disclose the data flow plainly.

## 14. Official QGIS Plugin Repository — compliance checklist

From the plugins.qgis.org publish rules, the 2016 licensing post, the
QGIS 4.0-era repository changes (QEP 409 + Plugins Website v4.0.0), all
verified against the live pages on 2026-08-18:

**Hard requirements (publish page):**

- [ ] OSGEO ID account for uploads
- [ ] `metadata.txt`: name (no "plugin" in it), `qgisMinimumVersion=3.40`,
      `hasProcessingProvider=yes`, working homepage/tracker/repository/
      license links (the homepage may be the repo README), `about`
      disclosing the account/subscription requirement, `changelog` per
      release
- [ ] License **compatible with GPLv2 or later**; plain-text LICENSE file;
      public source repo whose code is identical to the uploaded zip
      (source in repo form, not a zip)
- [ ] No binaries (binary-requiring plugins are rejected absent a PSC
      exception); package ≤ 20 MB
- [ ] External dependencies declared in `about` — we have none (stdlib +
      PyQGIS only)
- [ ] Cross-platform (Windows/macOS/Linux); reviewers randomly smoke-test
      installability

**Security scanning (QEP 409, merged 2026-02-17; blog announcement
2026-04-23):** every uploaded version is scanned, and **critical findings
block download and approval**:

- [ ] **Bandit** — no critical findings: verified TLS only (no
      `verify=False` / unverified SSL contexts), no `exec`/`eval`/pickle/
      `shell=True`, no hardcoded passwords (B105–B107). Our design
      (QgsNetworkAccessManager + QgsAuthManager, no embedded secrets)
      passes by construction; a token must never ship in code or metadata
- [ ] **detect-secrets** — no secrets in the package
- [ ] Non-blocking advisories (flake8, file permissions, suspicious files,
      "request without timeout", urllib usage) show as badges — set
      explicit timeouts everywhere; bundling `.bandit` /
      `.secrets.baseline` / `.flake8` configs marks the version
      "Validated (configured)"

**Plugins Website v4.0.0 (shipped July 2026):**

- [ ] **Verified maintainer contact email is a hard approval requirement**,
      re-verified yearly (unmaintained plugins face eventual
      unpublication)
- [ ] Standard authors get **manual review for every new version**
      (auto-approval is reserved for users with explicit approval
      permission — "trust people, not plugins")
- [ ] Async **Qt6 compatibility check** runs per upload (results tab) —
      our dual Qt5/Qt6 shims keep this clean
- [ ] Experimental flag for the first releases; approvals ~daily except
      weekends
- [ ] Pre-emptively address duplication vs. the two §3 neighbours in the
      submission notes

Sources: plugins.qgis.org/publish · blog.qgis.org 2016-05-29 licensing
post · QEP 409 (`qep-409-plugins-security-validator.md`) ·
plugins.qgis.org/docs/security-scanning · blog.qgis.org 2026-04-23 and
2026-07-06 posts.

## 15. Cross-platform support

- **Baseline: QGIS 3.40 LTR** (`qgisMinimumVersion=3.40`) — the last 3.x LTR
  line, Python 3.12 on Windows/OSGeo4W.
- **QGIS 4.x (Qt6) compatibility** must be designed in from day one:
  PyQt5/PyQt6 shims (`qgis.PyQt` abstraction), no Qt5-only APIs; CI tests
  against both 3.40 and the current 4.x. (Published plugins already span
  3.22–4.99 with one codebase.)
- OS targets: Windows (OSGeo4W), macOS (dmg bundle), Linux (distro Python).
  No platform-specific code paths expected — all I/O is HTTP + QGIS API.
- Distribution/update: official repo via Plugin Manager; packaging/release
  automation with `qgis-plugin-ci`.

## 16. Phased implementation plan

**Phase 0 — validation (½ week).** Confirm the current LTR designation on
qgis.org (the roadmap page is JS-rendered; at research time 3.40 is the
last 3.x LTR line and 4.2 the current release); register the OSGEO ID and
verify the maintainer contact email (hard approval requirement); spike a
minimal plugin calling `/api/v2/hazards` + one `QgsTask`-based analysis
call inside QGIS 3.40 and 4.x; confirm the QgsAuthManager APIHeader flow
end-to-end; run Bandit + detect-secrets locally on the spike so the
first upload passes the QEP-409 blocking scans.

**Phase 1 — anonymous MVP (2–3 weeks).** Processing provider with
`analyze_point`, `analyze_features` (batch, capped, throttled),
`events_near_point`, `risk_grid_for_extent`; dock with hazard browser,
click-to-analyze, provenance inspector, honest unavailable states; memory
layers + LayerSpec styling; client cache; User-Agent; offline viewer mode.
Submit to the official repo as *experimental*. **No account features yet —
the funnel starts working only if the free core is excellent.**

**Phase 2 — accounts (2 weeks).** Token-in-auth-manager onboarding;
save-location and monitor flows against `account/locations` and
`alerts/rules`; 403-upgrade rendering; **platform-side scoped API keys**
(`account:write`) so desktop flows don't depend on 30-day sessions; alert
history view.

**Phase 3 — monitoring & SMS conversion (1–2 weeks).** Phone verification
guidance (deep-link + in-plugin status), preferences (quiet hours,
thresholds), unsubscribe — all against the deployed `/api/v2/alerts/*`;
subscription upgrade paths from cap hits.

**Phase 4 — business/government (2 weeks).** Webhook management UI,
multi-recipient guidance, batch cap policies per tier, organization
messaging; evaluation of a platform-side polygon-analysis endpoint (removes
the §5.4 constraint properly).

**Phase 5 — polish & promotion.** Translations (EN/FR/DE/ES matching the
platform), layout/report templates with provenance blocks, screencasts,
QGIS Hub/community presence, stable (non-experimental) release.

## 17. Risks & open questions

- **Repository security scanning is now a hard gate, verified (QEP 409 +
  Plugins Website v4.0.0):** Bandit + detect-secrets block approval on
  critical findings; a verified maintainer email (yearly re-verification)
  and per-version manual review for standard authors apply. The plugin's
  design (zero dependencies, QgsNetworkAccessManager with verified TLS,
  no embedded secrets, no telemetry) passes by construction; residual
  risks are rule-set churn (admin-tunable) and advisory-badge noise
  (e.g. timeout/urllib warnings) — mitigated by bundled linter configs
  and explicit timeouts.
- **API keys confer no higher public rate budget today** (per-IP limiting
  applies to everyone). If professional batch usage becomes a selling
  point, the platform should key public budgets to the API key, not only
  the IP — a deliberate platform decision, noted for the roadmap.
- **Rate limiter is per-worker in-memory** — documented per-IP numbers are
  the honest contract; the plugin's throttling assumes them.
- **Polygon/area analysis** is point-based today (§5.4); the plugin labels
  this honestly until a platform endpoint exists.
- **No raster services** — NDMI grid rasterization is client-side; if heavy
  raster demand emerges, a COG/WMS endpoint is a platform roadmap item.
- **Session-token UX** for account writes until scoped keys land (§7) —
  acceptable interim, must be clearly messaged.
- **LTR transition (3.40 → 4.x)** timing affects the support matrix (the
  qgis.org roadmap page is JS-rendered and could not be machine-verified;
  3.40 is the last 3.x LTR line, 4.2 the current release at research
  date); dual-version CI from day one mitigates.

## 18. Appendix — design invariants

1. The plugin is a client: no hazard math, no data fabrication, no cached
   "fake offline" results.
2. Provenance travels with every layer and every dialog.
3. Credentials only in QgsAuthManager; projects carry only authcfg IDs.
4. Free tier is genuinely useful; gates appear at persistence/monitoring.
5. Every entitlement statement comes from the server's upgrade descriptors.
6. Zero third-party dependencies; `QgsNetworkAccessManager` + `QgsTask`.
7. GPL plugin, proprietary backend, disclosed account requirements.
8. Honest states everywhere: `unavailable`, `key_required`, offline,
   rate-limited — shown, never hidden.
