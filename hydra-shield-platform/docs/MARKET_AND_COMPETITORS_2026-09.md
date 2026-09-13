# Talaix — Market & Competitor Study (September 2026)

**Status:** operator-requested study, saved 2026-09-12. Complements
`COMPLIANCE_STRATEGY.md` (the compliance-pivot study + decisions) and
`marketing/outreach/lsa_package/Talaix_Business_Plan.md`. Does not supersede
either.

**Scope:** the core product — globally covered, multi-hazard physical
climate-risk **evidence** for EU disclosure (CSRD/ESRS E1, EU Taxonomy DNSH,
EUDR), sold as standalone, transparently priced packs and subscriptions.

**Method & verification status (read this first).** The findings below come
from (a) the repository's own dated research — `COMPLIANCE_STRATEGY.md`
(33 vendors profiled, checked 2026-09-06), `PRICING.md`,
`marketing/segments/segments.json`, `docs/ECONOMIC_INTELLIGENCE.md` — and
(b) **live web verification on 2026-09-12** of the physical-risk specialists
(§5A): vendor sites and press sources, each fact carrying a URL in §Sources.
The CSRD/ESG suites (§5B) and EUDR tooling (§5C) live re-check was started
but not completed, so those two sections rest on the internal record and are
marked accordingly; re-verify them before external use. The binding project
rule applies: no fabricated content — where no documented figure exists,
that is stated.

---

## 1. Executive summary

Talaix sells the **physical climate-risk evidence layer** that EU disclosure
law now requires. The market is driven by **mandatory, deadline-bound spend**,
not discretionary "risk analytics" spend — the single most important
difference from generic climate-risk software.

1. **CSRD/ESG reporting suites do not generate physical-risk evidence.**
   Customers bring it via consultants. → They are our **integration targets
   and channel partners**, not competitors.
2. **Physical-risk specialists publish no prices** and sell opaque
   five-to-seven-figure enterprise contracts. → **The gap: nobody sells a
   cheap, standalone, transparently priced evidence pack.**
3. **The SME/mid-market is effectively unserved** — the largest buyer pool
   behind CSRD wave 2 and EUDR.

**The gap we occupy:** a transparently priced, audit-traceable, globally
covered evidence layer, with an open-source engine (EUPL-1.2) as the trust
anchor — sold per report and per month, not per enterprise contract.

---

## 2. Market drivers — regulatory calendar

Verified against `COMPLIANCE_STRATEGY.md` §2 (checked 2026-09-06); the Omnibus
outcome was additionally confirmed via a 2026 search result.

| Regulation | Population | First reports | Status |
|---|---|---|---|
| CSRD Wave 1 | Large PIEs (>500 employees, ex-NFRD) | FY2024 (published 2025) | In force |
| CSRD Wave 2 | Other large undertakings | **FY2027 (published 2028)** | In force; +2y delay (Dir. (EU) 2025/794) |
| CSRD Wave 3 | Listed SMEs etc. | FY2028 (published 2029) | In force; Omnibus proposes removal |
| CSRD Wave 4 | Non-EU >€150M EU turnover | FY2028 (published 2029) | In force |
| Simplified ESRS | All in-scope | — | **Adopted 3 July 2026** |
| **EUDR** | Large operators/traders | **30 Dec 2025** | **In force now** |
| **EUDR** | SME/micro operators | **30 June 2026** | **In force now** |
| CSDDD | >€1.5B turnover | 26 July 2027 | In force |
| CSDDD | >€900M turnover | 26 July 2028 | In force |
| California SB 261 | >$500M revenue in CA | 1 Jan 2026 | In force (physical-risk report) |

**Omnibus outcome (2025–2026):** two-year delay for waves 2–3, employee
threshold raised to 1,000, scope reduced by roughly 80%, simplified ESRS
cutting mandatory datapoints (reported up to ~60%). Post-Omnibus CSRD
population is estimated at **~12,000–15,000** companies (down from ~50,000) —
this is an **estimate, not independently verified**; `config/csrd/` correctly
marks Omnibus-proposed rules as *proposed*, never as law.

**What ESRS E1 demands for physical risk** (our product surface): site
coordinates of material assets; acute + chronic hazard screening at those
coordinates; evidence status per result; stated limitations; scenario
analysis across time horizons; anticipated financial effects (E1-9);
double-materiality union. Every item maps to an existing Talaix capability.

