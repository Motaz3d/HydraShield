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
| AGENTS.md project map + session protocol | ✅ | 2026-09-05: root `AGENTS.md` maps the repo + auto session protocol (read PLAN.md at start, update both files at end) — saves exploration tokens every session |
| Analytical engine → public open-source repo (`tore`) | ✅ | 2026-09-06: engine extracted to https://github.com/Motaz3d/tore (EUPL-1.2, "Talaix Open Risk Engine") for the NLnet Restack application — tx_core + src.climate (minus web blueprints) + src.prediction + src.gis_mapping + analytical dashboard data-pipeline + hydration_control + 4 config registries. 34 tests green in standalone venv; verified live end-to-end (8/10 hazards real data at Mersin; dust/volcanic honestly unavailable). **Binding: engine changes must be mirrored — `scripts/sync_tore.sh --push -m "..."`** (rule in root AGENTS.md) |

## Geographic coverage — "we cover the entire Earth"

| Item | Status | Notes |
|---|---|---|
| Global coverage statement on homepage | ✅ | Hero states global coverage with the honest terrain caveat |
| Actual data coverage | ✅ | Core integrated datasets are global (Sentinel-2 + Landsat C2 L2 fallback, Open-Meteo, ERA5/-Land, FIRMS VIIRS/MODIS, WorldPop, OSM, GloFAS, ESA WorldCover); elevation 25 m Europe / 90 m for 60°N–56°S (SRTM); per-dataset coverage in the data registry (167 datasets, grouped by catalog_group) and on `sources.html` |
| Clarify coverage scope across all pages | 🔶 | Homepage done; extend to `technology.html` / `for-*` pages where relevant |
| National open-data + geo portal connectors | 🔶 | 2026-09-03: 98 global sources catalogued as candidates in the Data Observatory (national portals incl. EU/US/UK/FR/DE/ES/CA/AU/JP/KR/IN/BR/MX/SA/QA/JO/MA/TN, international orgs, hazard archives, EO, climate, environment, energy, evidence registries) — URLs audited. Gradual engine wiring waves 1–2 + late wave done: GDACS multi-hazard (flood FL + volcanic VO), NASA EONET (wildfire + dust events), GEOGLOWS + USGS gauges + USGS dv history (discharge: 2 models + observed gauges), **earthquake module** (USGS ComCat + EMSC — 10 hazards), **IBTrACS cyclone archive** (prepared, last 3 seasons), **CAMS dust pipeline** (key-gated, activates with CAMS_ADS_KEY); GEM re-evaluated → stays candidate (no point API); 25/168 datasets integrated |

## Go-to-market

