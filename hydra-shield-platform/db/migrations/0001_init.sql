-- HydraShield PostGIS target schema — DESIGN ONLY.
--
-- This DDL is the migration target documented in docs/DATA_MODEL_POSTGIS.md.
-- It is NEVER executed by the application: SQLite (data/cache/hydrashield_cache.sqlite3)
-- remains the live store until the dual-write → backfill → read-switch
-- discipline in that document justifies the switch.
--
-- Conventions:
--   - spatial columns are GEOGRAPHY (metres, lon/lat WGS84), indexed with GiST;
--   - temporal columns are TIMESTAMPTZ, btree-indexed where queried by time;
--   - provenance columns: source, evidence_id, content_hash;
--   - versioning columns: dataset_version / model_version / valid_from / valid_to;
--   - JSONB for semi-structured payloads (params, evidence, uncertainty).

CREATE EXTENSION IF NOT EXISTS postgis;

-- ---------------------------------------------------------------------------
-- Registries (catalog records; versioning by valid_from/valid_to rows)
-- ---------------------------------------------------------------------------

CREATE TABLE datasets (
    id                  BIGSERIAL PRIMARY KEY,
    dataset_key         TEXT NOT NULL,              -- registry id, e.g. 'sentinel2-l2a'
    name                TEXT NOT NULL,
    provider            TEXT,
    provider_class      TEXT,
    status              TEXT NOT NULL,              -- integrated | candidate | rejected
    dataset_version     TEXT,                       -- product version / reference year
    license             TEXT,
    geom                GEOGRAPHY(POLYGON, 4326),   -- coverage footprint where declared
    data_quality_profile JSONB,                     -- integrated entries only
    source              TEXT,                       -- provenance: registry file + audit date
    content_hash        TEXT,                       -- hash of the registry entry
    valid_from          TIMESTAMPTZ NOT NULL,
    valid_to            TIMESTAMPTZ                 -- NULL = current record
);
CREATE INDEX idx_datasets_geom ON datasets USING GIST (geom);
CREATE INDEX idx_datasets_key_valid ON datasets (dataset_key, valid_from);
CREATE UNIQUE INDEX idx_datasets_key_current
    ON datasets (dataset_key) WHERE valid_to IS NULL;

CREATE TABLE models (
    id                  BIGSERIAL PRIMARY KEY,
    model_key           TEXT NOT NULL,              -- registry id, e.g. 'fwi_system_v1'
    model_version       TEXT NOT NULL,              -- registry 'version' — never edited in place
    name                TEXT NOT NULL,
    methodology         TEXT,
    validation          JSONB,
    limitations         TEXT,
    source              TEXT,                       -- provenance: registry file + audit date
    content_hash        TEXT,
    valid_from          TIMESTAMPTZ NOT NULL,
    valid_to            TIMESTAMPTZ
);
CREATE UNIQUE INDEX idx_models_key_version ON models (model_key, model_version);

CREATE TABLE research_refs (
    id                  BIGSERIAL PRIMARY KEY,
    ref_key             TEXT NOT NULL UNIQUE,       -- registry id, e.g. 'vanwagner1987'
    title               TEXT NOT NULL,
    year                INTEGER,
    url                 TEXT,
    pipeline_stage      TEXT,                       -- paper → … → production
    source              TEXT,
    content_hash        TEXT,
    valid_from          TIMESTAMPTZ NOT NULL,
    valid_to            TIMESTAMPTZ
);

-- ---------------------------------------------------------------------------
-- Events (spatial-temporal core)
-- ---------------------------------------------------------------------------

CREATE TABLE ground_truth_events (
    id                  BIGSERIAL PRIMARY KEY,
    event_key           TEXT,                       -- upstream event id where available
    hazard              TEXT NOT NULL,
    geom                GEOGRAPHY(POINT, 4326) NOT NULL,
    occurred_at         TIMESTAMPTZ NOT NULL,       -- event time (observed)
    recorded_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    properties          JSONB,                      -- magnitude, FRP, burned area…
    source              TEXT NOT NULL,              -- e.g. 'NASA FIRMS VIIRS'
    evidence_id         TEXT,                       -- src/climate/evidence.py id
    content_hash        TEXT,
    dataset_version     TEXT
);
CREATE INDEX idx_gt_events_geom ON ground_truth_events USING GIST (geom);
CREATE INDEX idx_gt_events_time ON ground_truth_events (occurred_at);
CREATE INDEX idx_gt_events_hazard_time ON ground_truth_events (hazard, occurred_at);

