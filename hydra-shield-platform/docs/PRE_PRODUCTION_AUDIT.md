# Pre-Production Audit Report — Climate Extreme Intelligence evolution

**Date:** 2026-08-17 · **Scope:** 12 local commits on `main` ahead of
`origin/main` (11 evolution commits + 1 audit-fix commit) ·
**Verdict:** GREEN — ready to push on explicit owner instruction.

---

## 1. Change summary

- `git status`: clean tree, branch 12 commits ahead of `origin/main`.
- `git diff --stat origin/main..HEAD`: **79 files, +15,730 / −1,117**
  (60 added, 19 modified, 0 deleted).
- No production deploy performed; nothing pushed.

## 2. Test results

| Gate | Result |
|---|---|
| Offline test suite | **356 passed** (227 baseline + 129 new) |
| Real-data integration (`test_real_integration.py`, live network) | **2/2 passed** — real Sentinel-2 scene (S2C_31UGR_20260814, 0.08 % cloud), full Clervaux pipeline, 19 provenance components |
| Live API smoke (local) | v1 health/status/sources/snapshot(5 entries)/risk-grid/spread 200; analyze/report correctly 400 without params; watch validation 400 on bad input |
| Live v2 smoke (real data) | all six hazards `status: ok` with real data (flood discharge 10.5 m³/s; drought deficit z=−0.85, 2nd driest 90-day window of 10; wind gust percentile 18.0 vs 1991–2020; heat 37.4 °C p82.2; coastal waves OBSERVED/FORECAST labelled); events `key_required` honest without FIRMS key; economy `not_quantified`; solutions 11 real matches |
| Docker | image builds clean; container smoke: health OK, six hazards registered, real heat analysis inside container |
| Docker Compose | `docker compose config -q` valid (api, dash, caddy, watch_checker) |
| Frontend | `node --check` on all 12 JS files; all 16 pages serve 200; every fetch URL validated against deployed routes |

## 3. Security review

**Secrets & credentials**
- Tracked sensitive files: only `.env.example` (names, no values). No
  `.env`, keys, or PEMs tracked. No hardcoded password/token/API-key
  patterns in tracked source. Git history of the range scanned: clean.
- `info@talaix.com` appears only as an address (SMTP_FROM default,
  templates, docs, tests). **No credentials for it anywhere** — tracked
  files, history, Dockerfile, frontend, logs, docs all clean.

**Auth/accounts (accounts.py, auth_api.py)**
- PBKDF2-HMAC-SHA256 (120 k iters, per-user salt); dummy-verify blunts
  timing enumeration; tokens are 256-bit random, stored HMAC-hashed only;
  constant-time comparisons; parameterised SQL throughout; per-user
  isolation on every account query (no IDOR); input length caps; audit
  log free of secrets (tested); session cookie HttpOnly + SameSite=Lax +
  Secure-on-HTTPS; per-IP limits on public endpoints + per-tier per-user
  budgets; least-privilege defaults (role `registered`, status `pending`).
- Known accepted limitations (documented, pre-existing): rate limiter is
  per-worker in-memory; CSRF relies on SameSite=Lax (double-submit token
  is a roadmap item); verification tokens travel in URLs (one-time, 24 h
  TTL — standard practice).

## 4. Evidence & honesty verification

- **Label discipline:** "modeled" survives only in the documented alias
  table (normalised to MODELLED); coastal sea-level rise is a structurally
  separate block (`temporal: PROJECTED`, per-scenario `SCENARIO`, IPCC AR6
  SPM citation) — verified not mixed into observations; marine waves
  `latest: OBSERVED` vs `forecast: FORECAST` verified live; events carry
  classification + cause discipline (UNKNOWN unless DOCUMENTED — enforced
  by type, tested).
- **Monetary fabrication:** no monetary values in new product code; the
  economy endpoint always returns the exact `not_quantified` statement;
  solutions KB `cost_basis: "not quantified"` everywhere; solutions source
  URLs are 20 real institutional domains (verified list).
- **Hazard operational claims:** a hazard registers only with a wired real
  source (tested — unbuilt foundations are honestly absent); all six
  registered hazards verified live against real upstream data; website
  copy sweep found no overclaims (only disclaimer phrasing).
- **Randomness:** none in new code. Two pre-existing seeded-RNG uses
  (GDPR anonymisation helper, ML training negative sampling — declared,
  outside the serving path) predate this range.

## 5. Defects found during review — all fixed locally (commit `3d5f83e`)

1. **Contact submissions never reached the platform** — the endpoint only
   mailed the acknowledgement to the submitter. Fixed: message now goes to
   the platform inbox (`CONTACT_INBOX`, default info@talaix.com)
   via a new `contact_message` template.
2. **Contact-form spam-relay vector** — the acknowledgement echoed the
   submitter's full message to any address. Fixed: acknowledgement no
   longer echoes message content.
3. **GDPR consent assumed** — registration recorded `consent=True` when
   the client sent nothing. Fixed: defaults to not-given; only actual
   consent is recorded.
4. **Label inconsistency in PDF metadata** — evidence summary printed
   "MODELED". Fixed: normalised to MODELLED.
5. **Unsourced monetary claims on legacy problem.html** — "€20,000/hour",
   "80% water loss" presented as fact. Fixed: reframed as rounded
   published estimates with an explicit context note.

Each fix has regression tests; suite re-run green (356).

## 6. Compatibility

- v1 `/api/…` contracts untouched and live-verified; legacy
  `dashboard.js` / `risk-snapshot.js` byte-identical; Dash app and
  compose topology unchanged; database changes are additive-only
  (`CREATE TABLE IF NOT EXISTS`) on the shared SQLite file.

## 7. Deferred observations (not blocking; tracked in IMPLEMENTATION_ROADMAP)

- CSRF double-submit token; GDPR data-subject export/erasure endpoints;
  watch→account migration; per-tier saved-location limits are uniform
  (the 50-cap `upgrade` descriptor points at tiers whose higher limits
  are a later stage); rate limiter per-worker; `roadmap.html` grant
  figures are aspirational plan targets (left as-is deliberately).

## 8. Sign-off

All 17 review steps executed and green. Production remains untouched.
**Awaiting explicit instruction before `git push origin main`.**
