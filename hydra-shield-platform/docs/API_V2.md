# HydraShield Public API — v2 Contract

**Base URL:** `https://hydrashield.earth`
**Status:** stable contract. Additive changes only; a breaking change ships
as `/api/v3`. Deprecations are announced in responses (`sunset` header) two
minor versions ahead.

This document is the normative reference for the public REST surface. It
describes only what the code does today
(`src/climate/api_v2.py`, `src/dashboard/api.py`, `src/dashboard/auth_api.py`,
`src/dashboard/sms_api.py`). Example payloads below are **illustrative
shapes** (field names are real; values are placeholders, never real
measurements).

---

## 1. Conventions

### Requests

- All endpoints are **GET** unless marked **POST / PATCH / DELETE**.
- Query parameters are URL-encoded; POST/PATCH bodies are JSON
  (`Content-Type: application/json`).
- Coordinates: `lat` in `[-90, 90]`, `lon` in `[-180, 180]` (WGS-84).
  Out-of-range or non-numeric values → `400`.

### Responses

- Success: HTTP 2xx with a JSON object. Top-level keys are stable per
  endpoint; new fields may be added at any time (additive).
- Analysis responses carry provenance per component and, where applicable,
  `generated_at` / content hashes so integrators can cache and verify.
- PDF: `GET /api/report` returns `application/pdf` (not JSON).

### Errors

Every non-2xx response is stable JSON:

```json
{"error": "lat and lon must be numbers", "status": 400}
```

| Status | Meaning |
|---|---|
| 400 | Invalid parameters (the `error` string says which) |
| 401 | Authentication required / invalid credentials |
| 403 | Authenticated but insufficient tier — body includes an `upgrade` descriptor `{"required_role", "your_role", "unlocks"}` |
| 404 | Unknown resource (hazard, event, location…) |
| 429 | Rate limit exceeded |
| 502 | Upstream data source failed |
| 503 | Capability unavailable — see *Honest unavailability* |

SDKs rely on this shape and raise it as an exception.

### Honest unavailability

When a real data source cannot be obtained, endpoints do **not** fabricate
values. Two forms:

1. HTTP 503 with an explicit payload, e.g.
   `{"hazard": "wildfire", "status": "unavailable", "unavailable_reason": "…"}`.
2. HTTP 200 where a component block reports `status: "unavailable"` (or
   `"key_required"`) with a reason, while the rest of the response is real.

Callers must render these states as-is. SDKs return them as **data**, never
as exceptions (only true errors — `{"error", "status"}` bodies — raise).

### Rate limits

Per client IP (first `X-Forwarded-For` hop), sliding window. Budgets are
listed per endpoint below. Authenticated mutating endpoints additionally
apply **per-user, per-tier budgets** (`accounts.TIER_RATE_LIMITS`, requests
per minute: registered 120 · subscriber/professional 600 ·
business/municipality/government 1200).

### Authentication

- **Public GET endpoints:** none.
- **Account / alert endpoints:** one of
  - `Authorization: Bearer <session token>` — from `POST /api/v2/auth/login`
    or `GET /api/v2/auth/verify` (API clients; takes precedence);
  - `hydrashield_session` HttpOnly cookie — set by the website on
    login/verify (`SameSite=Lax`; browsers rely on that for CSRF).
- **`X-API-Key` (read-only, subscriber-issued):** the SDKs already send this
  header when configured. Keys authenticate `GET` requests as their owner
  (see §7 for the live management endpoints).

### Honesty and label discipline

Every claim in every response carries labels from the platform vocabulary
(`src/climate/ontology.py`):

- **Claim status:** `OBSERVED | DOCUMENTED | REPORTED | MODELLED | INFERRED | UNKNOWN`
- **Temporal class:** `OBSERVED | HISTORICAL | FORECAST | PROJECTED | SCENARIO`

Forecasts/projections are labelled and never blended into observations.
Scores/levels are screening indicators unless their block says otherwise
(`validated: true`). Cause is DOCUMENTED or UNKNOWN — never inferred.

