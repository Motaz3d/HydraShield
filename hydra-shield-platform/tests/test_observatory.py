"""
Offline tests for the Observatory layer: source-health intelligence,
reproducible analysis runs, data-quality profiles, the evidence
confidence profile, and the PostGIS design artefacts.

Everything here runs without network access: the source-health probe
(src.climate.source_health._http_get) is monkeypatched, registries are
config files, and stores are pointed at tmp_path SQLite files.
"""

import os
from types import SimpleNamespace

import pytest

os.environ["HYDRASHIELD_CACHE_DB"] = "/tmp/hydrashield_test_observatory_cache.sqlite3"
if os.path.exists(os.environ["HYDRASHIELD_CACHE_DB"]):
    os.remove(os.environ["HYDRASHIELD_CACHE_DB"])

from src.dashboard.api import create_app  # noqa: E402
from src.climate import data_registry, registry, source_health, uncertainty  # noqa: E402
from src.climate.api_observatory import observatory_bp  # noqa: E402
from src.dashboard import analysis_runs  # noqa: E402

_NEW_CANDIDATE_IDS = (
    "eccc", "saws", "ncm-uae", "inmet", "smn-mexico", "smn-argentina",
    "dmc-chile", "senamhi", "marocmeteo", "ncm-saudi", "mss-singapore",
    "bmkg",
)

_PROFILE_KEYS = {
    "freshness", "completeness", "spatial_resolution_note",
    "temporal_resolution_note", "provenance_note", "validation",
    "coverage_note", "licensing_note",
}

_DIMENSIONS = (
    "source_quality", "recency", "coverage", "method_transparency",
    "validation_status", "independence",
)


def _db(tmp_path, name="obs.sqlite3"):
    return str(tmp_path / name)


def _patch_db(monkeypatch, module, db_path):
    """Point a store module's default_cache at a tmp DB."""
    monkeypatch.setattr(module, "default_cache",
                        lambda: SimpleNamespace(db_path=db_path))


@pytest.fixture()
def client():
    app = create_app()
    # The lead registers observatory_bp in src/dashboard/api.py; register
    # it here only when that wiring is not present yet.
    if "observatory" not in app.blueprints:
        app.register_blueprint(observatory_bp)
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


# ---------------------------------------------------------------------------
# Source health: store roundtrip + status-change detection (no network)
# ---------------------------------------------------------------------------

def test_source_health_roundtrip_and_status_changes(tmp_path, monkeypatch):
    db = _db(tmp_path, "health.sqlite3")
    store = source_health.SourceHealthStore(db)

    monkeypatch.setattr(source_health, "_http_get",
                        lambda url: (200, 42.0, True, None))
    integrated = data_registry.by_status("integrated")
    summary = source_health.check_integrated_sources(store=store)
    assert summary["checked"] == len(integrated) == summary["ok"]
    assert summary["down"] == 0
    assert {t["status_change"] for t in summary["transitions"]} == {"new"}
    assert len(summary["transitions"]) == len(integrated)

    health = source_health.latest_health(store=store)
    assert len(health["datasets"]) == len(integrated)
    assert all(d["health"] == "ok" for d in health["datasets"].values())
    assert len(health["changes"]) == len(integrated)  # the "new" records

    # Everything goes down → ok_to_down transitions, health=down.
    monkeypatch.setattr(source_health, "_http_get",
                        lambda url: (None, 10000.0, False, "timeout"))
    summary = source_health.check_integrated_sources(store=store)
    assert summary["ok"] == 0
    assert {t["status_change"] for t in summary["transitions"]} == {"ok_to_down"}
    health = source_health.latest_health(store=store)
    assert all(d["health"] == "down" for d in health["datasets"].values())

    # Recovery → down_to_ok. Slow but reachable → degraded.
    monkeypatch.setattr(source_health, "_http_get",
                        lambda url: (200, 6000.0, True, None))
    summary = source_health.check_integrated_sources(store=store)
    assert {t["status_change"] for t in summary["transitions"]} == {"down_to_ok"}
    health = source_health.latest_health(store=store)
    assert all(d["health"] == "degraded" for d in health["datasets"].values())

    # Stable state → no transitions recorded.
    summary = source_health.check_integrated_sources(store=store)
    assert summary["transitions"] == []

    # Per-dataset lookup + honest miss for an unknown id.
    one = source_health.latest_health(dataset_id="open-meteo-forecast", store=store)
    assert set(one["datasets"]) == {"open-meteo-forecast"}
    assert one["datasets"]["open-meteo-forecast"]["http_status"] == 200
    assert source_health.latest_health(dataset_id="nope", store=store)["datasets"] == {}