CREATE TABLE climate_events (
    id                  BIGSERIAL PRIMARY KEY,
    event_key           TEXT NOT NULL,              -- platform event id (ev-derived)
    hazard              TEXT NOT NULL,
    geom                GEOGRAPHY(POINT, 4326) NOT NULL,
    started_at          TIMESTAMPTZ,
    ended_at          TIMESTAMPTZ,
    recorded_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    summary             JSONB,
    evidence            JSONB,                      -- full evidence list ("show me the evidence")
    source              TEXT NOT NULL,
    evidence_id         TEXT,
    content_hash        TEXT,
    dataset_version     TEXT,
    model_version       TEXT
);
CREATE INDEX idx_climate_events_geom ON climate_events USING GIST (geom);
CREATE INDEX idx_climate_events_time ON climate_events (recorded_at);
CREATE INDEX idx_climate_events_hazard ON climate_events (hazard, recorded_at);

-- ---------------------------------------------------------------------------
-- Evaluation / benchmarking / analysis runs (reproducibility core)
-- ---------------------------------------------------------------------------

CREATE TABLE evaluation_runs (
    id                  BIGSERIAL PRIMARY KEY,
    evaluation_key      TEXT NOT NULL UNIQUE,       -- content-derived id
    target              TEXT NOT NULL,              -- what was evaluated (model/indicator)
    model_version       TEXT,
    dataset_version     TEXT,
    metrics             JSONB,                      -- ROC/PR-AUC, Brier…
    executed_at         TIMESTAMPTZ NOT NULL,
    source              TEXT,                       -- script/config that produced it
    evidence_id         TEXT,
    content_hash        TEXT
);
CREATE INDEX idx_evaluation_runs_time ON evaluation_runs (executed_at);

CREATE TABLE benchmark_runs (
    id                  BIGSERIAL PRIMARY KEY,
    benchmark_key       TEXT NOT NULL UNIQUE,       -- content-derived id
    suite               TEXT NOT NULL,
    model_version       TEXT,
    dataset_version     TEXT,
    results             JSONB,
    executed_at         TIMESTAMPTZ NOT NULL,
    source              TEXT,
    evidence_id         TEXT,
    content_hash        TEXT
);
CREATE INDEX idx_benchmark_runs_time ON benchmark_runs (executed_at);

CREATE TABLE analysis_runs (
    analysis_id         TEXT PRIMARY KEY,           -- 'ar_' + content hash (see src/dashboard/analysis_runs.py)
    endpoint            TEXT NOT NULL,
    hazard              TEXT,
    geom                GEOGRAPHY(POINT, 4326),     -- from lat/lon
    params              JSONB,
    dataset_versions    JSONB,
    model_versions      JSONB,
    methodology         TEXT,
    executed_at         TIMESTAMPTZ NOT NULL,
    result_hash         TEXT NOT NULL,
    uncertainty         JSONB,
    evidence            JSONB,
    content_hash        TEXT                        -- = analysis_id basis hash
);
CREATE INDEX idx_analysis_runs_geom ON analysis_runs USING GIST (geom);
CREATE INDEX idx_analysis_runs_time ON analysis_runs (executed_at);
CREATE INDEX idx_analysis_runs_hazard ON analysis_runs (hazard, executed_at);

-- ---------------------------------------------------------------------------
-- Source intelligence
-- ---------------------------------------------------------------------------

CREATE TABLE source_health (
    id                  BIGSERIAL PRIMARY KEY,
    dataset_key         TEXT NOT NULL,
    checked_at          TIMESTAMPTZ NOT NULL,
    http_status         INTEGER,
    latency_ms          DOUBLE PRECISION,
    ok                  BOOLEAN NOT NULL,
    status_change       TEXT,                       -- new | ok_to_down | down_to_ok | NULL
    note                TEXT,
    source              TEXT,                       -- probed URL
    dataset_version     TEXT
);
CREATE INDEX idx_source_health_dataset_time ON source_health (dataset_key, checked_at);

-- ---------------------------------------------------------------------------
-- Accounts / sessions / API keys
-- ---------------------------------------------------------------------------

CREATE TABLE users (
    id                  BIGSERIAL PRIMARY KEY,
    email               TEXT NOT NULL UNIQUE,
    password_hash       TEXT NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    verified_at         TIMESTAMPTZ,
    locale              TEXT,
    valid_from          TIMESTAMPTZ NOT NULL DEFAULT now(),
    valid_to            TIMESTAMPTZ
);