### CORS

Read-only public GET endpoints may be exposed to configured origins via the
`HYDRASHIELD_CORS_ORIGINS` environment variable: **exact origins** (no
wildcards, never `*` with credentials), GET-only. Default: same-origin only
(no CORS headers emitted). *(Server-side CORS header emission is being wired
alongside the embeddable component; the policy above is the contract.)*

---

## 2. Public multi-hazard endpoints (`/api/v2`)

Registered hazard ids today: `wildfire`, `flood`, `drought`, `heat`,
`wind`, `coastal`. A hazard is registered only when wired to a real,
documented data source — there are no placeholders.

### `GET /api/v2/hazards`

The hazard registry. No rate limit.

```json
{
  "hazards": [
    {
      "id": "wildfire",
      "name": "Wildfire",
      "tagline": "…",
      "enabled": true,
      "analysis": {"available": true, "reason": null},
      "events": {"available": false, "reason": "NASA FIRMS key … not configured"},
      "temporal_coverage": {"<dataset>": {"start": "2012", "end": "present"}},
      "sources": [{"name": "NASA FIRMS (VIIRS/MODIS), …",
                   "url": "https://firms.modaps.eosdis.nasa.gov/"}],
      "provenance": {"module": "src.climate.hazards.wildfire.WildfireModule",
                     "sources_declared_by": "…",
                     "indicator_status": "…"}
    }
  ],
  "note": "A hazard is registered only when backed by a real, documented data source…"
}
```

`temporal_coverage` is per-dataset and drives year selection — years are
never hardcoded. `enabled` is the registry state (a registered hazard is
enabled by definition); per-capability runtime state lives under
`analysis`/`events`. `sources` lists the official datasets behind the
hazard (name + URL, de-duplicated from the same declarations the map layer
panel shows); `provenance` states where the descriptor comes from and the
screening-indicator status of the levels.

### `GET /api/v2/hazards/<hazard_id>`

One hazard descriptor plus its `map_layers` list (each layer:
`layer_id`, `label`, `group`, `kind`, `endpoint`, `legend`, `source`,
`url`, `date`, `resolution`, `status` (`available | key_required |
unavailable`), `temporal`, `default_on`, `provenance`).
404 for an unknown id.

### `GET /api/v2/analyze`

Per-hazard analysis. **Rate limit: 30/min.**

| Param | Required | Notes |
|---|---|---|
| `hazard` | no | default `wildfire`; must be a registered id (404 otherwise) |
| `lat`, `lon` | yes | point to analyse |
| `name` | no | display name echoed in the result |
| `raw` | no | `raw=1` includes the engine-native payload (`raw` key; wildfire compatibility) |

Response (`HazardAnalysis.to_dict`):

```json
{
  "hazard": "wildfire",
  "location": {"lat": 0.0, "lon": 0.0, "name": "…"},
  "status": "ok | partial | unavailable | key_required",
  "summary": "…",
  "level": {"label": "High", "score": 0.0, "score_max": 100.0,
            "basis": "…", "validated": false},
  "blocks": {"<hazard-specific>": {}},
  "evidence": [ {"<EvidenceRecord fields>": "…"} ],
  "provenance": {"<component>": {"kind": "…", "source": "…"}},
  "unavailable_reason": null
}
```

- `level.score` may be `null` when severity is categorical; `level.basis`
  always states what the level rests on and whether it is validated.
- 503 (not an exception, a state) when the hazard is globally unavailable:
  `{"hazard", "status": "unavailable", "unavailable_reason"}`.

### `GET /api/v2/events`

Historical events around a point. **Rate limit: 10/min.**

| Param | Required | Notes |
|---|---|---|
| `hazard` | no | default `wildfire` |
| `lat`, `lon` | yes | |
| `radius_km` | no | default `50` |
| `year` | no | integer; any year — out-of-coverage years are answered with the dataset's stated coverage, not an error |

