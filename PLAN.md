# HydraShield — Working Plan

Living plan between the operator and the AI copilot. Statuses are kept
honest: an item is "done" only when it is verified in production.

Legend: ✅ done · 🔶 partially done / in progress · ⬜ planned

## Platform foundation

| Item | Status | Notes |
|---|---|---|
| User registration end-to-end (register → email verify → login) | ✅ | Verified live 2026-08-22: 201 on register, real verification email via Gmail SMTP, browser redirect to `account.html?verified=1`, session persists across deploys (`HYDRASHIELD_SECRET_KEY` set) |
| Operator account `info@hydrashield.earth` = admin | ✅ | Activated + promotion chain verified server-side; Commercial Center at `admin.html` |
| Transactional email (verification, reset, alerts) | ✅ | Gmail SMTP live on Vultr (`/opt/hydrashield/.env`, never in Git) |
| SMS alerts | 🔶 | Code complete, 33 tests green, three honest backends; production runs the dev outbox — **no real SMS until a provider is configured** (`SMS_PROVIDER=http` + `SMS_HTTP_URL` + key/secret in server `.env`) |
| Show/hide password on auth forms | ✅ | Live on `account.html` |
| Tropical cyclones — 7th hazard | ✅ | GDACS (UN-OCHA/EU JRC) live global monitoring: analyze + active-storms map layer; historical tracks via IBTrACS declared candidate (not wired, honestly stated) |
| International trade movement on the map | 🔶 | Ports/harbours layer live (OSM, 50 km, `/api/trade-infrastructure`); live vessel tracking (AIS) needs a shipping-data provider — declared, not wired |

## Geographic coverage — "we cover the entire Earth"

| Item | Status | Notes |
|---|---|---|
| Global coverage statement on homepage | ✅ | Hero states global coverage with the honest terrain caveat |
| Actual data coverage | ✅ | Core integrated datasets are global (Sentinel-2, Open-Meteo, ERA5/-Land, FIRMS VIIRS/MODIS, WorldPop, OSM, GloFAS, ESA WorldCover); elevation 25 m Europe / 90 m for 60°N–56°S (SRTM); per-dataset coverage in the data registry (67 sources) and on `sources.html` |
| Clarify coverage scope across all pages | 🔶 | Homepage done; extend to `technology.html` / `for-*` pages where relevant |
| National open-data + geo portal connectors | ⬜ | Per-country open data (national geo portals, Copernicus/EEA) feeding the analytical models, documented in provenance |

## Go-to-market

| Item | Status | Notes |
|---|---|---|
| Marketing workspace + daily copilot | ✅ | `marketing/` + `scripts/marketing_status.py morning/evening`; hazard→market radar live |
| Audience segmentation (government / insurance / investment / …) | ✅ | 31 segments in `marketing/segments/segments.json`, matched to the site's `for-*` pages |
| Grant classifier — EU + global companies + banks | ⬜ | Foundation exists (`marketing/eu_funding/`, 10 verified Horizon records). Unify: instrument × sector × eligibility × deadline × budget × fit score; expose in Commercial Center |
| Newsletter (design matching the site) | ⬜ | Built on the existing mailer; own GDPR consent + unsubscribe; inherits site identity (Inter/Space Grotesk, #0EA5E9) |
| Case studies published | ⬜ | Must be real — candidates exist in repo research (`docs/*_Opportunities.md` location analyses); publish only evidence-backed studies |
| Pricing clarification | ⬜ | Site currently states (honestly) "no public pricing yet". Decide tier structure/pricing, then publish a clear pricing page — no invented numbers |
| "Where to invest / what to build" service | ⬜ | Core product item: positive siting intelligence (low multi-hazard risk + infrastructure + available funding) for companies, municipalities and governments; fields + environment-compatible technologies per location |
| Sustainability-report evidence | 🔶 | Platform reports already serve as physical-risk evidence annexes (CSRD/ESRS E1, TCFD/ISSB positioning); labelled screening-level until model validation completes (`docs/VALIDATION.md`) |

## Operating rules (binding)

- No fabricated content: leads, grants, case studies and prices enter only
  from real, checkable sources or an explicit operator decision.
- Every deploy: push to `main` → GitHub Actions tests (784) → Vultr.
- Server secrets live only in `/opt/hydrashield/.env` (chmod 600).
