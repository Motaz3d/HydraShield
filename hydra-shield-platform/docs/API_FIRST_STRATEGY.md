# HydraShield — API-First Strategy

**Status:** normative direction. HydraShield is a climate/hazard
intelligence **infrastructure** with a website on top — not a website with
an API bolted on. Every analytical capability ships as a stable, versioned,
documented API first; the HydraShield frontend is merely the reference
consumer.

---

## 1. Principles

1. **One analytical engine, many interfaces.** The same real-data engine
   serves the website, the REST API, the Python SDK, the JavaScript SDK,
   the embeddable component, monitoring jobs and webhooks. No interface
   gets its own logic.
2. **Versioned contracts.** `/api/v2/…` is a stable contract: additive
   changes only; breaking changes require `/api/v3`. Deprecations are
   announced in responses (`sunset` header) two minor versions ahead.
3. **External-first.** A company must be able to integrate HydraShield
   into its own SaaS, GIS, property, insurance, banking or government
   system **without ever loading the HydraShield frontend**: REST + SDKs +
   embeddable web component + webhooks.
4. **Real data only — everywhere.** The same honesty rules apply to every
   interface: explicit `unavailable` states, provenance, claim/temporal
   labels, honest confidence, no fabricated values.
5. **Build vs partner.** We do not rebuild what a reliable external
   provider does better (see `PRODUCTS_AND_PARTNERSHIPS.md`). HydraShield's
   value is the analytical core + evidence discipline + integration surface.

## 2. Interface surface

| Interface | Consumers | Status |
|---|---|---|
| REST `/api/v2` | any system | stable contract, documented in `docs/API_V2.md` |
| Python SDK (`sdk/python/hydrashield/`) | data science, backends, research | implemented (stdlib-only) |
| JavaScript SDK (`sdk/js/hydrashield.js`) | web apps, SaaS frontends | implemented (fetch-based, no deps) |
| `<hydrashield-risk>` Web Component | property/GIS/insurance websites | implemented (CORS-gated) |
| Monitoring API (`/api/v2/alerts/*`) | ops teams, municipalities | implemented |
| Webhooks (HMAC-signed) | event-driven systems, insurers, banks | implemented |
| Standard formats (GeoJSON layers) | GIS systems | risk-grid GeoJSON; CAP/GML scaffold is roadmap |

## 3. Access model for external consumers

- **Public tier** (rate-limited per IP): snapshot, risk-grid, sources,
  limited analysis — keeps the open-data spirit.
- **API key** (`X-API-Key` header): subscriber-issued keys (created in the
  account page, stored HMAC-hashed, revocable) unlock higher rate budgets
  and (later) licensed historical/economic datasets. Keys identify the
  consumer for usage metering (`usage_log`), never grant write access to
  other users' data.
- **CORS**: read-only public GET endpoints may be exposed to configured
  origins via `HYDRASHIELD_CORS_ORIGINS` (exact origins, never `*` with
  credentials; default: same-origin only).
- **Webhooks**: outbound only, HMAC-SHA256 signed (`X-HydraShield-Signature`),
  HTTPS-only, SSRF-guarded (no private/loopback targets), at-least-once
  with recorded delivery status.

## 4. Versioning & stability rules

- Response envelopes keep stable top-level keys per endpoint; new fields
  are additive; removed/renamed fields only in a new version.
- Every analysis response carries `generated_at`, provenance and
  (where applicable) a content hash so integrators can cache and verify.
- Errors are stable JSON: `{"error": str, "status": int}` — SDKs rely on it.

## 5. Event-driven intelligence (monitoring → webhooks)

The alert engine evaluates: threshold crossing, recovery, and significant
change (declared 24 h/7 d delta method on the same real series). On an
alert it routes: in-app record → email → SMS → webhook(s). Every delivery
is recorded with status; nothing fires on invented data; anti-flood rules
apply to every channel.

## 6. What this is not

- Not a data reseller: we serve derived intelligence with provenance, not
  repackaged upstream datasets (upstream licenses respected).
- Not a forecast vendor: forecasts/projections are labelled and never
  blended into observations.
- Not a black box: every score links to its evidence and its
  validation status.