Response is the hazard module's event payload: a list of derived event
records (each with an `id`, observed conditions kept separate from modelled
context, and per-event evidence). When the underlying dataset needs a
credential (wildfire: `FIRMS_MAP_KEY`) the payload states
`status: "key_required"` / `"unavailable"` with the reason — no invented
events.

### `GET /api/v2/events/<event_id>`

One stored event with its full evidence list ("show me the evidence").
Events are persisted server-side when derived via `GET /api/v2/events`.
404 when the id is not stored.

### `GET /api/v2/economy`

Economic exposure profile. **Rate limit: 20/min.**

| Param | Required | Notes |
|---|---|---|
| `lat`, `lon` | yes | |
| `radius_km` | no | default `5` |
| `hazard` | no | attaches that hazard's current level as `hazard_context` (failures are reported in the context block, never fatal) |

Structured exposure categories from real mapped data (OSM / WorldCover).
Monetary quantification is always `not_quantified` — no documented
valuation dataset is integrated, and none is invented.

### `GET /api/v2/solutions`

Site-fitted sustainable solutions. **Rate limit: 20/min.**

| Param | Required | Notes |
|---|---|---|
| `lat`, `lon` | yes | |
| `hazards` | no | comma-separated registered ids (e.g. `wildfire,drought`) — declared as *caller-selected* hazards of interest (basis says so); unknown ids are listed under `unknown_hazards_requested` |

The site context is assembled from light cached fetchers only (terrain,
land cover, OSM counts, recent weather); hazard levels are **not** computed
on this endpoint (use `/api/v2/analyze` per hazard). Without `hazards=`,
the response is the honest insufficient-data path (`insufficient_data`
states what is missing).

### `GET /api/v2/sources`

The data-source audit registry (`config/source_registry.json`): every
evaluated source with purpose, coverage, resolution, freshness, license,
kind, limitations and integration status (`integrated | candidate |
rejected`). 503 if the registry cannot be read. Identical content to
`GET /api/sources`.

### `GET /api/v2/registry` · `GET /api/v2/registry/<dataset_id>`

The **Data Observatory** (`config/data_registry.json`): fuller dataset
records — provider, provider_class, url, license, geographic/temporal
coverage, spatial/temporal resolution, update frequency, variables,
hazard relevance, provenance, quality, access method, api/download URL,
commercial-use constraints, status (`integrated | candidate | rejected`)
+ status note. Filters: `?status=`, `?hazard=`, `?provider_class=`
(400 on bad vocabulary). A catalog record never implies the data is wired
into analysis unless `status=integrated` (see `observatory_note` in the
response). 60/min.

### `GET /api/v2/models` · `GET /api/v2/models/<model_id>`

The **Model Registry** (`config/model_registry.json`): immutable records
of HydraShield proprietary indicators — version, methodology, scientific
basis (`research_ids`), inputs, outputs, validation datasets + status
(`not_validated | validation_in_progress | validated_screening |
validated_operational | deprecated`), geographic applicability,
uncertainty, limitations. 404 for unknown ids. 60/min.

### `GET /api/v2/research` · `GET /api/v2/research/<ref_id>`

The **Research Registry** (`config/research_registry.json`): scientific
foundations with authors/year/venue/DOI-or-official-URL, method, region,
limitations and pipeline stage (`paper | method | prototype | benchmark |
validation | production`). Filters: `?topic=`, `?pipeline_stage=`.
A paper never becomes production logic directly. 60/min.

### `GET /api/v2/ingestion/chains`

Multi-provider ingestion architecture: per-variable provider chains
(primary + fallbacks, never-merge notes) and declared single-provider
gaps (currently: river discharge, soil moisture). 60/min.

### `GET /api/v2/compound?lat&lon`