---

## 3. Who buys — bottom-up (no fabricated TAM)

- CSRD wave-2 companies — the **FY2027 reporting year** is the buying season.
- **EUDR operators/traders** — in force now; the required evidence is
  **geolocation-based**, exactly what the engine produces. Non-EU exporters
  selling into the EU are the least-served cohort.
- Banks and insurers under EBA Pillar 3 ESG ITS / EIOPA Solvency II — reuse
  the same evidence.
- Municipalities and governments — adaptation evidence + funding applications.

`docs/ECONOMIC_INTELLIGENCE.md` deliberately avoids market-size marketing:
"market claims follow the same evidence rules (source + reference period +
method) as climate claims." This study honours that rule — see §4.

---

## 4. Market size & trends — stated honestly

Published estimates for the climate-risk analytics / ESG software market sit
in the low single-digit **billions of USD per year** with high growth
(roughly 20%+). These were **not verified in this session** and are therefore
**not** used as a planning number. The defensible figure is the bottom-up
buyer count in §3.

Trends that matter:

- **Consolidation proves the layer is a must-have.** MSCI–First Street
  (~$120M, recorded in `COMPLIANCE_STRATEGY.md`), ISS STOXX–Sust Global,
  Moody's–RMS (~$2B), S&P–The Climate Service. The reporting suites are
  absorbing the physical-risk layer.
- **Earth observation + AI** are the cost curve behind cheap, global,
  site-level evidence.
- **Mid-market demand** is rising and structurally ignored by enterprise
  vendors.

---

## 5. Competitor map

### A. Physical climate-risk specialists (the real field)

Profiled in `COMPLIANCE_STRATEGY.md` §3B: Jupiter, Climate X, Sust Global→ISS
STOXX, Mitiga EarthScan, repath, Correntics, XDI, First Street→MSCI, Moody's/RMS,
MSCI, S&P→The Climate Service, Risilience, Cervest†2024, Verisk, Swiss Re /
Munich Re, CLIMADA.

| Vendor | Sells | Segment | Pricing | Note (verified live 2026-09-12 unless dated) |
|---|---|---|---|---|
| Climate X (UK) | Asset-level physical risk: Spectra + Adapt (adaptation Capex/ROI) + Carta (18.7M-company footprint) | Banks, insurers, real estate | Not published | **ESRS E1 claim verified** — dedicated page `climate-x.com/regulation/esrs` |
| Jupiter Intelligence (US) | ClimateScore Global analytics | Banks, utilities, government | Enterprise, opaque | **No explicit ESRS/CSRD/E1 wording found on site** (generic "disclosure & compliance" only); Arcadis partnership 2026-06 |
| Mitiga Solutions (ES) | EarthScan physical risk (Disclose module) | Finance/industry | Not published; "adaptive pricing" + free trial of EarthScan Pro | Claims CSRD, IFRS S2, TCFD, EU Taxonomy, SB 261 — **explicit "E1" not found** |
| XDI (AU) | Infrastructure physical risk | Banks, governments | Not published | Claims CSRD, TCFD, EU Taxonomy, ISSB, SEC — **explicit "E1" not found** |
| Correntics (CH) | Supply-chain climate risk | Industry | Not published | Narrow focus (internal record) |
| First Street → MSCI | Flood/fire/heat models | Public/research | — | **Acquisition verified: completed 3 Aug 2026, $120M cash + earn-out** (announced 24 Jun 2026) |
| Sust Global → ISS STOXX | Physical risk | Investors | — | **Acquisition verified (undisclosed price)**; sustglobal.com now serves ISS STOXX Climate & Nature Analytics |
| Moody's RMS · S&P · MSCI · Verisk | Cat + climate risk | Institutions | Large enterprise | Deep entrenchment (internal record) |
| Risilience (UK) | Climate risk analytics (Riise platform) | Institutions | Enterprise | Active; $26M Series B (~2023); Cambridge Risk Centre spin-out |
| Swiss Re / Munich Re | Location risk platforms | Insurance | Enterprise | Proprietary cat data (internal record) |
| CLIMADA (ETH) | Open-source risk model | Research | Free | No compliance workflow/API product (internal record) |
| Cervest (UK)† | Asset-level risk platform | — | — | **Collapse verified: administration May 2024 (Interpath); cervest.earth now redirects to Mitiga EarthScan** |

