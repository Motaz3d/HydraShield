# Compliance-First Strategy — Market Study, Decisions, Executive Plan

Operator mandate 2026-09-06: decide whether EU climate-compliance becomes the
core identity of Talaix, study competitors thoroughly, then execute a
programmatic + visual pivot and publish it. This document records the study,
the decisions (with reasons), and the executable plan. It supersedes the
directional notes in `docs/GRC_COMPLIANCE.md` (which stays as the phase tracker).

---

## 1. Decisions (answers to the operator's eight questions)

**Q1 — Should compliance be the core identity of the platform and the initiative?**
**Yes — as the market-facing identity (spearhead), with the multi-hazard engine
underneath unchanged.** Compliance spend is mandatory and deadline-driven;
discretionary "risk analytics" spend is postponable. The engine keeps serving
insurance/investment/government — but the front door, the hero message and the
first commercial funnel are now compliance. This is the third and (intended)
final positioning: not a pivot away from the engine, but a re-fronting of what
already exists (CsrdTX rules engine, XBRL output, four compliance products,
ESRS E1 brief + case study were all live before this decision).

**Q2 — Does risk become part of compliance operations?**
**Yes.** Hazard analytics stop being the product and become the *evidence layer
inside compliance workflows*. Product = audit-ready compliance evidence;
machinery = the multi-hazard engine. Insurance and investment remain supported
segments, not the headline.

**Q3 — EU companies, or global exporters operating in / exporting to the EU?**
**Both, sequenced.** Primary: EU in-scope companies (CSRD waves 1–2,
~12,000–15,000 post-Omnibus — estimate, not independently verified).
Secondary, and uniquely ours: non-EU companies — CSRD Wave 4 (non-EU groups
>€150M EU turnover, first reports FY2028) and EUDR operators/traders, where the
regulation is **already in force** (large operators 30 Dec 2025, SMEs 30 June
2026) and the required evidence is *geolocation-based* — exactly what our
satellite engine produces. The exporter angle is the least contested niche.

**Q4 — Do we cover all areas of EU compliance?**
**No — explicitly not.** We cover the *physical climate-risk evidence* layer:
CSRD/ESRS E1 physical risk (incl. E1-9 anticipated financial effects context),
EU Taxonomy DNSH climate adaptation (Appendix A vocabulary), EUDR geolocation
screening, plus the insurer/bank angles (EIOPA/Solvency II, EBA Pillar 3 ESG
ITS) that reuse the same evidence. We do NOT do: GHG/carbon accounting, ESRS
S/G standards, full reporting workflow, assurance/audit. Those are
integration-and-partner targets, not competitor territory (see §3).

**Q5 — New compliance engine, or build on the existing engines?**
**Build on what exists — no new engine.** CsrdTX (rules-as-data under
`config/csrd/`, XBRL output, `/api/v2/csrd`) shipped 2026-09-05; the hazard
engine (`tx_core` + `src.climate`) is mirrored open-source at `tore`. New work
is *layer depth*, not a new core: ESRS E1 datapoint mapping completeness,
E1-9 financial-effects context from the loss registries, scenario/time-horizon
fields. Engine changes keep following the tore mirror rule.

**Q6 — Does this serve the initiative (profit + distinctive service)?**
**Yes.** (a) Buyers purchase because law forces them to, on a published
calendar — the sales trigger exists before outreach. (b) We already built
~80% of the surface; marginal cost per served customer is near zero (automated
engine, no consultants). (c) Distinctiveness: no competitor combines global
multi-hazard coverage + evidence-class honesty + open-source engine +
transparent low pricing (see §4).

**Q7 — Can we compete, how, and what are the odds?**
**How:** price transparency against opaque enterprise contracts
(€19–39 per report, €49–249/mo tiers vs typical five-to-seven-figure annual
deals); standalone evidence packs vs bundled suites; auditability
(evidence classes, public source registry, open engine) vs black boxes;
global coverage vs US- or Europe-centric vendors.
**Odds, honestly:** first pilot customers within months — realistic, because
the pilot programme trades price for publishable case studies and the product
already works. Becoming the default evidence layer feeding one mid-size GRC
suite — plausible over 1–2 years. Displacing suites or winning Tier-1 banks
head-on — not realistic at our size. **Cervest's 2024 collapse is the
cautionary case**: cheap analytics alone failed. Our difference vs Cervest:
mandatory-deadline pull (not discretionary analytics) and near-zero delivery
cost (engine, not consultants). The risk is real and stated.

**Q8 — The plan:** §5.

---

## 2. Regulatory state (verified 2026-09-06)

### Wave calendar

| Regulation | Population | First reports | Status |
|---|---|---|---|
| CSRD Wave 1 | Large PIEs (>500 employees, ex-NFRD) | FY2024 (published 2025) | In force |
| CSRD Wave 2 | Other large undertakings | FY2027 (published 2028) | In force; +2y delay (Dir. (EU) 2025/794) |
| CSRD Wave 3 | Listed SMEs etc. | FY2028 (published 2029) | In force; Omnibus proposes removal |
| CSRD Wave 4 | Non-EU >€150M EU turnover | FY2028 (published 2029) | In force |
| Simplified ESRS | All in-scope | — | Adopted 3 July 2026; pending application |
| EUDR | Large operators/traders | 30 Dec 2025 | **In force now** |
| EUDR | SME/micro operators | 30 June 2026 | **In force now** |
| CSDDD | >€1.5B turnover | 26 July 2027 | In force |
| CSDDD | >€900M turnover | 26 July 2028 | In force |
| California SB 261 | >$500M revenue in CA | 1 Jan 2026 | In force (physical-risk report) |