**Compound Risk Engine v1** — qualitative interacting-hazard detection at
a point (10/min). Real per-hazard signals (drought/heat/wind/flood + a
declared screening fire-danger signal from ERA5+FWI) classified per the
Zscheischler (2020) typology: `multivariate` (≥2 hazards simultaneously
elevated), `temporally_compounding` (spell following spell within 90
days), `preconditioned` (antecedent deficit amplifying a current hazard,
INFERRED), `spatially_compounding` (always `not_computable` at point
scale). Response: `compound_signals` (real values + evidence per signal),
honest `no_compound_signal` empty state, `hazards_unavailable`, and an
`uncertainty_envelope`. **No numeric compound score exists.**

### `GET /api/v2/cascading?lat&lon`

**Cascading Risk Graph v1** — structural relevance of cascade paths
(10/min): curated hazard→system→system graph (`config/cascading_graph.json`)
filtered to paths whose hazard is currently elevated AND whose system
nodes have real mapped anchors (OSM/exposure counts). Carries the exact
statement: "Propagation likelihoods and losses are NOT quantified — this
is a structural relevance graph, not a loss model." Honest
`no_active_hazards` / `insufficient_exposure` / `no_anchored_paths` states.

### `GET /api/v2/economic-impact?lat&lon`

**Economic Impact Engine v1** — three strictly separated blocks (10/min):
`observed_losses` (always `unavailable` — no documented loss figures in
integrated sources), `modelled_estimates` (exposure-bounded qualitative
profile; monetary values `not_quantified`), `projections` (always
`not_available`). `confidence: low` throughout.

### `GET /api/v2/ground-truth` · `GET /api/v2/ground-truth/<event_id>`

**Ground Truth Event Registry** — authoritative documented historical
hazard events (e.g. July 2022 UK heatwave, July 2021 Ahr flood, Storm
Eunice, 2022 Iberian drought) with official sources and a declared
expected-signal definition per event. `signal_basis` distinguishes the
DOCUMENTED occurrence from the OBSERVED/MODELLED signal in our datasets.
Wildfire event family: `key_required` (FIRMS). `?hazard=` filter. 20/min.

### `GET /api/v2/benchmarks` · `POST /api/v2/benchmarks/run`

The **HydraShield Benchmark Suite** — the suite definition (reproducible
cases, one per ground-truth event) plus the latest execution summary when
present. `passed` means the detector reproduced the expected REAL signal
in the declared window — detection reproduction, **not** a skill score or
a validation claim. `POST /run` executes the suite live (admin role;
compute-intensive; network-bound). 20/min.

### `GET /api/v2/evaluations` · `GET /api/v2/evaluations/<run_id>`

Immutable evaluation-run records (content-hashed, append-only):
`?model_id=` filter. Kinds: `equation_reference` (e.g. the FWI adapter's
cffdrs verification), `benchmark_suite`, `validation_pipeline`. Runs are
recorded only when actually executed — a run is never fabricated.
Model lifecycle states: `experimental → screening → backtested →
validated → operational → deprecated` (in `model_registry.json`). 20/min.

### `GET /api/v2/source-health` (`?dataset_id=`)

Source Intelligence: latest reachability/latency/status-change records
per integrated dataset, from the periodic checker
(`scripts/check_source_health.py`, 30-min loop). Honest empty state
before the first run. 60/min.

### `GET /api/v2/analysis-runs` · `GET /api/v2/analysis-runs/<analysis_id>`

Reproducible analysis-run records: every `/api/v2/analyze` call is
recorded with analysis ID (content hash, volatile timestamps excluded),
dataset versions, model versions, parameters, methodology, execution
timestamp, result hash, uncertainty and evidence. `?hazard=` filter.
20/min.

### `GET /api/v2/losses` · `GET /api/v2/losses/sources`

**Loss Data Registry** — observed/estimated/modelled/projected losses
strictly separated. `observed_losses` is exactly "No documented loss
figures in integrated sources." until a documented loss dataset is
integrated; `/sources` lists reviewed candidates (EM-DAT, UNDRR
DesInventar, World Bank/GFDRR, NOAA Billion-Dollar Disasters, Munich Re,
Swiss Re) with access/license notes. 20/min.

---

## 3. Public v1 endpoints (`/api`, unchanged)

These contracts predate v2 and are kept stable. All GET.

