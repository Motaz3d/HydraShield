# Portfolios — geographic + temporal + goal work containers

A **portfolio** (المحفظة) groups a user's work — saved locations, analyses,
reports and alert rules — around **one goal, one region and one period**, so
ongoing research keeps its context across sessions instead of scattering
across one-off analyses.

- **Geographic context** — `region_name` on the portfolio plus per-item
  `lat`/`lon` coordinates (every item links back to the map).
- **Temporal context** — `start_date` / `end_date` (the period of interest)
  plus the items' own timeline (`created_at` per item).
- **Goal context** — `goal` (e.g. `insurance_review`, `csrd`,
  `supply_chain`, `investment`, `research`, `monitoring`).

## Data model

`src/dashboard/accounts.py` (`UserStore`), same SQLite database and table
conventions as the other account stores:

```sql
portfolios(id, user_id, name, goal NULL, region_name NULL,
           start_date NULL, end_date NULL, created_at)
portfolio_items(id, portfolio_id, kind, ref_id NULL, lat NULL, lon NULL,
                meta_json, created_at)
```

- `kind` ∈ `location | analysis | report | alert`.
- `ref_id` references the original row (e.g. `report_history.id`) when one
  exists; `meta_json` stores a **snapshot of the summary at save time** —
  continuity: the portfolio shows what the analysis said when it was saved,
  even if a re-analysis later says something else.
- Every query is ownership-scoped (`user_id` from the session); deleting a
  portfolio cascades its items. Caps: 25 portfolios per account (403 +
  `upgrade` descriptor), per-tier rate budget `v2_portfolios`.

## API (`/api/v2/account/portfolios`, `registered` tier)

| Endpoint | Notes |
|---|---|
| `GET /api/v2/account/portfolios` | `{"portfolios": […]}` with `item_count` |
| `POST /api/v2/account/portfolios` | `{name, goal?, region_name?, start_date?, end_date?}` → 201 `{"portfolio"}`; date order validated |
| `GET /api/v2/account/portfolios/<id>` | `{"portfolio": {…, "items": […]}}`; 404 for foreign ids |
| `DELETE /api/v2/account/portfolios/<id>` | cascades items; 404 for foreign ids |
| `POST /api/v2/account/portfolios/<id>/items` | `{kind, ref_id?, lat?, lon?, meta?}` → 201 `{"item"}`; lat/lon must come together and be in range |
| `DELETE /api/v2/account/portfolios/<id>/items/<item_id>` | `{"deleted": true}` or 404 |

## History wiring (prerequisite that ships with this feature)

`UserStore.record_analysis` / `record_report` existed from the accounts
stage but were never called — the account page rendered permanently empty
history. They are now wired through two helpers in
`src/dashboard/auth_api.py` (`record_user_analysis`, `record_user_report`),
which swallow every failure (history is an audit trail, never a failure
path) and skip anonymous callers:

- `GET /api/analyze` and `GET /api/v2/analyze` → `analysis_history`
- `GET /api/report` and `POST /api/v2/report-builder/pdf` → `report_history`

## UI

- **Account page** (`account.html` + `website/js/account.js`): portfolio
  panel — create form (name / goal / region / period), list with item
  counts, drill-down detail with per-item removal, delete.
- **Dashboard** (`website/js/dashboard.js`): after a completed analysis a
  "Keep working on this" card offers *Save this analysis* into a chosen
  portfolio (sign-in prompt for anonymous users).
- **Report builder** (`website/js/report-builder.js`): after PDF export a
  *Save draft to portfolio* row appears when the user has portfolios.

## Honesty notes

- Portfolio items record what the user actually saved — no item is
  auto-created, inferred or back-filled.
- The `meta_json` snapshot is labelled by its save time; it is never
  presented as the current state of the world.

Tests: `tests/test_portfolios.py` (auth gating, CRUD, validation, per-user
isolation, cascade delete, history wiring incl. anonymous skip).