**Finding (internal record 2026-09-06, live-checked 2026-09-12):** no
published list prices anywhere — re-confirmed on every specialist site
checked (the only pricing signal found: Mitiga's free trial of EarthScan
Pro); typical deals are five-to-seven-figure annual contracts. The explicit
ESRS **E1** claim is verified for **Climate X only**; Mitiga and XDI claim
CSRD alignment without naming E1, and Jupiter's site shows no EU-framework
wording at all. **Nobody sells a cheap, standalone, transparently priced
evidence pack** — and a 2025–2026 scan found **no new entrant** doing so.

### B. CSRD/ESG reporting suites — partners, not competitors

Profiled in `COMPLIANCE_STRATEGY.md` §3A (17 vendors): Workiva, Position
Green, IBM Envizi, SAP Sustainability Control Tower, Diligent, Enablon,
Sphera, Greenly, Sweep, Persefoni, Watershed, Normative, osapiens, Atlas
Metrics, Clarity AI, EcoVadis (+2 unverifiable).

**Finding:** none except **Clarity AI** claims to generate physical
climate-risk evidence — they are workflow + carbon accounting + XBRL tagging
platforms. Customers bring physical-risk evidence via consultants. → They are
our **integration targets**; outreach is already live (Tier-1 in
`marketing/outreach/compliance_wave1.md`).

### C. EUDR-specific tooling — partial overlap, least-contested market

osapiens (strong in EUDR/CSRD/CSDDD — recorded in `COMPLIANCE_STRATEGY.md`),
Satelligence, Meridia, TraceX, Koltiva, Livelihoods *(these five from general
market knowledge — not in the internal record and not yet live-verified)*;
free references: Trase / Global Forest Watch.

