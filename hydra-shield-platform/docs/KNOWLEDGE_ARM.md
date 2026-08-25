# Talaix — Knowledge Arm

The Knowledge Arm is the public scientific surface of the Talaix platform: a
library of periodic **evidence briefs** and evergreen **framework explainers**
at the intersection of finance and the environment.

## 1. Purpose

- Build reference authority by showing our working: every claim is linked to an
  open source.
- Feed the Talaix Academy with accurate, up-to-date framework context.
- Act as a free marketing surface for the business lines by demonstrating the
  evidence quality behind Green Finance Verification, Insurance, Supply Chain
  and Sustainability Reporting.

The content strategy is demand-driven and documented in
`docs/CONTENT_STRATEGY.md`.

## 2. Content kinds

| Kind | Cadence | Goal |
|------|---------|------|
| `evidence_brief` | Weekly or biweekly | Curated, open-source beats from the institutions we monitor, with explicit claim status and Talaix-view analysis where appropriate. |
| `framework_explainer` | Evergreen, updated when regimes change | Plain-language explainers of regulatory frameworks (EU Taxonomy, DNSH, CSRD, EUDR, etc.) aimed at banks, companies and advisors. |

Both kinds live in `config/briefs_registry.json`.

## 3. Editorial process

### Sourcing rules

- **Open sources only.** Every fact must be traceable to a public document or
  public news item with a URL.
- **Every fact linked.** Each source entry carries `name`, `url`, `date` (where
  available) and `claim_status`.
- **Claim statuses**
  - `REPORTED` — news or a publisher's account; the original item is linked so
    the reader can verify.
  - `DOCUMENTED` — official document, regulation, dataset or other primary
    source.
- **"Talaix view" analysis** is always explicitly labelled as such and kept
  separate from reported/documented facts.
- **Unavailable beats are stated, never filled.** If a monitoring window yields
  nothing verifiable, the brief says so.
- **No predictions as fact.** Forward-looking statements are labelled as
  scenarios, expectations or Talaix view, never as fact.
- **No invented statistics.** Numbers must come from a linked source or be
  labelled as model output with limitations.
- **No paywalled sources.** If a primary source is behind a paywall, look for
  the official open version or omit the beat.

### Monitored institutions

The evidence-brief monitoring list is deliberately public:

- EBA — Pillar 3 ESG / Green Asset Ratio
- ESMA — green-bond external reviewers, sustainable-finance supervision
- EIOPA — insurance climate stress testing
- ECB / NGFS — climate risk supervision and research
- DG ENV — EU environment policy (EUDR, water, circular economy)
- DG CLIMA — EU climate policy
- FATF — environmental crime and money-laundering risk
- ICVCM — Integrity Council for the Voluntary Carbon Market
- UNFCCC Article 6 — carbon-market mechanisms

Suggestions for additional open sources are welcome via `contact.html`.

## 4. Publishing workflow

1. Draft the brief as a new entry in `config/briefs_registry.json`.
2. Set `status` to `"draft"` while reviewing.
3. Run the structural honesty test (`tests/test_briefs.py`) before publishing.
4. Set `status` to `"published"`. Drafts are never served by the API.
5. Deploy the registry change. No CMS or database migration is required.

### Schema reference

```json
{
  "id": "kebab-id",
  "kind": "framework_explainer" | "evidence_brief",
  "title": "...",
  "date": "2026-08-25",
  "summary": "...",
  "sections": [{"heading": "...", "body": "..."}],
  "sources": [
    {"name": "...", "url": "...", "date": "2026-08-14"|null, "claim_status": "REPORTED"|"DOCUMENTED"}
  ],
  "related_tools": [{"label": "...", "href": "green-finance.html"}],
  "related_glossary": ["eu_taxonomy", "dnsh"],
  "status": "published"
}
```

## 5. Review checklist

Before marking a brief as published:

- [ ] Every source URL resolves and supports the claim it is attached to.
- [ ] Dates are correct and consistent with the source.
- [ ] Talaix-view analysis is explicitly labelled.
- [ ] `claim_status` values are `REPORTED` or `DOCUMENTED` only.
- [ ] `related_tools` links point to existing platform pages.
- [ ] No invented statistics, predictions-as-fact or paywalled sources.

## 6. Deliberately NOT built

The Knowledge Arm is intentionally lightweight:

- **No CMS.** Content is config-driven; publishing is a registry edit and a
  deployment.
- **No email automation.** Distribution reuses existing channels (LinkedIn,
  newsletter when live, Academy cross-links). An email-subscription feature is
  a roadmap item and will reuse the platform mailer.
- **No paywall.** All published briefs are public.

## 7. API reference

Read-only public endpoints, rate-limited to 60 requests/minute per client IP:

- `GET /api/v2/briefs` — list published briefs. Optional `?kind=` filter
  (`framework_explainer` or `evidence_brief`). Returns `{briefs: [...], note}`.
- `GET /api/v2/briefs/<brief_id>` — full published brief, or honest 404.

See `src/climate/api_briefs.py` and `src/climate/briefs.py` for implementation.
