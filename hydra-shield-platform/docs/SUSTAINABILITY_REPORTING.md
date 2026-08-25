# Sustainability & CSRD Reporting

Talaix Sustainability Evidence Reports provide a CSRD / ESRS-oriented physical
climate-risk evidence pack for a company's own sites. The pack reuses the same
real-data verification engine as the Green Finance Verification feature and
states explicitly which disclosure areas it covers and which it does not.

## Purpose

- Produce an evidence-backed sustainability report addressed to competent
  authorities, auditors and investors.
- Combine a company profile (declared by the company, not verified by Talaix)
  with site-level physical hazard verification.
- Align with CSRD (EU) 2022/2464, ESRS Delegated Regulation (EU) 2023/2772,
  the EU Taxonomy DNSH adaptation vocabulary, California SB 261, and China's
  CSDS Basic Standard (Trial).

## Inputs

- **Company profile**: `name` (required), optional `sector`, `country`,
  `website`, `description`. These fields are labelled
  *"declared by the company — not verified by Talaix"*.
- **Sites**: a list of `{name, lat, lon}` locations. The same physical hazard
  checks (flood, coastal, wildfire, heat, drought, wind) are run for each site
  via `src.climate.verification.verify_portfolio`.

## ESRS coverage map

| Area | Ref | Coverage | Note |
|------|-----|----------|------|
| ESRS 2 — Governance & strategy | ESRS 2 GOV/SBM | not_covered | Company-declared fields only; not verified by Talaix. |
| ESRS E1 — Physical climate risk of sites (gross risk) | ESRS E1 IRO-1 / MD-P-3 | covered_by_evidence | Covered by site-level physical hazard verification. |
| ESRS E1 — GHG emissions, targets and transition plan | ESRS E1 MDR-P / MDR-T | not_covered | Requires company GHG inventories and transition planning. |
| ESRS E2 — Pollution | ESRS E2 | not_covered | No pollutant emissions or discharge data collected. |
| ESRS E3 — Water & marine resources | ESRS E3 | partial | Drought / water-stress physical evidence only; consumption/discharge metrics not covered. |
| ESRS E4 — Biodiversity & ecosystems | ESRS E4 | not_covered | No biodiversity or ecosystem impact assessment performed. |
| ESRS E5 — Resource use & circular economy | ESRS E5 | not_covered | No resource-flow or circular-economy metrics collected. |
| ESRS S1–S4 — Social standards | ESRS S1/S2/S3/S4 | not_covered | Social and workforce disclosures are outside scope. |
| ESRS G1 — Business conduct | ESRS G1 | not_covered | Governance and business-conduct disclosures are not verified. |

Items marked `not_covered` are **declared boundaries** of this pack, not
omissions. They require company data or other assurance providers.

## Frameworks

- **CSRD (EU) 2022/2464 & ESRS Delegated Regulation (EU) 2023/2772** —
  primary vocabulary; the pack covers ESRS E1 physical climate-risk
  identification for own sites. Double materiality, GHG inventories,
  transition plans and governance disclosures are not covered.
- **EU Taxonomy DNSH climate adaptation** — reuses the Appendix A hazard
  classification and claim-status language from Green Finance Verification.
- **California SB 261** — climate-related financial risk reports; the
  physical-risk evidence is the relevant layer.
- **California SB 253** — GHG emissions disclosure (Scope 1/2/3); tracked as
  a declared boundary — emissions measurement is not covered.
- **China CSDS Basic Standard (Trial)** — Ministry of Finance sustainability
  disclosure standard, aligned with SSE/SZSE/BSE 2024 guidelines;
  physical climate-risk evidence is the relevant layer.

## Talaix Evidence Standard

The report carries a published methodology label with five criteria:

1. Every claim carries a controlled-vocabulary claim status.
2. Every evidence record states source, dataset, reference period and link.
3. Every report is content-hashed (report id) and engine-versioned.
4. Unavailable data is declared as gaps, never invented.
5. Company-supplied fields are labelled as unverified.

This label is **not** third-party accreditation, **not** assurance under
ISAE 3000 or AA1000, and **not** the limited-assurance engagement that CSRD
requires from an auditor or independent assurance provider.

## Relation to Green Finance Verification

Both features use the same `src.climate.verification` engine. Green Finance
Verification is asset/portfolio oriented and targeted at green-finance
workflows; Sustainability Reporting wraps the same evidence into a
company-level CSRD/ESRS disclosure pack.

## API reference

All endpoints are mounted under `/api/v2/sustainability`.

### `GET /api/v2/sustainability/frameworks`

Public frameworks reference. Returns `frameworks`, `coverage_map`,
`evidence_standard` and `disclaimer`.

Rate limit: 60 requests/minute per client IP.

### `POST /api/v2/sustainability/report`

Generate and persist the JSON evidence report. Requires the `registered`
role.

Request body:

```json
{
  "company": {
    "name": "Acme Renewable Materials SA",
    "sector": "renewable energy manufacturing",
    "country": "Luxembourg"
  },
  "assets": [
    {"name": "Trier factory", "lat": 49.75, "lon": 6.64},
    {"name": "A Coruña port", "lat": 43.3, "lon": -8.4}
  ]
}
```

Limits: 25 sites for `registered`, 100 for `subscriber` and above.

Response: the full `build_sustainability_evidence` payload including
`report_id`, `coverage_map`, `portfolio_summary`, `site_results`,
`declared_gaps`, `evidence_standard`, disclaimer and honesty contract.

### `POST /api/v2/sustainability/report/pdf`

Same inputs as `/report`; returns the evidence pack as a PDF. Returns `503`
if `reportlab` is not installed.

### `GET /api/v2/sustainability/report/<report_id>`

Return the full stored report record. Owner or admin only; `404` for unknown
IDs, `403` for other users' reports.

## Roadmap

- Expand jurisdiction-specific templates (e.g. SEC climate disclosure,
  UK SDS) on the same evidence engine.
- Add optional company identifier fields (LEI, VAT) as declared metadata.
- Continuous monitoring of reported sites via `/api/v2/account/alerts`.