CREATE TABLE sessions (
    id                  BIGSERIAL PRIMARY KEY,
    user_id             BIGINT NOT NULL REFERENCES users (id),
    token_hash          TEXT NOT NULL UNIQUE,       -- HMAC hash, never the token
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at          TIMESTAMPTZ NOT NULL
);
CREATE INDEX idx_sessions_user ON sessions (user_id, expires_at);

CREATE TABLE api_keys (
    id                  BIGSERIAL PRIMARY KEY,
    user_id             BIGINT NOT NULL REFERENCES users (id),
    key_hash            TEXT NOT NULL UNIQUE,       -- HMAC hash, never the key
    label               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at          TIMESTAMPTZ
);
CREATE INDEX idx_api_keys_user ON api_keys (user_id);

-- ---------------------------------------------------------------------------
-- Alerting
-- ---------------------------------------------------------------------------

CREATE TABLE alert_rules (
    id                  BIGSERIAL PRIMARY KEY,
    user_id             BIGINT NOT NULL REFERENCES users (id),
    hazard              TEXT NOT NULL,
    geom                GEOGRAPHY(POINT, 4326) NOT NULL,  -- watched location
    name                TEXT,
    severity_threshold  TEXT NOT NULL DEFAULT 'HIGH',
    active              BOOLEAN NOT NULL DEFAULT TRUE,
    last_severity       TEXT,
    last_checked        TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_alert_rules_geom ON alert_rules USING GIST (geom);
CREATE INDEX idx_alert_rules_user_active ON alert_rules (user_id, active);

CREATE TABLE alert_records (
    id                  TEXT PRIMARY KEY,           -- 'al_' + content hash
    user_id             BIGINT NOT NULL REFERENCES users (id),
    rule_id             BIGINT NOT NULL REFERENCES alert_rules (id),
    hazard              TEXT NOT NULL,
    geom                GEOGRAPHY(POINT, 4326),
    severity            TEXT NOT NULL,
    trigger             TEXT NOT NULL,
    analysis_id         TEXT REFERENCES analysis_runs (analysis_id),
    dataset_version     TEXT,
    model_version       TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    suppressed          BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE INDEX idx_alert_records_geom ON alert_records USING GIST (geom);
CREATE INDEX idx_alert_records_time ON alert_records (created_at);

CREATE TABLE alert_deliveries (
    id                  BIGSERIAL PRIMARY KEY,
    alert_id            TEXT NOT NULL REFERENCES alert_records (id),
    channel             TEXT NOT NULL,              -- sms | email | webhook
    target              TEXT,
    status              TEXT NOT NULL,              -- sent | outbox | held | suppressed | failed | disabled
    provider_message_id TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_alert_deliveries_alert ON alert_deliveries (alert_id, created_at);

CREATE TABLE webhook_subscriptions (
    id                  BIGSERIAL PRIMARY KEY,
    user_id             BIGINT NOT NULL REFERENCES users (id),
    url                 TEXT NOT NULL,              -- HTTPS only (enforced by app)
    secret_hash         TEXT NOT NULL,              -- HMAC signing secret hash
    events              TEXT NOT NULL DEFAULT 'alert_fired',
    active              BOOLEAN NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_webhook_subs_user ON webhook_subscriptions (user_id, active);

-- ---------------------------------------------------------------------------
-- Usage metering + audit
-- ---------------------------------------------------------------------------

CREATE TABLE usage_events (
    id                  BIGSERIAL PRIMARY KEY,
    user_id             BIGINT REFERENCES users (id),
    api_key_id          BIGINT REFERENCES api_keys (id),
    endpoint            TEXT NOT NULL,
    occurred_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    status_code         INTEGER,
    latency_ms          DOUBLE PRECISION,
    meta                JSONB
);
CREATE INDEX idx_usage_events_time ON usage_events (occurred_at);
CREATE INDEX idx_usage_events_user_time ON usage_events (user_id, occurred_at);

CREATE TABLE audit_log (
    id                  BIGSERIAL PRIMARY KEY,
    actor_user_id       BIGINT REFERENCES users (id),
    action              TEXT NOT NULL,
    detail              TEXT,                       -- never secrets, codes or tokens
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_audit_log_time ON audit_log (created_at);
CREATE INDEX idx_audit_log_actor ON audit_log (actor_user_id, created_at);
