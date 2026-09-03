# Talaix — Working Plan

Living plan between the operator and the AI copilot. Statuses are kept
honest: an item is "done" only when it is verified in production.

Legend: ✅ done · 🔶 partially done / in progress · ⬜ planned

## Platform foundation

| Item | Status | Notes |
|---|---|---|
| User registration end-to-end (register → email verify → login) | ✅ | Verified live 2026-08-22: 201 on register, real verification email via Gmail SMTP, browser redirect to `account.html?verified=1`, session persists across deploys (`HYDRASHIELD_SECRET_KEY` set) |
| Operator account `info@talaix.com` = admin | ✅ | Activated + promotion chain verified server-side; Commercial Center at `admin.html` |
| Transactional email (verification, reset, alerts) | ✅ | Gmail SMTP live on Vultr (`/opt/hydrashield/.env`, never in Git) |
| SMS alerts | 🔶 | Code complete, 33 tests green, three honest backends; production runs the dev outbox — **no real SMS until a provider is configured** (`SMS_PROVIDER=http` + `SMS_HTTP_URL` + key/secret in server `.env`) |
| Show/hide password on auth forms | ✅ | Live on `account.html` |
| Tropical cyclones — 7th hazard | ✅ | GDACS (UN-OCHA/EU JRC) live global monitoring: analyze + active-storms map layer; historical tracks via IBTrACS declared candidate (not wired, honestly stated) |
| International trade movement on the map | 🔶 | Ports/harbours layer live (OSM, 50 km, `/api/trade-infrastructure`); live vessel tracking (AIS) needs a shipping-data provider — declared, not wired |

## Geographic coverage — "we cover the entire Earth"

| Item | Status | Notes |
|---|---|---|
| Global coverage statement on homepage | ✅ | Hero states global coverage with the honest terrain caveat |
| Actual data coverage | ✅ | Core integrated datasets are global (Sentinel-2 + Landsat C2 L2 fallback, Open-Meteo, ERA5/-Land, FIRMS VIIRS/MODIS, WorldPop, OSM, GloFAS, ESA WorldCover); elevation 25 m Europe / 90 m for 60°N–56°S (SRTM); per-dataset coverage in the data registry (167 datasets, grouped by catalog_group) and on `sources.html` |
| Clarify coverage scope across all pages | 🔶 | Homepage done; extend to `technology.html` / `for-*` pages where relevant |
| National open-data + geo portal connectors | 🔶 | 2026-09-03: 98 global sources catalogued as candidates in the Data Observatory (national portals incl. EU/US/UK/FR/DE/ES/CA/AU/JP/KR/IN/BR/MX/SA/QA/JO/MA/TN, international orgs, hazard archives, EO, climate, environment, energy, evidence registries) — URLs audited. Gradual engine wiring wave 1 done: GDACS multi-hazard (flood FL + volcanic VO event layers), NASA EONET (wildfire second source), GEOGLOWS (second discharge provider — declared gap closed); 20/168 datasets integrated |

## Go-to-market

| Item | Status | Notes |
|---|---|---|
| Marketing workspace + daily copilot | ✅ | `marketing/` + `scripts/marketing_status.py morning/evening`; hazard→market radar live |
| Audience segmentation (government / insurance / investment / …) | ✅ | 31 segments in `marketing/segments/segments.json`, matched to the site's `for-*` pages |
| Grant classifier — EU + global companies + banks | ⬜ | Foundation exists (`marketing/eu_funding/`, 10 verified Horizon records). Unify: instrument × sector × eligibility × deadline × budget × fit score; expose in Commercial Center |
| Newsletter (design matching the site) | ⬜ | Built on the existing mailer; own GDPR consent + unsubscribe; inherits site identity (Inter/Space Grotesk, #0EA5E9) |
| Case studies published | ✅ | First three live on the reports portal (`hydra-shield-platform/website/reports.html`): anonymized real-decision studies — bank credit file, insurance underwriting referral, CSRD/ESRS E1 disclosure. Operator-attested, no invented metrics; further studies only real, checkable and with the customer's written approval |
| Pricing clarification | 🔶 | Tiers and prices decided 2026-08-31: `hydra-shield-platform/docs/PRICING.md` (Free / Professional €49/mo launch / Business €249/mo / Government from €4,900/yr / Enterprise from €12,000/yr; pay-per-report €19–39; pilot programme trades nominal price for publishable case studies; recorded-not-charged until billing ships). Remaining: publish the pricing page + update `account.html` wording |
| Stripe billing integration | 🔶 | Backend blueprint + checkout/portal/webhook + idempotency + data model + frontend buttons + tests are done. Awaiting deploy + real Stripe secrets (`STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY`, `STRIPE_WEBHOOK_SECRET`, `TALAIX_PUBLIC_BASE_URL`) and `scripts/setup_stripe_products.py` run against the live account. No secrets in Git. |
| "Where to invest / what to build" service | ⬜ | Core product item: positive siting intelligence (low multi-hazard risk + infrastructure + available funding) for companies, municipalities and governments; fields + environment-compatible technologies per location |
| Sustainability-report evidence | 🔶 | Platform reports already serve as physical-risk evidence annexes (CSRD/ESRS E1, TCFD/ISSB positioning); labelled screening-level until model validation completes (`docs/VALIDATION.md`) |

## Funders outreach wave 1 (draft, awaiting operator review)

| Item | Status | Notes |
|---|---|---|
| Wave-1 draft — 10 funder targets (EIC, LIFE-CINEA, DG ECHO, EUSPA, EEA, Climate-KIC, MITECO, ApC Portugal, Poland MoC, BNDES) | 🔶 | `marketing/outreach/funders_wave1.md`; official recipient emails sourced 2026-08-31 |
| Preview sample email (EIC( → operator inbox | 🔶 | `scripts/send_preview_funder_wave.py` + `email_templates/outreach_funders.txt`; local run lands in `data/outbox/` — real send on Vultr; 18 mailer tests green |

## Repositioning — financial/investment product (operator decision 2026-09-02)

| Item | Status | Notes |
|---|---|---|
| Site IA + homepage → financial/investment identity | ✅ | Verified live 2026-09-02: new nav, money-first homepage, wildfire pages hidden/relocated (commit 5d6295b) |
| Reports engine front-and-centre | ✅ | Verified live 2026-09-02: top-level nav, finance-first order, wildfire PDFs archived |
| Environmental Licensing advisory page | ✅ | Verified live 2026-09-02: `licensing.html` HTTP 200 (advisory, not a legal permit) |
| Documented loss figures — free open sources | ✅ | Verified live 2026-09-02: NOAA NCEI integrated; `/api/v2/losses/summary` returns real figures in production; EM-DAT/DesInventar staged ingest |
| Commercial loss-DB licences (Munich Re NatCatSERVICE, Swiss Re sigma) | ⬜ | Procure after first platform revenue; registry entries marked `planned` |

## Operating rules (binding)

- No fabricated content: leads, grants, case studies and prices enter only
  from real, checkable sources or an explicit operator decision.
- Every deploy: push to `main` → GitHub Actions tests (784) → Vultr.
- Server secrets live only in `/opt/hydrashield/.env` (chmod 600).