**Opportunity:** **non-EU exporters** shipping the seven commodities into the
EU lack affordable EU-facing evidence tooling. This is the least-contested
niche (also flagged on the DeepTechXL deck: "Least-contested niche: non-EU
exporters").

### D. Free / public alternatives

CLIMADA (open model), ThinkHazard (GFDRR), WRI Aqueduct, Copernicus CDSE,
Climate Central, NOAA/FEMA. **Why they are not enough:** no compliance layer,
no audit trail, no product API, no ESRS E1-ready pack — raw material, not a
product.

---

## 6. Head-to-head

| Dimension | Physical-risk specialists | CSRD/ESG suites | Talaix |
|---|---|---|---|
| Generates physical-risk evidence | ✅ | ❌ | ✅ |
| Published pricing | ❌ (5–7 figures) | Partial | ✅ (€19–249/mo) |
| Self-serve / instant | ❌ | Partial | ✅ |
| Source/method/status on every value | Rare | N/A | ✅ (evidence classes) |
| Open-source engine | ❌ | ❌ | ✅ (EUPL-1.2) |
| Global multi-hazard coverage | Partial | N/A | ✅ (10 hazards) |
| Serves SME / mid-market | No | Yes, but no physical evidence | ✅ |

---

## 7. The gap we occupy

Transparently priced, audit-traceable, globally covered physical climate-risk
evidence for EU compliance — sold per report and per month, with an
open-source engine and a public source registry as the trust anchor.
Position: **"the evidence layer"** — feed the GRC suites and consultants;
serve directly the companies below the enterprise tier they ignore.

---

## 8. Risks (stated honestly)

1. **Cervest 2024** — cheap analytics alone failed. Our difference:
   mandatory-deadline pull (not discretionary analytics) and near-zero
   delivery cost (engine, not consultants).
2. **Consolidation** — the suites keep absorbing the layer. This also makes
   us a plausible integration/acquisition target, not an existential threat.
3. **Regulatory uncertainty** — Omnibus narrowed CSRD scope; mitigated by
   serving multiple frameworks (CSRD + EUDR + EIOPA/EBA).
4. **Validation pending** — all outputs are screening-level and labelled as
   such; validation roadmap with a research partner targets 2027.
5. **Scale** — head-on displacement of Tier-1 vendors is unrealistic; the
   path is evidence-layer partnership + the mid-market.

---

## 9. Strategic priorities

### 9.1 Operator directive 2026-09-12 — EUDR exporters are the top angle

**Ruling (operator):** the non-EU exporter / EUDR geolocation direction is the
**least-contested** market for Talaix. It is therefore raised to **top
outreach priority**, and it must be **presented in correspondence from
2026-09-20 onward**.

**Implemented in the codebase:**

- Dedicated template `src/dashboard/email_templates/outreach_eudr_exporters.txt`
  (registered in `mailer._TEMPLATE_NAMES`), framed for EU-bound commodities
  and non-EU exporters; honesty boundary stated on every output ("screening
  evidence with declared gaps — never a deforestation-free claim, never EUDR
  compliance verification").
- `scripts/backfill_daily.py`: `eudr_operators` is **always in the pool** (the
  daily send volume is never reduced); from `_EUDR_PRIORITY_FROM = 2026-09-20`
  it moves to the **top** of `_PRIORITY` and is presented with the new
  template. Before that date EUDR leads keep their previous position and the
  generic compliance message.
- Tests: `tests/test_eudr_outreach.py` + updated `tests/test_backfill_daily.py`.

**Enabling dependency:** verified EUDR-exporter contacts. ~39 `eudr_operators`
leads are already in the store (incl. non-EU exporters: Mewah Group SG, Kuala
Lumpur Kepong MY, Amaggi BR). The bottleneck remains verified contacts — bulk
`discover_contacts.py` runs and external research batches (imported via
`scripts/import_contacts.py`, `verification: OBSERVED`) are the unlock.

### 9.2 Other priorities

1. Concentrate the wedge on the **FY2027 CSRD buying season** and **EUDR**
   (in force now) — the two non-deferrable drivers.
2. **Turn the suites into a channel** (evidence-layer integration), not
   competitors — outreach already running.
3. Keep **published pricing** as the structural differentiator — never drift
   to "contact us". The 2026-09-12 live re-check confirmed this gap persists:
   still no list prices at any specialist, and no new self-serve entrant.
4. Re-verify §5B (suites) and §5C (EUDR tools) figures before external use —
   the live pass on 2026-09-12 covered §5A only.

---

## Sources & verification status

- `docs/COMPLIANCE_STRATEGY.md` — 33-vendor competitor study + regulatory
  calendar, checked 2026-09-06 (verified).
- `docs/PRICING.md`, `marketing/segments/segments.json`,
  `docs/ECONOMIC_INTELLIGENCE.md` (verified).
- `marketing/outreach/lsa_package/Talaix_Business_Plan.md` §4, §7 (verified).
- Omnibus outcome: one 2026 search result (wave-2 FY2027, wave-3 FY2028, ~80%
  scope cut, 1,000-employee threshold, simplified ESRS) — consistent with the
  internal record.
- **Live verification 2026-09-12 (physical-risk specialists, §5A):**
  - Climate X — Spectra/Adapt/Carta verified, ESRS E1 page verified:
    `climate-x.com/spectra`, `climate-x.com/regulation/esrs`.
  - Jupiter — ClimateScore Global verified (`jupiterintel.com/climatescore-global`);
    no ESRS/CSRD/E1 wording on site; Arcadis partnership 2026-06 (news snippet).
  - Mitiga — EarthScan verified; CSRD/IFRS S2/TCFD/EU Taxonomy/SB 261 claims
    verified on `mitigasolutions.com`; explicit "E1" not found; free trial of
    EarthScan Pro, no price list.
  - XDI — CSRD/TCFD/EU Taxonomy/ISSB/SEC claims verified on `xdi.systems`;
    explicit "E1" not found.
  - First Street → MSCI — completed 3 Aug 2026, $120M cash + earn-out:
    Business Wire via Morningstar, 2026-08-03; RTTNews/dpa-AFX, 2026-06-24.
  - Sust Global → ISS STOXX — verified (undisclosed; Yahoo Finance headline
    via search snippet); `sustglobal.com` now serves ISS STOXX content.
  - Risilience — Riise platform live (`risilience.com`); $26M Series B ~2023
    (news snippet).
  - Cervest — administration May 2024, administrators Interpath (Evening
    Standard, 2024-05-23); `cervest.earth` redirects to Mitiga EarthScan.
  - New-entrant scan 2025–2026: none found with published self-serve pricing.
- §5B (CSRD/ESG suites) and §5C (EUDR tools): internal record only —
  live re-check started 2026-09-12 but not completed; **[unverified — re-check]**.
