# CsrdTX — CSRD/ESRS Regulatory Intelligence Engine

**Status:** Wave 1 shipped 2026-09-05 (engine `1.0.0`). This document is the
architecture specification and the living roadmap for the CSRD capability of
the Talaix platform (`talaix.com/sustainability.html`).

Related: `docs/SUSTAINABILITY_REPORTING.md` (evidence pack API),
`docs/PRICING.md` (source of record for prices), `docs/EVIDENCE_ARCHITECTURE.md`.

---

## 1. Why an engine, not a report template

CSRD/ESRS is a moving target: the 2023 ESRS set (Delegated Regulation (EU)
2023/2772), the Omnibus I proposal (COM(2025) 80), the "stop-the-clock"
Directive (EU) 2025/794, and the simplified ESRS adopted 2026-07-03 (mandatory
datapoints reduced by more than 60%, pending scrutiny and publication) all
change *who* reports *what* and *when*. A hard-coded report generator breaks
on every amendment. CsrdTX therefore follows one rule:

> **Rules are data, not code.** Regulatory knowledge lives in versioned JSON
> documents under `config/csrd/`, each with a legal status and a source. A
> regulatory update is a data change — a new version document or changelog
> entry — never an engine rewrite.

Every assessment pins the exact rule set and ESRS version it used, so any
output remains reproducible and auditable after the law changes.

## 2. Architecture

```
config/csrd/                          ← regulatory knowledge base (data)
├── applicability_rules.json          ← versioned scope rule sets + wave calendar
├── esrs_2023.json                    ← ESRS 2023/2772 structure (in force)
├── esrs_2026_simplified.json         ← simplified ESRS (adopted, pending application)
└── changelog.json                    ← regulatory watch: dated events, statuses

src/climate/csrd/                     ← the engine (no Flask, pure functions)
├── regulations.py                    ← KB loader; version/rule-set selection by year + status
├── applicability.py                  ← scope screening: in_scope / out_of_scope /
│                                       potentially_in_scope / requires_legal_confirmation
├── materiality.py                    ← double materiality scoring (documented math)
├── readiness.py                      ← 0–100 readiness composite + gap analysis
└── engine.py                         ← orchestration → one sealed assessment object

src/climate/api_csrd.py               ← Flask blueprint /api/v2/csrd/…
website/sustainability.html + js      ← applicability check + regulatory watch UI
tests/test_csrd_engine.py             ← 30 tests, fully offline
```

Legal status is first-class: `in_force`, `adopted_pending_application`,
`proposed`. Only `in_force` rules drive determinations. Proposed rules
(Omnibus I) are evaluated separately and returned as a labelled *forward
outlook* — never silently applied.

## 3. The math (deterministic, documented, tested)

### 3.1 Applicability

- EU size test (in force, Directive 2013/34/EU as updated by (EU) 2023/2775):
  "large" = at least 2 of 3 criteria exceeded — employees > 250,
  net turnover > €50M, balance sheet > €25M.
- Each criterion evaluates to `met` / `not_met` / `unknown`. Missing facts are
  never guessed: unknowns that can flip the outcome yield
  `potentially_in_scope`; legal facts the engine cannot verify yield
  `requires_legal_confirmation`.
- Wave mapping follows the wave calendar (wave 1 FY2024; waves 2–3 delayed two
  years by (EU) 2025/794 → FY2027/FY2028; wave 4 non-EU Art. 40a → FY2028).
- Omnibus forward outlook: employee threshold (>1000) modelled as a hard gate
  plus one financial criterion, per the proposal's structure.

### 3.2 Double materiality

- `severity = (scale + scope + irremediability) / 3` — each scored 0–5.
- `impact_score = severity` (actual impacts) or `severity × likelihood`
  (potential impacts, likelihood ∈ [0,1]).
- `financial_score = magnitude × likelihood` — magnitude 0–5.
- `combined_score = max(impact_score, financial_score)` — double materiality
  is a **union**, not an average: either perspective alone can make a topic
  material. `material = combined_score ≥ threshold` (default 2.5).
- `confidence = mean(evidence weights)` with A=1.0, B=0.85, C=0.7, D=0.5
  (company-declared), E=0.3, F=0.0 (unavailable).
- E1 financial materiality is seeded from the platform's real physical-hazard
  verification: hazard level labels map to magnitudes (very high 4.5 … very
  low 0.5), likelihood = share of sites at moderate-or-higher exposure
  (floored at 0.3), evidence grade B (modelled from real data, screening-level,
  not actuarial).

### 3.3 Readiness composite (0–100)

| Component | Weight | What it measures |
|---|---|---|
| applicability_clarity | 0.20 | Definitiveness of the scope determination |
| evidence_coverage | 0.35 | Disclosure requirements backed by evidence vs declared gaps |
| data_completeness | 0.15 | Company profile facts + resolved site data |
| materiality_readiness | 0.30 | Topical standards assessed at confidence ≥ 0.5 |

Overall = weighted sum. Every point is traceable to a component and every
component to its inputs; the score is descriptive, never promotional.

### 3.4 Never invent (architecture, not slogan)

Every datapoint and every materiality perspective carries a controlled status:
`VERIFIED`, `SUPPORTED`, `COMPANY_DECLARED`, `INFERRED`, `UNAVAILABLE`,
`NOT_ASSESSED` — always with a reason. Topics without evidence are emitted as
`NOT_ASSESSED` with `null` scores. There is no code path that fabricates a
value.

## 4. API