| Endpoint | Rate limit | Description |
|---|---|---|
| `/api/health` | none | `{"status": "ok|degraded", "timestamp", "cache", "firms_configured", "version"}` |
| `/api/status` | none | service status, module list, data policy |
| `/api/analyze` | 30/min | Full wildfire analysis. `?location=…` (Nominatim geocoding, recorded in provenance) **or** `?lat=&lon=`. Cached, provenance-annotated |
| `/api/risk-grid` | 10/min | n×n fire-danger grid over a bbox — `south, west, north, east` (required), `n` (default 5). GeoJSON |
| `/api/risk-snapshot` | 60/min | Top-risk ranking over the configured monitored areas (real cached analyses). 503 `{"status": "unavailable"}` when no real snapshot exists |
| `/api/history` | 20/min | "Lessons from the Past": `?location=` or `?lat=&lon=`, `days` (default 90). Real ERA5 + FWI history, observed fires (FIRMS when configured), what HydraShield would have recommended — labelled OBSERVED / MODELLED / RECOMMENDED / UNKNOWN |
| `/api/report` | 10/min | Professional **PDF**. `?location=` or `?lat=&lon=`, `type=simple\|decision\|scientific` (default `decision`), `history=1` to include the past-lessons section. `application/pdf`, `inline` disposition |
| `/api/fires` | 20/min | Multi-source fire evidence (NASA FIRMS VIIRS+MODIS): `lat, lon`, `days` (default 5, clamped 1–10), `radius_km` (default 50, clamped 1–200). Honest unavailable without a key |
| `/api/exposure-features` | 20/min | Mapped OSM features (hospitals, schools, fire stations, water): `lat, lon`, `radius_m` (default 2000) |
| `/api/population-exposure` | 20/min | WorldPop estimate + population-by-hazard-class overlay: `lat, lon`, `radius_km` (default 3). Gridded estimates with reference year — never exact counts |
| `/api/smoke` | 20/min | **OBSERVED**-fire smoke transport (FIRMS detections + forecast winds): `lat, lon`, `radius_km` (50), `days` (3), `hours` (24). 503 without a configured observed-fire source |
| `/api/smoke-scenario` | 20/min | **SCENARIO** smoke transport for a hypothetical fire under current conditions: `lat, lon`, `hours` (24). Always labelled SCENARIO / MODELLED |
| `/api/ignition-risk` | 20/min | Relative Ignition-Likelihood Indicator: `lat, lon`. Screening-level, explicitly NOT a probability; carries `validation_status` (not validated) |
| `/api/exposure-summary` | 20/min | Combined human-exposure summary: wildfire hazard / population / ignition / OSM / smoke kept strictly separate, never merged into one number, never a probability |
| `/api/sources` | none | Data-source audit registry (same as `/api/v2/sources`) |

Non-public/operational v1 endpoints (`POST /api/analysis-jobs`,
`GET /api/analysis-jobs/<id>`, `POST /api/watch`, `DELETE /api/watch/<id>`,
`POST /api/spread`, `POST /api/allocation`, deprecated `POST /api/risk`)
exist for the website and may change without v2 stability guarantees.

---

## 4. Auth & account endpoints (`/api/v2`, auth required except as noted)

Session tokens are random 256-bit values, stored HMAC-hashed server-side.
CSRF: browser POSTs rely on the `SameSite=Lax` cookie; API clients must use
Bearer only.

### Public auth (rate-limited per IP)

