# Talaix PostGIS Data Model (design target)

**Status: DESIGN ONLY.** The live store is the shared SQLite database
(`data/cache/hydrashield_cache.sqlite3`, path via `HYDRASHIELD_CACHE_DB`).
Nothing in the application executes `db/migrations/0001_init.sql` — it is
the agreed migration target for when a spatial-temporal backend is
justified, and it is written so that every current SQLite table maps onto
it mechanically.

## Why PostGIS (eventually)

The platform is spatial-temporal by nature: analyses happen at points,
events occur at points over time, alert rules watch locations, and the
observatory tracks datasets with coverage footprints. SQLite serves the
current single-node deployment well; PostGIS becomes justified when we
need any of:

- spatial queries (nearest events to a point, events within a radius,
  coverage-footprint overlap) — today these are done in Python;
- concurrent writers beyond what a single SQLite writer serialises;
- temporal range queries over large event/health histories.

## Design conventions

- **Spatial columns** are `GEOGRAPHY(POINT, 4326)` (metres, WGS84 lon/lat;
  `datasets.geom` is a `POLYGON` coverage footprint). Every spatial column
  has a **GiST index** (`USING GIST (geom)`).
- **Temporal columns** are `TIMESTAMPTZ`; columns queried by time
  (`occurred_at`, `executed_at`, `checked_at`, `created_at`) carry **btree
  indexes**, usually composite with the natural filter (`hazard`,
  `dataset_key`, `user_id`).
- **Provenance columns** on evidence-bearing tables: `source`
  (human-readable origin), `evidence_id` (src/climate/evidence.py id),
  `content_hash` (SHA-256 of the payload the row rests on).
- **Versioning columns**: `dataset_version` / `model_version` where a row
  depends on a dataset/model state; registry tables (`datasets`, `models`,
  `research_refs`, `users`) are versioned as rows with
  `valid_from` / `valid_to` (NULL = current) so history is never
  overwritten — the same "never edit a version in place" discipline as
  `config/model_registry.json`.
- **JSONB** for semi-structured payloads (`params`, `evidence`,
  `uncertainty`, `metrics`, `data_quality_profile`).
- **Secrets stay hashed**: `sessions.token_hash`, `api_keys.key_hash`,
  `webhook_subscriptions.secret_hash` mirror the current HMAC discipline;
  `audit_log.detail` never carries secrets.

## Tables (db/migrations/0001_init.sql)

| Table | Purpose | Spatial (GiST) | Temporal (btree) | Provenance / versioning |
|---|---|---|---|---|
| `datasets` | data-registry records (versioned rows) | coverage polygon | `valid_from/valid_to` | `source`, `content_hash`, `dataset_version` |
| `models` | model-registry records | — | `valid_from/valid_to` | `model_version`, `content_hash` |
| `research_refs` | research-registry records | — | `valid_from/valid_to` | `content_hash` |
| `ground_truth_events` | observed ground-truth (FIRMS, gauges) | point | `occurred_at` | `source`, `evidence_id`, `content_hash`, `dataset_version` |
| `climate_events` | platform-derived historical events | point | `recorded_at` | `evidence_id`, dataset+model version |
| `evaluation_runs` | model/indicator evaluation results | — | `executed_at` | versions, `evidence_id`, `content_hash` |
| `benchmark_runs` | benchmark suite results | — | `executed_at` | versions, `content_hash` |
| `analysis_runs` | reproducible analysis records (`ar_…`) | analysis point | `executed_at` | versions, `result_hash`, `content_hash` |
| `source_health` | integrated-source health history | — | `checked_at` | `source` (probed URL), `dataset_version` |
| `users` / `sessions` / `api_keys` | accounts | — | expiry/creation | hashed tokens/keys |
| `alert_rules` | watched locations per user | point | — | threshold + state |
| `alert_records` / `alert_deliveries` | fired alerts + per-channel outcomes | point | `created_at` | links `analysis_id`, versions |
| `webhook_subscriptions` | outbound webhook targets | — | — | `secret_hash` |
| `usage_events` / `audit_log` | metering + security audit | — | `occurred_at`/`created_at` | actor references |

Mapping notes from the current SQLite schema:

- `analysis_runs.analysis_id` (`ar_` + content hash), `alert_records.id`
  (`al_` + hash) carry over as primary keys unchanged — content-derived
  ids are backend-neutral.
- `lat`/`lon` REAL pairs become `GEOGRAPHY(POINT, 4326)`; `params_json` /
  `uncertainty_json` / `evidence_json` TEXT columns become JSONB.
- `ok`/`active`/`suppressed` INTEGER flags become BOOLEAN.
- `datasets` keeps the registry's catalog discipline: `status`
  integrated | candidate | rejected, and `data_quality_profile` present on
  integrated entries only.

## Migration discipline (when justified — not before)

SQLite stays live until a concrete need above justifies the switch. The
switch itself follows three phases, each independently reversible:

1. **Dual-write** — the storage modules (`cache.py` consumers,
   `notify_store.py`, `analysis_runs.py`, `source_health.py`, event
   stores) write to both SQLite and PostGIS behind the existing store
   interfaces; reads stay on SQLite. Row counts and spot hashes are
   compared per table.
2. **Backfill** — one-off script copies historical rows in id order
   (content-derived ids make the copy idempotent); re-verify counts/hashes.
3. **Read-switch** — reads move to PostGIS behind the same interfaces;
   SQLite writes continue for one full watch_checker cycle as a rollback
   path, then stop. Rollback = flip the read switch back.

Never: big-bang cutover, schema changes without a new numbered migration
(`db/migrations/NNNN_*.sql`, append-only), or executing this DDL from
application code.