Base: `/api/v2/csrd` (registered in `src/dashboard/api.py`).

| Endpoint | Auth | Description |
|---|---|---|
| `GET /regulations` | public | ESRS versions, wave calendar, rule sets, changelog |
| `POST /applicability` | registered | Scope screening for a company profile |
| `POST /assessment` | registered | Full assessment: applicability + materiality + coverage + readiness + gaps + TX seal. Sites ≤25 free, ≤100 subscriber (existing `ROLE_RANK` gate) |
| `POST /assessment/xbrl` | registered | Machine-readable assessment: `format=xbrl` (XBRL 2.1 instance, default) or `format=ixbrl` (inline-XBRL XHTML). Same limits |

Every assessment is content-hashed (`assessment_id`), engine-versioned, and
sealed (`authenticity.code`, TX-XXXX-XXXX-XXXX) like all Talaix products.

### 4.1 XBRL output (machine-readable)

- Facts use the documented **Talaix extension namespace**
  (`https://talaix.com/xbrl/taxonomy/csrd/2026`). The element mapping is data
  (`config/csrd/xbrl_mapping.json`); the served taxonomy
  `website/xbrl/csrd/2026/talaix-csrd.xsd` mirrors it, and
  `tests/test_csrd_xbrl.py` keeps the two in sync.
- **Never invent applies to tags too:** a missing value emits no fact and is
  listed in the document's tagging notes. NOT_ASSESSED topics produce no
  topic facts.
- Entity identifier: the company's **LEI** when supplied (ISO 17442 scheme,
  as in ESEF); otherwise a content-hash identifier under
  `https://talaix.com/entity`.
- **Declared gap, stated in every document:** anchoring to the official ESRS
  digital (XBRL) taxonomy. Extension elements are only mapped to official
  ESRS element names once verified against the published taxonomy files —
  never guessed. The output is a machine-readable assessment extract, not an
  ESEF filing package.

## 5. Pricing placement (decision, 2026-09-05)

Per the norms in `docs/PRICING.md` (conversion through value; the free tier
stays genuinely useful; payment appears at added value), CsrdTX slots into the
**existing tiers — no new prices, no price changes**:

- **Free (€0)** — public regulatory reference: `/regulations`, ESRS versions,
  wave calendar, regulatory watch. This is the trust builder.
- **Professional (€49/mo)** — applicability checks and full CsrdTX
  assessments for portfolios up to 25 sites (screening-level), alongside the
  existing sustainability-evidence sections.
- **Business (€249/mo)** — assessments up to 100 sites under one organization,
  gap analysis and readiness tracking for reporting annexes (alongside the
  existing evidence pack).
- **Enterprise (custom)** — portfolio-scale assessments via API; future
  value-chain (VSME supplier) and assurance-pack modules at contract scope.

Rationale: the pricing page already sells "sustainability-evidence" at
Professional/Business; CsrdTX is the intelligence layer on top of the same
evidence, so it inherits the same gates (implemented via the existing
`ROLE_RANK` site limits in `api_csrd.py`). No `PRICING.md` amendment is
required; if a future wave adds a separately priced module (e.g. assurance
pack), it goes through the §7 change rules: commit + matching site update in
one deploy.

## 6. Roadmap

### Wave 1 — shipped 2026-09-05 ✅
Versioned regulatory KB; applicability engine; double materiality math;
readiness composite + gap analysis; `/api/v2/csrd` API; applicability check
and regulatory watch on the sustainability page; 30 tests.

### Wave 2 — assessment depth
- Company-declared datapoint intake (energy, GHG Scope 1/2/3, water, waste)
  with `COMPANY_DECLARED` status and document upload as supporting evidence.
- Interactive double-materiality workflow (stakeholder survey capture, IRO
  register) on top of `materiality.py`.
- ESRS 2026 simplified set: ingest the published disclosure requirements once
  in force; version diff ("what changed for your company").
- Persisted assessments + readiness tracking over time.

### Wave 3 — evidence & assurance support
- Document intelligence: extract datapoints from uploaded PDFs/Excel
  (invoices, prior reports) → candidate values, human-confirmed, never
  auto-accepted (extraction ≠ proof).
- Assurance-support pack: evidence register, data lineage, methodology,
  missing-data log — auditor-ready export (assurance itself remains with the
  independent provider).
- EU Taxonomy eligibility/alignment screening linked to the same evidence.

### Wave 4 — continuous intelligence
- Regulatory Watch active monitoring: ingest official sources (EUR-Lex,
  Commission, EFRAG), detect changes, map to affected datapoints and affected
  customers, notify.
- Continuous readiness: re-score on new evidence or regulatory change;
  report diffs between assessment versions.
- Value-chain module: VSME-level supplier questionnaires (the value-chain
  cap), aggregated into the parent's CSRD assessment.

### Wave 5 — platform surfaces
- Python SDK + CLI (`tx sustainability …`, incl. `reproduce <id>`).
- ~~Digital tagging export~~ **XBRL/iXBRL shipped early** (§4.1, 2026-09-05);
  remaining: anchoring the extension elements to the official ESRS digital
  taxonomy once verified against the published files.
- QGIS/plugin surfaces for spatially-driven E1/E3/E4 screening.

## 7. Boundaries (always stated)

CsrdTX produces screening-level intelligence from declared facts and Talaix
physical-risk evidence. It is **not** legal advice, **not** assurance under
ISAE 3000 / AA1000, and **not** the limited-assurance engagement CSRD
requires from an auditor or independent assurance provider. Unavailable data
is declared, never invented.
