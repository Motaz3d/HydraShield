# Green Finance Verification

Talaix Green Finance Verification is a physical-evidence layer for financed
assets. It screens an asset or a portfolio of assets against the physical
climate hazards listed in the EU Taxonomy Climate Delegated Act Appendix A,
using only real, registered hazard modules. The output is a structured
verification record plus an optional PDF evidence report.

## Purpose

- Provide asset-level physical climate-risk evidence for green-finance
  workflows (green bonds, sustainability-linked loans, ESG disclosures).
- Use the EU Taxonomy "Do No Significant Harm" (DNSH) climate-change
  adaptation hazard vocabulary.
- Declare every data gap explicitly — never invent or silently omit
  unavailable layers.

## DNSH hazard mapping

| Talaix hazard | EU Taxonomy Appendix A label | Risk class |
|---------------|------------------------------|------------|
| flood | Riverine / pluvial flooding | acute |
| coastal | Coastal flooding & sea-level rise | chronic |
| wildfire | Wildfire | acute & chronic |
| heat | Heat stress / heat waves | chronic & acute |
| drought | Drought / water stress | chronic |
| wind | Storms & extreme wind | acute |

Only hazards registered in `src.climate.registry` and present in the mapping
above are checked. If a module is absent or unavailable, the hazard is
reported as `UNKNOWN` with a declared gap.

## Claim status and confidence vocabulary

Each checked hazard receives:

- **claim_status**
  - `DOCUMENTED` — when the underlying level is explicitly marked `validated`.
  - `MODELLED` — normal screening result from a real model with declared inputs.
  - `UNKNOWN` — when the module is absent, raises an exception, or reports
    `unavailable`/`key_required`.
- **confidence**
  - `high` — when the claim status is `DOCUMENTED`.
  - `medium` — when the analysis status is `ok` and the claim is `MODELLED`.
  - `low` — when the analysis status is `partial` or the claim is `UNKNOWN`.

## Framework context

The report names four frameworks and what it provides for each:

1. **EU Taxonomy Climate Delegated Act** — risk vocabulary & assessment
   criterion (Appendix A acute/chronic classification).
2. **EBA Pillar 3 ESG ITS** — Template 5 physical-risk disclosure context.
3. **ICMA Green Bond Principles** — post-issuance monitoring / impact
   reporting cadence.
4. **IFRS S2 / TCFD** — physical-risk disclosure language.

## Honesty contract

Unavailable data is declared, never invented. Every missing or unsuitable
hazard layer is recorded as `UNKNOWN` with a stated limitation in
`declared_gaps`.

## Disclaimer

Talaix provides a physical-evidence layer only. This is **NOT** a Second Party
Opinion, **NOT** an EU Green Bond external review by an ESMA-registered
external reviewer, and **NOT** investment advice. Hazard levels are screening
indicators unless explicitly labelled validated.

## API reference

All endpoints are mounted under `/api/v2/verification`.

### `GET /api/v2/verification/asset`

Verify a single asset.

Query parameters:

- `lat` — latitude (`-90` to `90`).
- `lon` — longitude (`-180` to `180`).
- `name` — optional asset name.

Rate limit: 20 requests/minute per client IP.

Response: the full `verify_asset` JSON (see `src/climate/verification.py`).

### `GET /api/v2/verification/report`

Download the evidence PDF for a single asset. Same query parameters as
`/asset`. Rate limit: 10/minute. Returns `503` if `reportlab` is not
installed.

### `POST /api/v2/verification/portfolio`

Batch check a portfolio of assets. Requires the `registered` role.

Request body:

```json
{
  "name": "optional portfolio name",
  "assets": [
    {"name": "Trier", "lat": 49.75, "lon": 6.64},
    {"name": "A Coruña", "lat": 43.3, "lon": -8.4}
  ]
}
```

Limits: 25 assets for `registered` users, 100 for `subscriber` and above.

Response:

```json
{
  "portfolio_id": "…",
  "count": 2,
  "ok_count": 2,
  "results": [
    {"asset": {"name": "Trier", "lat": 49.75, "lon": 6.64},
     "ok": true,
     "verification_id": "…",
     "summary": "…",
     "hazard_levels": {"flood": "Very high"}}
  ]
}
```

The full record (including all evidence) is persisted and can be fetched by
ID.

### `GET /api/v2/verification/portfolio/<portfolio_id>`

Return the full stored portfolio record. Owner or admin only. Returns `404`
for unknown IDs.

## Roadmap

- Continuous monitoring of verified assets reuses the existing
  `/api/v2/account/alerts` endpoint.
- Carbon-credit integrity checks and greenwashing-risk screening are later
  phases on the same verification engine.