| Endpoint | Limit | Body / params → response |
|---|---|---|
| `POST /api/v2/auth/register` | 20/hour | `{email, password, display_name?, consent?}` → 201 `{"status": "pending_verification", …}`; 409 if already registered |
| `GET /api/v2/auth/verify?token=…` | — | consumes the email token → `{"status": "verified", "session_token", "user"}` + session cookie |
| `POST /api/v2/auth/login` | 30/15 min | `{email, password}` → `{"session_token", "user"}` + cookie; 401 invalid, 403 unverified |
| `POST /api/v2/auth/logout` | — | destroys the session, clears the cookie → `{"status": "logged_out"}` |
| `POST /api/v2/auth/resend-verification` | 10/hour | `{email}` → indistinguishable `{"status": "ok"}` (never reveals whether the address exists) |
| `POST /api/v2/auth/forgot-password` | 10/hour | `{email}` → indistinguishable `{"status": "ok"}` |
| `POST /api/v2/auth/reset-password` | 10/hour | `{token, password}` → `{"status": "password_updated"}`; all sessions are invalidated. The password is validated before the single-use token is consumed |
| `POST /api/v2/contact` | 5/hour | `{email, message, name?}` → 201 `{"status": "received"}`. The acknowledgement never echoes the message |

### Account (Bearer or cookie)

| Endpoint | Notes |
|---|---|
| `GET /api/v2/account` | profile + counts: `{"user", "locations", "alerts"}` |
| `PATCH /api/v2/account` | `{display_name}` (only supported field) → `{"user"}` |
| `GET /api/v2/account/locations` | `{"locations": […]}` |
| `POST /api/v2/account/locations` | `{lat, lon, name?}` → 201 `{"location"}`; 50-location cap (403 + `upgrade`); per-tier rate budget |
| `DELETE /api/v2/account/locations/<id>` | `{"deleted": true}` or 404 |
| `GET /api/v2/account/history` | own analysis history |
| `GET /api/v2/account/alerts` | `{"alerts": […]}` |
| `POST /api/v2/account/alerts` | `{lat, lon, hazard?, threshold?, channel?}` — `threshold` is an object, e.g. `{"risk_gte": 65}`; `channel` default `email` → 201 `{"alert"}`; per-tier rate budget |
| `DELETE /api/v2/account/alerts/<id>` | `{"deleted": true}` or 404 |
| `GET /api/v2/account/usage` | `{"usage": […]}` — own usage log |

All account endpoints return 401 without a session. Per-user isolation is
enforced in every query (IDOR-safe).

---

## 5. Alert endpoints (`/api/v2/alerts`, auth required, `registered` tier+)

| Endpoint | Limit / cap | Notes |
|---|---|---|
| `POST /api/v2/alerts/phone` | 10/hour/IP | `{phone}` E.164 → 201 `{"status": "verification_sent", "phone", "delivery_backend"}`. The 6-digit code is delivered by SMS only — never in the response |
| `POST /api/v2/alerts/phone/verify` | 10/hour/IP | `{code}` → `{"status": "verified", "phone", "prefs"}`; enables `sms_enabled` by default |
| `DELETE /api/v2/alerts/phone` | — | removes own phone, disables SMS → `{"deleted": true}` |
| `GET /api/v2/alerts/preferences` | — | `{"prefs", "phone"}` |
| `PATCH /api/v2/alerts/preferences` | per-tier budget | fields: `sms_enabled`, `email_enabled`, `quiet_hours` (`{"start","end"}` HH:MM UTC or null), `language`, `max_per_day`; unknown fields → 400 |
| `GET /api/v2/alerts/rules` | — | `{"rules": […]}` |
| `POST /api/v2/alerts/rules` | per-tier budget + tier cap | `{hazard, lat, lon, name?, severity_threshold?}` (threshold default `HIGH`; hazard must be registered). Caps: registered 2 · subscriber/professional 25 · business/municipality/government 100 — 403 + `upgrade` at the cap |
| `DELETE /api/v2/alerts/rules/<id>` | — | `{"deleted": true}` or 404 |
| `GET /api/v2/alerts/history` | — | `{"alerts": […]}` — last 50 alert records with deliveries |
| `POST /api/v2/alerts/unsubscribe` | — | explicit SMS opt-out (`sms_enabled=false`); `?rules=1` also deletes all rules → `{"status": "unsubscribed", "rules_deleted": n}`. Audited |

---

## 6. Webhooks

**Status: live.** Management endpoints (session/cookie auth;
`require_role("registered")`):