def test_source_health_error_status_is_down_not_ok(tmp_path, monkeypatch):
    db = _db(tmp_path, "health_err.sqlite3")
    store = source_health.SourceHealthStore(db)
    monkeypatch.setattr(source_health, "_http_get",
                        lambda url: (503, 120.0, False, "HTTP 503"))
    summary = source_health.check_integrated_sources(store=store)
    assert summary["down"] == summary["checked"]
    record = store.previous("open-meteo-forecast")
    assert record["http_status"] == 503
    assert record["ok"] is False
    assert record["status_change"] == "new"


# ---------------------------------------------------------------------------
# API: /api/v2/source-health (honest empty state, then populated)
# ---------------------------------------------------------------------------

def test_api_source_health_empty_state(client, tmp_path, monkeypatch):
    _patch_db(monkeypatch, source_health, _db(tmp_path, "empty.sqlite3"))
    resp = client.get("/api/v2/source-health")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["datasets"] == {}
    assert body["changes"] == []
    assert "No source-health checks recorded yet" in body["note"]


def test_api_source_health_populated(client, tmp_path, monkeypatch):
    _patch_db(monkeypatch, source_health, _db(tmp_path, "populated.sqlite3"))
    monkeypatch.setattr(source_health, "_http_get",
                        lambda url: (200, 30.0, True, None))
    source_health.check_integrated_sources()  # writes via patched default DB

    resp = client.get("/api/v2/source-health")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["datasets"]
    assert all("health" in d for d in body["datasets"].values())
    assert "No source-health checks recorded yet" not in body["note"]

    resp = client.get("/api/v2/source-health?dataset_id=open-meteo-forecast")
    assert resp.status_code == 200
    record = resp.get_json()["datasets"]["open-meteo-forecast"]
    assert record["health"] == "ok"
    assert record["http_status"] == 200
    assert record["ok"] is True


# ---------------------------------------------------------------------------
# Analysis runs: record / get / list / reproducibility
# ---------------------------------------------------------------------------

def _run_kwargs(result=None):
    return dict(
        endpoint="/api/v2/analyze",
        hazard="wildfire",
        lat=40.1,
        lon=6.2,
        params={"name": None, "raw": False},
        result=result or {"hazard": "wildfire", "status": "ok",
                          "level": {"score": 42}},
        model_versions={"fwi_system_v1": "1.0.0"},
        dataset_versions={"open-meteo-forecast": "current"},
        methodology="test methodology",
        uncertainty={"confidence": "medium"},
        evidence=[{"source": "test"}],
    )


def test_analysis_runs_record_get_list(tmp_path):
    db = _db(tmp_path, "runs.sqlite3")
    analysis_id = analysis_runs.record_run(db_path=db, **_run_kwargs())
    assert analysis_id.startswith("ar_")

    run = analysis_runs.get_run(analysis_id, db_path=db)
    assert run["analysis_id"] == analysis_id
    assert run["hazard"] == "wildfire"
    assert run["lat"] == 40.1 and run["lon"] == 6.2
    assert run["result_hash"]
    assert run["model_versions"] == {"fwi_system_v1": "1.0.0"}
    assert run["executed_at"]  # kept as a field…
    assert run["uncertainty"] == {"confidence": "medium"}

    assert analysis_runs.get_run("ar_missing", db_path=db) is None
    assert analysis_runs.list_runs(db_path=db)
    assert analysis_runs.list_runs(hazard="wildfire", db_path=db)
    assert analysis_runs.list_runs(hazard="flood", db_path=db) == []