Sources: EUR-Lex CELEX:32022L2464, 32024L1760, 32023R1115; Directive (EU)
2025/794 ("stop-the-clock"); EC corporate-sustainability-reporting timeline
(Omnibus political agreement 9 Dec 2025; simplified ESRS adopted 3 July 2026);
leginfo.legislature.ca.gov (SB 261). Post-Omnibus CSRD population
(~12,000–15,000, down from ~50,000) is an **estimate, not independently
verified**; Omnibus scope final adoption not confirmed on EUR-Lex as of today —
our `config/csrd/` registry correctly still marks those rules "proposed".

### What ESRS E1 demands for physical risk (our product surface)

Site coordinates of material assets; hazard screening at those coordinates
(acute: flood, wildfire, storm, heat — chronic: heat stress, water stress,
sea-level rise); evidence status per result; stated limitations; scenario
analysis across time horizons; anticipated financial effects (E1-9);
double-materiality union. Every one of these maps to an existing Talaix
capability (`config/csrd/esrs_2023.json`, sustainability evidence pack,
evidence classes OBSERVED→UNKNOWN).

---

## 3. Competitor study (verified 2026-09-06)

### A. CSRD/ESG reporting suites — the physical-risk gap

17 vendors profiled (Workiva, Position Green, IBM Envizi, SAP SCT, Diligent,
Enablon, Sphera, Greenly, Sweep, Persefoni, Watershed, Normative, osapiens,
Atlas Metrics, Clarity AI, EcoVadis + 2 unverifiable). **Finding: none except
Clarity AI claims to generate physical climate-risk evidence** — they are
workflow + carbon accounting + XBRL tagging platforms. Customers bring
physical-risk evidence via consultants. → **The suites are our integration
targets and channel partners, not our competitors.** Clarity AI (custom
pricing, financial-institution focus) is the single partial overlap.

### B. Physical climate-risk specialists — the pricing gap

16 vendors profiled (Jupiter, Climate X, Sust Global→ISS STOXX, Mitiga
EarthScan, repath, Correntics, XDI, First Street→MSCI ~$120M, Moody's/RMS $2B,
MSCI, S&P→The Climate Service, Risilience, Cervest†2024, Verisk, Swiss Re /
Munich Re platforms, CLIMADA). **Findings:**
- No published list prices anywhere; typical deals are five-to-seven-figure
  annual enterprise contracts.
- ESRS E1 evidence explicitly claimed by Mitiga, XDI, Moody's, Climate X —
  but only bundled inside expensive platforms. **Nobody sells a cheap,
  standalone, transparently priced evidence pack.**
- SME/mid-market essentially unserved; CLIMADA is open-source but
  research-grade (no compliance workflow, no audit trail, no API product).
- Consolidation (MSCI, ISS STOXX, Workiva, S&P, Moody's acquisitions) proves
  physical-risk evidence is a *must-have layer* the suites are absorbing.

### The gap we occupy

Transparently priced, audit-traceable, globally covered physical climate-risk
evidence for EU compliance — sold per report and per month, not per six-figure
contract; with an open-source engine (`tore`, EUPL-1.2) and a public source
registry as the trust anchor. Position: **"the evidence layer"** — feed GRC
suites and consultants; serve directly the companies below the enterprise
tier they ignore.

---

## 4. Positioning & messaging (executed in this wave)

- Homepage hero → compliance-first (CSRD/ESRS E1, EU Taxonomy DNSH, EUDR).
- Primary nav → Compliance dropdown first.
- `llms.txt` + footer brand line → compliance-evidence framing.
- Honesty contract unchanged and foregrounded — it is the differentiator
  auditors respond to ("unavailable is stated, never filled in").
- Claims discipline: "evidence layer, not assurance" everywhere; no
  accreditation claims; Omnibus-proposed rules shown as proposed.

## 5. Executive plan (programmatic + visual)

| Phase | Deliverable | Status |
|---|---|---|
| P0 — study & decisions | this document | ✅ 2026-09-06 |
| P1 — identity pivot | hero/meta/nav/footer/llms.txt → compliance-first; compliance.html wave calendar; marketing segments +2 (sustainability/compliance officers, EUDR operators) | this wave |
| P2 — funnel | CSRD scope-checker as free front door (exists at sustainability.html — sharpen as landing); pricing page already live; pilot programme push for first customer | 🔶 next |
| P3 — product depth | ESRS E1 datapoint-coverage map published per report; E1-9 financial-effects context from loss registries; scenario/time-horizon fields in packs | ⬜ |
| P4 — channel | outreach wave to 2–3 GRC suites + 5 consultancies/auditors (evidence-layer partnership); EUDR exporter outreach (non-EU commodity traders) | ⬜ |
| P5 — proof | first pilot customer → publishable case study (existing pilot terms); trust page (security/GDPR posture) for procurement | ⬜ |

First-customer motion: free CSRD scope check → €19–39 sample evidence pack on
their own sites → €490 pilot → subscription. Every step is self-serve and
already built except the outreach itself.

## 6. What we deliberately do NOT do

- No GHG accounting, no S/G standards, no assurance services, no full GRC
  workflow suite.
- No new engine; no tearing out insurance/investment surfaces (they stay,
  demoted from headline to segments).
- No fabricated urgency: Omnibus-proposed items are presented as proposed.
