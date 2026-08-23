# Talaix — Backend Infrastructure

**Status:** current state + target design for the data-intensive backend.
Rule: infrastructure follows demonstrated need — nothing here licenses
premature migration. The honest current stack is documented first.

---

## 1. Current state (production, verified)

| Concern | Current implementation |
|---|---|
| Primary store | **SQLite (WAL)** at `/data/hydrashield_cache.sqlite3` on the shared Docker volume: cache, jobs, watches, alerts, accounts, events, webhooks, alert rules/deliveries. Additive, idempotent migrations (`CREATE TABLE IF NOT EXISTS`) |
| Caching | `TTLCache` (per-namespace TTLs, error results pinned short) + 15-min analysis cache shared by API and jobs |
| Workers | `watch_checker` container loop (30 min): watch checks → alert-rule evaluation → snapshot rebuild. In-process threads for analysis jobs (`jobs.py`, staged, deduped) |
| Rate limits | per-IP sliding window + per-tier per-user budgets (in-memory, per-worker) |
| Versioning | `/api/v2` additive-only contract (`docs/API_V2.md`); model versions immutable in `config/model_registry.json`; report/analysis content hashes (`report_content_id`, evidence `content_hash`) |
| Provenance | `EvidenceRecord` + per-component provenance dicts + upgraded legacy aliases; content hashing binds claims to source payloads |
| Reproducibility | every analysis carries `generated_at` + provenance; event/alert/report IDs are content-derived; the same inputs re-derive the same IDs |
| Logging | stdlib logging per module; gunicorn access logs; watch scripts log to stdout (Docker logs) |
| Failure recovery | honest unavailable states everywhere; error results pinned ≤60 s; containers `restart: unless-stopped`; post-deploy health gate in CI |
| Tests | 600+ offline tests; live-network smoke via `test_real_integration.py` (manual); CI gate before deploy |

## 2. Target: PostgreSQL/PostGIS (stage, evaluated — not yet migrated)

**Why eventually:** spatial queries at scale (event/cell geometry), concurrent
multi-writer load (API + workers + future SDK consumers), temporal tables,
proper indexing for the Data Observatory's live catalog.

**Proposed shape (when justified):**

```
PostgreSQL 16 + PostGIS
  core:        users, sessions, organizations, subscriptions, api_keys
  intelligence: climate_events (geom), event_evidence, datasets, models,
                research_refs, provider_health
  monitoring:  watches, alert_rules, alert_records, alert_deliveries,
                webhook_subscriptions, usage_log, audit_log (append-only)
  cache:       stays Redis-like or pg UNLOGGED — or remain SQLite-sidecar
```

- **Migration discipline:** dual-write shadow phase → backfill → read-switch
  per table family → SQLite kept as cache. Alembic-style versioned
  migrations; rollback per step. No big-bang cutover.
- **Trigger to start:** sustained multi-writer contention, geometry query
  needs (event search by polygon), or ≥3 services fighting over WAL.

## 3. Workers & queues (target)

Current in-container loops are adequate at present volume. Target when
alert/webhook volume grows:

- Task queue (RQ/Dramatiq-class, Redis or pg-backed): analysis jobs,
  alert evaluation, webhook delivery with **retry/backoff** (today:
  at-least-once per dispatch run, no retry worker — declared limitation).
- Scheduler: cron-style beat inside a worker container (replaces the
  shell loop) with per-job locks (no duplicate concurrent evaluation).
- Webhook delivery: queue with exponential backoff + dead-letter +
  per-target circuit breaker.

## 4. Observability (target)

- **Structured logs** (JSON lines: ts, level, module, request_id, route,
  status, duration, upstream) — single `logging` config in `wsgi.py`;
  request-id middleware propagating to upstream calls.
- **Metrics**: per-endpoint latency/error counters, cache hit ratios,
  upstream-call counts per provider, alert/webhook delivery rates.
  Expose at `/api/internal/metrics` (admin-only) before any external APM.
- **Health depth**: extend `/api/health` with per-upstream reachability
  snapshot (cached 5 min, non-blocking).

## 5. Data pipelines (normative for new datasets)

Every dataset follows the observatory pipeline (see
`docs/PRODUCTS_AND_PARTNERSHIPS.md` §3):

```
registry candidate → fetcher (error-dict convention) → validation
(ingestion.validate_series/spatial) → normalization → engine block
(labels + provenance + uncertainty envelope) → API contract test →
offline unit tests → live smoke → integrated status in the registry
```

- Provider chains (`src/climate/ingestion.py`) declare primary/fallback
  per variable; single-provider gaps are declared, never hidden.
- Source comparison never merges silently (FIRMS pattern).
- Temporal data: ISO-8601 UTC everywhere; daily series validated for
  monotonicity, gaps, duplicates, null ratios before use.

## 6. Security baseline (unchanged, restated)

Env-only secrets; hashed tokens/keys; per-user isolation; rate limits;
SSRF-guarded webhooks; read-only API keys; audit log without secrets;
offline tests with no real credentials.