def test_analysis_runs_reproducible_id_excludes_volatile_timestamps(tmp_path):
    db = _db(tmp_path, "runs_repro.sqlite3")
    id1 = analysis_runs.record_run(db_path=db, **_run_kwargs())
    id2 = analysis_runs.record_run(db_path=db, **_run_kwargs())
    assert id1 == id2  # executed_at is NOT part of the id basis
    assert len(analysis_runs.list_runs(db_path=db)) == 1  # upserted, not duplicated

    different = _run_kwargs(result={"hazard": "wildfire", "status": "ok",
                                    "level": {"score": 43}})
    id3 = analysis_runs.record_run(db_path=db, **different)
    assert id3 != id1
    assert len(analysis_runs.list_runs(db_path=db)) == 2


def test_analyze_endpoint_records_run(client, tmp_path, monkeypatch):
    db = _db(tmp_path, "api_runs.sqlite3")
    _patch_db(monkeypatch, analysis_runs, db)

    class _FakeResult:
        def to_dict(self, include_raw=False):
            return {"hazard": "wildfire", "status": "ok",
                    "level": {"score": 42}, "methodology": "fake"}

    module = registry.get("wildfire")
    assert module is not None
    monkeypatch.setattr(module, "analyze",
                        lambda lat, lon, name=None: _FakeResult())
    monkeypatch.setattr(module, "availability", lambda: (True, None))

    resp = client.get("/api/v2/analyze?hazard=wildfire&lat=40.1&lon=6.2")
    assert resp.status_code == 200

    runs = analysis_runs.list_runs(db_path=db)
    assert len(runs) == 1
    run = runs[0]
    assert run["endpoint"] == "/api/v2/analyze"
    assert run["hazard"] == "wildfire"
    assert run["lat"] == 40.1 and run["lon"] == 6.2
    assert run["result_hash"]
    assert run["model_versions"]  # from config/model_registry.json
    assert run["dataset_versions"]  # integrated ids from data_registry.json


# ---------------------------------------------------------------------------
# API: /api/v2/analysis-runs
# ---------------------------------------------------------------------------

def test_api_analysis_runs(client, tmp_path, monkeypatch):
    db = _db(tmp_path, "api_list.sqlite3")
    _patch_db(monkeypatch, analysis_runs, db)
    aid = analysis_runs.record_run(db_path=db, **_run_kwargs())

    resp = client.get("/api/v2/analysis-runs")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["count"] == 1
    assert body["runs"][0]["analysis_id"] == aid

    resp = client.get("/api/v2/analysis-runs?hazard=wildfire&limit=10")
    assert resp.get_json()["count"] == 1
    resp = client.get("/api/v2/analysis-runs?hazard=flood")
    assert resp.get_json()["count"] == 0

    resp = client.get(f"/api/v2/analysis-runs/{aid}")
    assert resp.status_code == 200
    assert resp.get_json()["analysis_id"] == aid

    resp = client.get("/api/v2/analysis-runs/ar_missing")
    assert resp.status_code == 404
    assert "error" in resp.get_json()

    assert client.get("/api/v2/analysis-runs?limit=abc").status_code == 400
    assert client.get("/api/v2/analysis-runs?limit=0").status_code == 400


# ---------------------------------------------------------------------------
# Data-quality profiles: integrated ⇒ present, candidate ⇒ absent
# ---------------------------------------------------------------------------

def test_data_quality_profile_presence_rules():
    integrated = data_registry.by_status("integrated")
    assert integrated
    for entry in integrated:
        profile = entry.get("data_quality_profile")
        assert profile, f"{entry['id']}: integrated entry missing profile"
        assert set(profile) == _PROFILE_KEYS, \
            f"{entry['id']}: profile keys {sorted(profile)}"
        assert all(profile[k] for k in _PROFILE_KEYS), \
            f"{entry['id']}: empty profile field"
    for entry in data_registry.by_status("candidate"):
        assert "data_quality_profile" not in entry, \
            f"{entry['id']}: candidate carries a profile claim"


def test_new_candidates_validate_and_are_candidates():
    # data_registry.all() runs the full existing document validation.
    entries = data_registry.all()
    assert len(entries) >= 67  # 55 baseline + 12 new candidates
    for cid in _NEW_CANDIDATE_IDS:
        entry = data_registry.get(cid)
        assert entry is not None, f"missing candidate '{cid}'"
        assert entry["status"] == "candidate"
        assert entry["hazard_relevance"], f"{cid}: hazard_relevance empty"
        assert entry["url"].startswith("https://")


