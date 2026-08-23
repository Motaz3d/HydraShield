# Talaix — Sustainability & Funding Intelligence

**Status:** implemented core (taxonomy, funding knowledge base, match
engine, `/api/v2/funding`, funding page, marketing integration); research
and activation items marked. Sustainability and funding are **core product
capabilities**, not content pages.

The chain this layer implements:

```
CLIMATE EXTREME → EVIDENCE → EXPOSURE → PROBLEM
→ SUSTAINABLE SOLUTION → FUNDING → FINANCE → INVESTMENT
→ IMPLEMENTATION → MONITORING → OUTCOME
```

## 1. Sustainability as a platform layer

Sustainability intelligence reuses the existing platform substrate — the
hazard ontology, evidence architecture, provenance, Solutions
Intelligence, Economic Intelligence — and adds two curated knowledge
bases:

- `config/sustainability_taxonomy.json` — classifies the platform's
  solution classes by environmental objective, adaptation/mitigation
  character and approach type, referencing `solutions_knowledge.json`
  entries (never duplicating them). Objectives with no curated solution
  class are deliberately absent.
- `config/funding_knowledge.json` — real funding programmes with official
  URLs (15 at curation: LIFE, Horizon Europe, Interreg, EIC, EIB, EIF,
  InvestEU, ERDF, Cohesion Fund, CAP/EAFRD, Digital Europe, UCPM, GCF,
  GEF, World Bank climate).

Every sustainability/funding statement connects problem → hazard →
location → evidence → solution → limitations → source.

## 2. Funding record model

Each programme record: `id, name, programme, funding_body, jurisdiction,
funding_type[], sector[], hazards[], sustainability_objectives[],
adaptation, mitigation, nature_based, technology, beneficiary_types[],
eligibility, funding_amount, funding_rate, cofinancing, deadline, status,
official_url, source, date_published, date_checked, evidence_type,
confidence, limitations, hydrashield_relevance, recommended_action`.

**Critical honesty rules:**

- `funding_amount`, `funding_rate`, `deadline`, call status are stated
  only when officially published; otherwise **"not stated"** /
  **"not currently verified"**. All 15 curated records currently carry
  honest unverified values — the curation note says so.
- **Funding types are distinguished**: grant, loan, equity, guarantee,
  blended finance, technical assistance, prize, procurement, tax
  incentive. Funding is not free money; the type is always displayed.
- Eligibility summaries are indicative; the official programme text
  governs. No eligibility is assumed from a programme's climate relevance.

## 3. Funding match engine (`src/climate/funding.py`)

Deterministic screening, explainable per match — the same discipline as
the solutions engine:

- **Gates**: hazard overlap; beneficiary type (when given);
  jurisdiction (EU programmes ↔ EU member states; GCF/GEF/World Bank ↔
  their target countries — the rule is stated in each match).
- **Fit**: `matched_dimensions / relevant_dimensions` over the optional
  context (sector, sustainability objective, adaptation/mitigation,
  nature-based, technology), with the matched dimensions quoted.
- **Per match**: why it matches, what is supported, who may apply,
  eligibility note, `not_verified` list, deadline, official source,
  limitations, recommended action. Always with the disclaimer:
  *potential sources — eligibility requires verification — not financial
  advice — no funding guaranteed.*

API: `GET /api/v2/funding?hazards=…&sector=…&beneficiary=…&country=…`
(20/min/IP). UI: `funding.html` (in the primary nav), linked contextually
from the solutions page ("find potential funding for these solutions").

## 4. Location → funding chain

The product path: analyze a place (hazard) → exposure → solutions →
funding. Today the solutions page hands the hazard context to
`funding.html`; the caller selects sector/applicant/country and gets
matched programmes. A future iteration can pass site-derived context
(country from geocoding, sectors from the inferred site sectors)
automatically — additive, never silently assumed.

## 5. Sustainability profile & report (architecture)

A location's sustainability profile assembles: location, hazards,
environmental conditions, exposure, sustainability challenges,
recommended solutions (Solutions Intelligence), potential funding
(Funding Intelligence), implementation considerations, monitoring
indicators. This becomes a report section when the report engine gains
it — the PDF report extension is **DEFERRED** until the profile content
is proven against real locations; nothing monetary is ever invented
(assumptions and sources must be explicit).

## 6. Finance/investment connection

Opportunities are classified per beneficiary type (municipality,
government, company, investor, bank, insurer, infrastructure owner,
research institution, NGO, agricultural organization) and per instrument
(public grant / public loan / private investment / blended finance /
technical assistance). No ROI, no avoided-loss figures: monetary
statements require documented values with assumptions — the same rule as
`resilience_economics` in Solutions Intelligence.

## 7. Commercial radar integration

- `marketing/segments/segments.json` gained 10 sustainability segments
  (municipal climate adaptation, sustainable finance, green investment,
  environmental consulting, engineering firms, water management,
  EU-funded projects, technology providers, infrastructure, forestry).
- The copilot `funding` command reports the EU-funding ledger +
  platform KB state; the `radar` command ranks leads including their
  funding/programme signals.
- EU funding marketing logic: FUNDING SIGNAL → project/organization →
  problem → hazard → Talaix capability → relevance → contact
  strategy — all from official programme/project sources, no scraping,
  no auto-contact.

## 8. Monthly intelligence (design, NOT sending)

*Monthly Talaix Climate & Sustainability Intelligence* — a future
subscriber product: new documented events, new funding opportunities,
new solutions/technology, policy developments, personalized by country/
sector/hazards/saved locations. Architecture: subscriber preference
records (existing alert_prefs pattern extended) + a monthly compilation
job. **Not implemented and never sent until explicitly configured** —
activation requires its own consent and audit design.

## 9. Map & QGIS futures (documented, not implemented)

- Map: future layers for funded climate projects, nature-based projects,
  restoration, adaptation infrastructure — each with source/date/
  resolution/status/provenance, lazy-loaded, off by default. No such
  layer ships without a real, queryable source.
- QGIS: future Processing algorithms `hydrashield:find_solutions` and
  `hydrashield:find_funding` ride the same API (`/api/v2/solutions`,
  `/api/v2/funding`) — documented in
  `docs/QGIS_INTEGRATION_ARCHITECTURE.md`; not yet implemented in the
  Phase 0 plugin.

## 10. Annual report connection

The Annual Climate Extreme Intelligence Report
(docs/ANNUAL_CLIMATE_EXTREME_REPORT.md) gains sustainability dimensions:
documented adaptation responses, the funding landscape (from curated
programme records with date_checked), solutions evidence, and lessons —
all under the same sourcing rules. No annual rankings are fabricated;
each figure requires its authoritative source and reference period.