| Endpoint | Notes |
|---|---|
| `GET /api/v2/account/webhooks` | list own subscriptions (secrets never included) |
| `POST /api/v2/account/webhooks` | create `{url, events:["alert_fired","significant_change"]}` — URL must pass the SSRF guard (HTTPS, public host); response includes the signing secret **once**; max 5/user |
| `DELETE /api/v2/account/webhooks/<id>` | delete own subscription |

- **Signing:** every delivery carries
  `X-HydraShield-Signature: sha256=<hex>` — HMAC-SHA256 of the raw request
  body with the webhook's secret. Verify before processing.
- **Payload envelope:**

  ```json
  {"event": "<alert_fired|significant_change>", "data": {}, "sent_at": "<ISO-8601 UTC>"}
  ```

  `data` for alerts: `{alert_id, hazard, location{name,lat,lon}, severity, trigger, analysis_id, created_at}`.
- **Delivery semantics:** at-least-once per dispatch run — receivers must
  be idempotent. Every delivery attempt is recorded server-side
  (`sent|failed|disabled`). A retry/backoff worker is a roadmap item.
- **Transport:** HTTPS only; private/loopback targets are refused at
  creation and re-validated at every delivery (SSRF/DNS-rebinding guard).

## 7. API keys

**Status: live.** Management endpoints (session/cookie auth):

| Endpoint | Role | Notes |
|---|---|---|
| `POST /api/v2/account/api-keys` | subscriber | create `{label}` → plaintext key `hs_…` returned **once** |
| `GET /api/v2/account/api-keys` | registered | list own keys (id/label/dates; never the key) |
| `DELETE /api/v2/account/api-keys/<id>` | registered | revoke own key |

Keys are stored HMAC-hashed, revocable, and sent as the `X-API-Key`
header. They are **read-only**: they authenticate `GET` requests as their
owner (for usage metering and tier rate budgets); any non-GET request
with an API key is refused with 403. They never grant access to other
users' data.

---

## 7a. Product analytics (first-party)

`POST /api/v2/analytics/event` — public, 60/min per IP, returns 202.
First-party, privacy-conscious product events (docs/PRODUCT_ANALYTICS.md
is normative): whitelisted event names only, unknown fields dropped, no
identity accepted, coordinates rounded to ~11 km, session pseudonyms
stored as HMAC hashes. Single event object or `{"events": [...]}`
(max 20).

Admin aggregates — `admin` tier required, aggregate counts only:

- `GET /api/v2/admin/analytics/summary` — totals, by-event counts, funnel
- `GET /api/v2/admin/analytics/top?dimension=page|hazard|referrer|feature&limit=N`
- `GET /api/v2/admin/analytics/daily?days=N` (max 90)

---

## 8. Versioning policy

- `/api/v2/…` is stable: new fields and new endpoints may be added;
  existing fields are never removed, renamed or re-typed.
- A breaking change requires `/api/v3`.
- Deprecations are announced in responses (`sunset` header) two minor
  versions ahead.
- The v1 `/api/…` public GET contracts (§3) are frozen, not versioned
  further; new capability lands in v2.

## 9. Changelog

- **2026-08-17** — First published v2 contract: hazard registry, per-hazard
  analyze/events, economy, solutions, sources; frozen v1 public GETs;
  auth/account/alerts; webhooks (live, §6); API keys (live, §7).
- **2026-08-17 (2)** — Data Observatory (`/registry`), Model Registry
  (`/models`), Research Registry (`/research`), ingestion chains,
  Compound Risk (`/compound`), Cascading Risk (`/cascading`), Economic
  Impact (`/economic-impact`).
- **2026-08-17 (3)** — Ground Truth Event Registry (`/ground-truth`),
  Benchmark Suite (`/benchmarks` + admin `/benchmarks/run`), immutable
  evaluation runs (`/evaluations`) + model lifecycle states, Source
  Intelligence (`/source-health`), reproducible analysis runs
  (`/analysis-runs`), Loss Data Registry (`/losses`).