# ---------------------------------------------------------------------------
# Evidence Confidence Profile (multi-dimensional, no single score)
# ---------------------------------------------------------------------------

def test_confidence_profile_dimensions_no_single_score():
    profile = uncertainty.confidence_profile(
        source_kind="official_observation", freshness_days=1,
        coverage_note="Global land", method_documented=True,
        validation_status="validated_operational", independent_sources=3)
    d = profile.to_dict()
    for dim in _DIMENSIONS:
        assert d[dim] == "high"
    assert "score" not in d and "overall" not in d
    assert "NOT collapsible" in d["summary_note"]
    assert d["notes"] is None


def test_confidence_profile_mapping_rules():
    low = uncertainty.confidence_profile(
        source_kind="media", freshness_days=400, coverage_note="one valley",
        method_documented=False, validation_status="not_validated",
        independent_sources=1).to_dict()
    assert low["source_quality"] == "low"
    assert low["recency"] == "low"
    assert low["coverage"] == "low"
    assert low["method_transparency"] == "low"
    assert low["validation_status"] == "low"
    assert low["independence"] == "low"

    mid = uncertainty.confidence_profile(
        source_kind="commercial_api", freshness_days=10,
        coverage_note="regional network", method_documented=True,
        validation_status="validated_screening", independent_sources=2)
    assert mid.recency == "medium"
    assert mid.coverage == "medium"
    assert mid.validation_status == "medium"
    assert mid.independence == "medium"
    assert mid.source_quality == "medium"

    # unknown is first-class: nothing declared → everything unknown
    blank = uncertainty.confidence_profile()
    for dim in _DIMENSIONS:
        assert getattr(blank, dim) == "unknown"

    with pytest.raises(ValueError):
        uncertainty.EvidenceConfidence(source_quality="very-high")


def test_confidence_profile_deterministic():
    kwargs = dict(source_kind="reanalysis", freshness_days=10,
                  coverage_note="Global", method_documented=True,
                  validation_status="not_validated", independent_sources=2)
    assert uncertainty.confidence_profile(**kwargs).to_dict() == \
        uncertainty.confidence_profile(**kwargs).to_dict()


# ---------------------------------------------------------------------------
# PostGIS design artefacts
# ---------------------------------------------------------------------------

def test_postgis_design_files_exist_and_are_spatial():
    root = os.path.join(os.path.dirname(__file__), "..")
    ddl_path = os.path.join(root, "db", "migrations", "0001_init.sql")
    doc_path = os.path.join(root, "docs", "DATA_MODEL_POSTGIS.md")
    assert os.path.exists(ddl_path)
    assert os.path.exists(doc_path)

    with open(ddl_path, encoding="utf-8") as fh:
        sql = fh.read().upper()
    assert "CREATE EXTENSION IF NOT EXISTS POSTGIS" in sql
    assert "CREATE TABLE" in sql
    assert "USING GIST" in sql
    assert "GEOGRAPHY(POINT, 4326)" in sql
    for table in ("DATASETS", "MODELS", "RESEARCH_REFS", "GROUND_TRUTH_EVENTS",
                  "CLIMATE_EVENTS", "EVALUATION_RUNS", "BENCHMARK_RUNS",
                  "ANALYSIS_RUNS", "SOURCE_HEALTH", "USERS", "SESSIONS",
                  "API_KEYS", "ALERT_RULES", "ALERT_RECORDS",
                  "ALERT_DELIVERIES", "WEBHOOK_SUBSCRIPTIONS", "USAGE_EVENTS",
                  "AUDIT_LOG"):
        assert f"CREATE TABLE {table}" in sql, f"missing table {table}"
    for col in ("EVIDENCE_ID", "CONTENT_HASH", "DATASET_VERSION",
                "MODEL_VERSION", "VALID_FROM", "VALID_TO"):
        assert col in sql, f"missing provenance/versioning column {col}"

    with open(doc_path, encoding="utf-8") as fh:
        doc = fh.read().lower()
    assert "dual-write" in doc
    assert "backfill" in doc
    assert "read-switch" in doc
    assert "design only" in doc