| Item | Status | Notes |
|---|---|---|
| Marketing workspace + daily copilot | ✅ | `marketing/` + `scripts/marketing_status.py morning/evening`; hazard→market radar live. LinkedIn post-time macOS alerts active since 2026-09-07 (`scripts/linkedin_post_alert.sh` — cron Tue/Wed/Thu 07:00 + Sun 16:00 local, notification + opens the day's draft) |
| Daily outreach volume | ✅ | Operator decision 2026-09-07: 15/day this week → 20/day from 2026-09-14 (`DAILY_SEND_CAP=15` in `.env`; one-shot cron `data/bump_send_cap.sh` bumps it on 09-14). Fixed `sent_today_count` double-count (scheduled sends were counted twice → effective cap was ½); 13 stale pre-pivot scheduled rows (insurance/banking/investment templates) cancelled — fresh start under the compliance identity |
| Audience segmentation (government / insurance / investment / …) | ✅ | 34 segments in `marketing/segments/segments.json` — incl. `sustainability_compliance` (tier-A since 2026-09-06) + `eudr_operators` — matched to the site's industries hub |
| Grant classifier — EU + global companies + banks | ⬜ | Foundation exists (`marketing/eu_funding/`, 10 verified Horizon records). Unify: instrument × sector × eligibility × deadline × budget × fit score; expose in Commercial Center |
| Newsletter (design matching the site) | ⬜ | Built on the existing mailer; own GDPR consent + unsubscribe; inherits site identity (Inter/Space Grotesk, #0EA5E9) |
| Case studies published | ✅ | First three live on the reports portal (`hydra-shield-platform/website/reports.html`): anonymized real-decision studies — bank credit file, insurance underwriting referral, CSRD/ESRS E1 disclosure. Operator-attested, no invented metrics; further studies only real, checkable and with the customer's written approval |
| Talaix Academy pilot course | 🔶 | 2026-09-05 deepening pass: 6→8 modules in `config/academy_course.json` — added "Hazard types and data sources" + "From hazard to financial impact", per-module learning objectives, case-study sections, try-it product links on every module; knowledge graph 30→42 nodes; glossary 22→30 terms; `academy.html` start panel (free-during-pilot note, progress bar, start/continue button). 2026-09-06 wave 2: 4 modules deepened (~127 min total), ESRS E1 physical-risk explainer brief published (3rd brief; EUR-Lex + EFRAG sources verified live), LinkedIn add-to-profile button on issued certificates; 31 academy/briefs tests green. 2026-09-06: Academy section added to homepage between "Who it's for" and "Reports" (dark band, 3 cards + CTA). SEO wave: static page per brief at `briefs/<id>.html` (canonical, OG, JSON-LD Article, `<base href="../">` for site chrome) generated from the registry by `scripts/build_brief_pages.py`; sitemap BRIEFS block auto-updated; briefs.js cards open static pages; freshness enforced by `tests/test_briefs_pages.py`. Next: more depth toward 4–6 h, `scripts/draft_brief.py` sourcing assistant, RSS feed, diagnostic onboarding, university partnership. **Publishing cadence (operator-approved 2026-09-06): evidence brief every 2 weeks — next due 2026-09-20 (human review before publish); framework explainer monthly — next due 2026-10-04** |
| Pricing clarification | ✅ | Tiers and prices decided 2026-08-31: `hydra-shield-platform/docs/PRICING.md` (Free / Professional €49/mo launch / Business €249/mo / Government from €4,900/yr / Enterprise from €12,000/yr; pay-per-report €19–39; pilot programme trades nominal price for publishable case studies; recorded-not-charged until billing ships). `pricing.html` published 2026-09-04; `account.html` links to it |
| Stripe billing integration | 🔶 | Backend blueprint + checkout/portal/webhook + idempotency + data model + frontend buttons + tests are done. Awaiting deploy + real Stripe secrets (`STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY`, `STRIPE_WEBHOOK_SECRET`, `TALAIX_PUBLIC_BASE_URL`) and `scripts/setup_stripe_products.py` run against the live account. No secrets in Git. |
| "Where to invest / what to build" service | ⬜ | Core product item: positive siting intelligence (low multi-hazard risk + infrastructure + available funding) for companies, municipalities and governments; fields + environment-compatible technologies per location |
| Sustainability-report evidence | 🔶 | Platform reports already serve as physical-risk evidence annexes (CSRD/ESRS E1, TCFD/ISSB positioning); labelled screening-level until model validation completes (`docs/VALIDATION.md`) |
| Google Search Console — sitemap | 🔶 | 2026-09-06: `https://talaix.com/sitemap.xml` submitted (domain property; full URL required). File verified live (HTTP 200, valid XML, 28 URLs, referenced in robots.txt; `/sources` clean URL also 200). GSC shows initial "Couldn't fetch" — normal for fresh submissions; check it flips to Success within a few days |

## GRC compliance direction — compliance-first identity (operator decision 2026-09-06)

| Item | Status | Notes |
|---|---|---|
| Market study + 8 strategic decisions | ✅ | `hydra-shield-platform/docs/COMPLIANCE_STRATEGY.md`: 33 vendors profiled (17 CSRD/GRC suites — none but Clarity AI does physical risk; 16 physical-risk vendors — all opaque enterprise pricing), regulatory calendar verified (EUDR live since 30 Dec 2025 / 30 Jun 2026, CSRD W2 reports FY2027, simplified ESRS adopted 3 Jul 2026). Gap we occupy: transparently priced standalone evidence packs |
| Compliance-first identity pivot on site | ✅ | Hero/title/meta/JSON-LD → "Climate-risk compliance evidence for EU disclosure"; nav reordered (Compliance first); footer brand line; llms.txt rewritten; `compliance.html` gained the who-must-comply wave calendar. 2026-09-07: LinkedIn presence aligned — founder About rewritten compliance-first (delivered for manual paste), 09-08 post rewritten (ESRS E1 evidence angle), stale 09-05 slot retired |
| Marketing segments → compliance | ✅ | +2 segments (`sustainability_compliance` = new tier-A primary, `eudr_operators`) in `marketing/segments/segments.json` |
| sustainability.html sharpened as first-customer funnel | ✅ | Free applicability check now leads (anchor `#applicability`), 4-step path (scope → sample pack → €490 pilot → subscribe), deadline framing (W2 reports FY2027 / published 2028), pricing strip. **Pricing decision: tiers unchanged** (transparent published prices are the wedge) — added the free CSRD-check row to `pricing.html` |
| Corporate email signature → compliance-first | ✅ | `_SIGNATURE_LINES` in `mailer.py` (+ brand tests): "Climate-Risk Compliance Evidence for EU Disclosure / Earth Observation & Physical-Risk Intelligence / Luxembourg-based technology team" — appended to every outgoing message |
| Compliance outreach wave 1 — preview SENT, wave ready for Vultr sends | 🔶 | Operator approved 2026-09-06. `compliance_wave1.md` + `.json` (8 verified Tier-1 targets; Position Green = webform-only, operator submits manually) + template `outreach_sustainability_compliance` + `send_compliance_wave1.py` (dry-run default, gates, caps, idempotent). **Preview incident resolved same day**: preview scripts never loaded `.env` → silent outbox fallback on the Vultr host; fixed (both compliance + funder previews), regression test added, deployed. Preview then sent for real from the operator's local env (Backend: smtp → info@talaix.com; carries the new signature). 2026-09-08 LinkedIn post rewritten compliance-first (`2026-09-08-research-reproducible-analysis.md`, segment → `sustainability_compliance`, landing → `compliance.html`). Next: `send_compliance_wave1.py --send` on Vultr from 2026-09-08, 2/day staggered |
| Rolling outreach pipeline — no empty queue (operator directive 2026-09-07) | 🔶 | Sequence locked by operator: investors (09-08/09) → CSRD companies + insurance (09-10/11) → **consultants LAST** (09-14→16). **CSRD wave 1 SCHEDULED** (`csrd_companies_wave1.json`: 14 email — published sustainability/general mailboxes only, e.g. Meliá/TUI/BASF/OMV/Metlen — + 8 webform-manual + 7 IR-only holds; rows #74–#87: 10 on 09-10 + 4 on 09-11). **Insurance fresh batch SCHEDULED** (2 honest sends: Sara, UMAS; DPO mailboxes + weak fits skipped — 26 premium insurers were pre-pivot-contacted → follow-up path ~09-22). **Consultants wave 1 BUILT, awaiting معتمد** (`build_consultants_wave1.py` → 41 entries from verified store contacts; Deloitte + QID dropped; preview `consultants_wave1_preview.html`; sends 15/day 09-14..16 when cap → 20). Generic scheduler `scripts/schedule_wave.py` (dry-run default, idempotent). Templates updated to the true 10-hazard roster. 21 wave tests green (`test_next_waves.py`) |
| GRC phase tracker | 🔶 | `docs/GRC_COMPLIANCE.md`: Phase 1 🔶 (CsrdTX + XBRL live since 2026-09-05; ESRS E1 datapoint-coverage map + E1-9 financial-effects context next), Phase 2 🔶 (funnel + wave draft done; sends after operator review). Infosec = internal trust enabler only, never a service line |

## Funders outreach wave 1 (draft, awaiting operator review)

| Item | Status | Notes |
|---|---|---|
| Wave-1 draft — 10 funder targets (EIC, LIFE-CINEA, DG ECHO, EUSPA, EEA, Climate-KIC, MITECO, ApC Portugal, Poland MoC, BNDES) | 🔶 | `marketing/outreach/funders_wave1.md`; official recipient emails sourced 2026-08-31 |
| Preview sample email (EIC( → operator inbox | 🔶 | `scripts/send_preview_funder_wave.py` + `email_templates/outreach_funders.txt`; local run lands in `data/outbox/` — real send on Vultr; 18 mailer tests green |

## Investor track

| Item | Status | Notes |
|---|---|---|
| Global investor landscape — all 6 world regions | ✅ | `marketing/research/global_investor_landscape_2026-09.md` + **interactive HTML** (`global_investor_landscape_2026-09.html`, same folder — search/region/EU-BV/verified/Tier-A filters): 106 entities across Europe (38), APAC (15), MENA (15), NA (13), Africa (13), LatAm (12); Tier-A shortlist of 26 (LUMO Labs, HTGF, BOM/Brabant Ventures, Satgana, Munich Re Ventures, Seraphim Space, Pale Blue Dot, Faber…), outreach waves A/B/C sequenced, domicile compatibility flagged per entity, verified-ticket marks + master re-check list |
| Operator contact for investor-facing signatures | ✅ | Motaz Omarien · motaz3d@gmail.com · **+352 661811680** · talaix.com — phone added to deck title + closing slides (regenerated 2026-09-07) and to be used in the DeepTechXL reply signature |
| **Next actions (operator-manual)** | 🔶 | 1) Send the DeepTechXL reply from motaz3d@gmail.com in the same thread, attaching `marketing/outreach/deeptechxl_pitch_deck.pdf` (final draft approved 2026-09-07). 2) Export LinkedIn profile → Save to PDF (or paste CV facts) so the Team slide gets a real founder bio, then regenerate the deck. 3) Submit the 6 webform-only funds (Satgana, Munich Re Ventures, Seraphim, Savia, OurCrowd, IDB Lab — URLs + notes in `marketing/outreach/investor_waves_abc.md`) |
| Investor waves A/B/C — 15 funds SCHEDULED | ✅ | Operator read every rendered message in `investor_waves_abc_preview.html` and approved 2026-09-07. Research: official contact routes verified per fund (only literally published emails used; no guessing). Template `outreach_investor` + `marketing/outreach/investor_waves_abc.json` + `scripts/schedule_investor_waves.py` (dry-run default, idempotent) + 8 tests green. Rows #59–#73 in `scheduled_outreach`: **11 on 09-08 (07:05–09:35 UTC) + 4 on 09-09**, 15-min stagger, within cap 15/day + window 07–17 UTC (combined with Vultr compliance wave: 14 then 6). Wave A→B→C order. **Rubio excluded** (official page excludes ESG/transparency tools); PBD/SE Ventures/Main Sequence deferred (research interrupted, operator call); 100x100/Dalus/DCVC have no published route (warm-intro only) |
| Pitch deck for DeepTechXL (Joel George, Analyst — replied 2026-09-07 asking for the deck) | ✅ | `marketing/outreach/deeptechxl_pitch_deck.pdf` (12 slides, 16:9) built by `scripts/build_deeptechxl_deck.py`; researched: Fund I €110M, tickets €100K–€2M, KET Digital Technologies × Sustainability/Security fit, portfolio hardware-heavy (framed via Stage-2 sensor testbed). Ask: **€850K pre-seed / 24 mo** (calibrated vs Dryad €1.8M, repath €1.2M, Mitiga €1.2M, Coolset €1.5M). IP: inbreng in natura into Dutch BV + CLA on tore + BOIP/EUIPO trademark + WBSO→Innovation Box. Reply goes from motaz3d@gmail.com (thread continuity), signature Talaix |

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
