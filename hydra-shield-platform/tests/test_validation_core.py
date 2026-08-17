"""
Offline tests for the scientific validation core: Ground Truth Event
Registry, Benchmark Suite, Model Evaluation Framework, and their v2
endpoints.

No network: ``run_case`` is driven with injected synthetic fetchers (test
fixtures, not product data); the API tests use Flask's test client; the
evaluation-run store is pointed at a tmp directory.
"""

import json
import os
import re
from datetime import date, timedelta

import pytest

# Isolate the cache DB + evaluation dir for the whole test module.
os.environ["HYDRASHIELD_CACHE_DB"] = "/tmp/hydrashield_test_validation_cache.sqlite3"
if os.path.exists(os.environ["HYDRASHIELD_CACHE_DB"]):
    os.remove(os.environ["HYDRASHIELD_CACHE_DB"])

from src.dashboard.api import create_app  # noqa: E402
from src.climate import benchmark, evaluation  # noqa: E402

CONFIG_DIR = os.path.join(os.path.dirname(__file__), "..", "config")
GROUND_TRUTH_PATH = os.path.join(CONFIG_DIR, "ground_truth_events.json")
SUITE_PATH = os.path.join(CONFIG_DIR, "benchmark_suite.json")
MODEL_REGISTRY_PATH = os.path.join(CONFIG_DIR, "model_registry.json")

_HTTPS_RE = re.compile(r"^https://[a-z0-9.-]+\.[a-z]{2,}(/|$)", re.IGNORECASE)


def _load(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture()
def eval_dir(tmp_path, monkeypatch):
    """Isolated evaluation store (benchmark runs + evaluation runs)."""
    d = tmp_path / "evaluation"
    monkeypatch.setenv("HYDRASHIELD_EVALUATION_DIR", str(d))
    return d


@pytest.fixture()
def client(eval_dir, monkeypatch, tmp_path):
    monkeypatch.setenv("HYDRASHIELD_OUTBOX_DIR", str(tmp_path / "outbox"))
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.delenv("SMTP_USER", raising=False)
    import src.dashboard.cache as cache_mod

    monkeypatch.setattr(cache_mod, "_default_cache", None)
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


# ---------------------------------------------------------------------------
# Ground Truth Event Registry
# ---------------------------------------------------------------------------

_GT_REQUIRED = (
    "id", "hazard", "name", "location", "start", "end", "status",
    "evidence_class", "sources", "expected_signal", "region", "limitations",
)


def test_ground_truth_schema_and_https():
    doc = _load(GROUND_TRUTH_PATH)
    events = doc["events"]
    assert len(events) == 5
    ids = [e["id"] for e in events]
    assert len(set(ids)) == len(ids)
    for event in events:
        for field in _GT_REQUIRED:
            assert field in event, f"{event['id']}: missing '{field}'"
        assert event["status"] in ("DOCUMENTED", "OBSERVED", "key_required")
        assert "signal_basis" in event, f"{event['id']}: signal_basis required"
        assert event["sources"], f"{event['id']}: at least one source required"
        for source in event["sources"]:
            assert source.get("name")
            assert _HTTPS_RE.match(source.get("url") or ""), (
                f"{event['id']}: source url must be https: {source.get('url')}"
            )


def test_ground_truth_documented_events_have_signals():
    for event in _load(GROUND_TRUTH_PATH)["events"]:
        if event["status"] == "key_required":
            assert event["expected_signal"] is None
            assert "FIRMS_MAP_KEY" in event["limitations"]
            continue
        signal = event["expected_signal"]
        assert signal and signal.get("type") and signal.get("definition")
        start_s, end_s = signal["window"].split("..")
        ws, we = date.fromisoformat(start_s), date.fromisoformat(end_s)
        assert ws <= we
        assert signal["window"] == f"{event['start']}..{event['end']}"
        loc = event["location"]
        assert loc["name"] and -90 <= loc["lat"] <= 90 and -180 <= loc["lon"] <= 180


def test_ground_truth_seeded_event_ids():
    ids = {e["id"] for e in _load(GROUND_TRUTH_PATH)["events"]}
    assert ids == {
        "eu-heatwave-2022-07",
        "ahr-flood-2021-07",
        "storm-eunice-2022-02",
        "iberia-drought-2022",
        "wildfire-firms-benchmark-placeholder",
    }


# ---------------------------------------------------------------------------
# Benchmark Suite definition
# ---------------------------------------------------------------------------


def test_benchmark_suite_structure_and_model_ids():
    suite = _load(SUITE_PATH)
    assert suite["version"] == "1.0.0"
    cases = suite["cases"]
    gt_ids = {e["id"] for e in _load(GROUND_TRUTH_PATH)["events"]}
    model_ids = {m["id"] for m in _load(MODEL_REGISTRY_PATH)["models"]}
    assert {c["ground_truth_event_id"] for c in cases} == gt_ids, (
        "one case per ground-truth event"
    )
    for case in cases:
        for field in ("case_id", "ground_truth_event_id", "model_id",
                      "detection", "expected", "pass_criteria"):
            assert field in case, f"{case.get('case_id')}: missing '{field}'"
        assert case["model_id"] in model_ids, (
            f"{case['case_id']}: unknown model '{case['model_id']}'"
        )
        assert case["detection"].get("method")
        if case.get("execution") == "key_required":
            assert case["model_id"] == "fwi_system_v1"
            assert case["expected"] is None
        else:
            assert case["expected"]
        # Declared criteria must be parseable, checkable statements.
        assert isinstance(case["pass_criteria"], str) and case["pass_criteria"]
        assert any(
            token in case["pass_criteria"]
            for token in (">=", "<=", "detected", "not executable")
        ), f"{case['case_id']}: pass_criteria not a checkable statement"


def test_benchmark_suite_expected_model_assignments():
    cases = {c["ground_truth_event_id"]: c for c in _load(SUITE_PATH)["cases"]}
    assert cases["eu-heatwave-2022-07"]["model_id"] == "heat_percentile_v1"
    assert cases["ahr-flood-2021-07"]["model_id"] == "flood_discharge_percentile_v1"
    assert cases["storm-eunice-2022-02"]["model_id"] == "wind_percentile_v1"
    assert cases["iberia-drought-2022"]["model_id"] == "drought_anomaly_v1"
    assert cases["wildfire-firms-benchmark-placeholder"]["model_id"] == "fwi_system_v1"


# ---------------------------------------------------------------------------
# Lifecycle states
# ---------------------------------------------------------------------------


def test_lifecycle_chain_order_and_validator():
    assert evaluation.LIFECYCLE_STATES == (
        "experimental", "screening", "backtested", "validated",
        "operational", "deprecated",
    )
    for state in evaluation.LIFECYCLE_STATES:
        assert evaluation.validate_lifecycle(state) == state
        assert evaluation.is_valid_lifecycle(state)
    assert not evaluation.is_valid_lifecycle("promoted")
    with pytest.raises(evaluation.EvaluationError):
        evaluation.validate_lifecycle("validated_operational")
    assert evaluation.lifecycle_index("backtested") > evaluation.lifecycle_index("screening")
    assert evaluation.lifecycle_index("operational") > evaluation.lifecycle_index("validated")


def test_all_registry_models_have_valid_lifecycle():
    doc = _load(MODEL_REGISTRY_PATH)
    chain = [s["state"] for s in doc["lifecycle_states"]]
    assert chain == list(evaluation.LIFECYCLE_STATES)
    assert len(doc["models"]) >= 13
    for model in doc["models"]:
        assert evaluation.is_valid_lifecycle(model.get("lifecycle")), (
            f"model '{model['id']}': invalid lifecycle {model.get('lifecycle')!r}"
        )


def test_lifecycle_assignments():
    models = {m["id"]: m for m in _load(MODEL_REGISTRY_PATH)["models"]}
    assert models["fwi_system_v1"]["lifecycle"] == "backtested"
    assert "not site-validated" in models["fwi_system_v1"]["lifecycle_note"].lower()
    for mid in ("composite_wildfire_risk_v1", "fire_spread_screening_v1",
                "ignition_likelihood_v1", "smoke_corridor_v1",
                "drought_anomaly_v1", "heat_percentile_v1", "wind_percentile_v1",
                "flood_discharge_percentile_v1", "coastal_slr_scenarios_v1",
                "population_exposure_v1", "fire_events_v1"):
        assert models[mid]["lifecycle"] == "screening", mid
    assert models["risk_framework_v1"]["lifecycle"] == "experimental"


# ---------------------------------------------------------------------------
# Evaluation run records
# ---------------------------------------------------------------------------


def test_run_record_list_get_roundtrip(eval_dir):
    path = evaluation.record_run(
        "heat_percentile_v1", "1.0.0", "benchmark_suite",
        "ERA5 daily Tmax (Open-Meteo archive)",
        {"cases": 1, "passed": 1},
        code_version="test",
    )
    assert os.path.exists(path)
    run_id = os.path.basename(path)[:-5]
    assert re.fullmatch(r"[0-9a-f]{64}", run_id)

    runs = evaluation.list_runs()
    assert [r["run_id"] for r in runs] == [run_id]
    assert evaluation.list_runs(model_id="heat_percentile_v1")[0]["run_id"] == run_id
    assert evaluation.list_runs(model_id="other_model") == []

    record = evaluation.get_run(run_id)
    for field in ("run_id", "model_id", "model_version", "kind", "dataset",
                  "metrics", "calibration", "fp_fn", "geographic_performance",
                  "temporal_performance", "failure_cases", "executed_at",
                  "code_version"):
        assert field in record, f"missing '{field}'"
    assert record["kind"] == "benchmark_suite"
    assert evaluation.get_run("0" * 64) is None
    assert evaluation.get_run("../etc/passwd") is None


def test_run_records_are_immutable(eval_dir):
    kwargs = dict(code_version="test", executed_at="2026-08-17T00:00:00Z")
    path1 = evaluation.record_run("m", "1.0.0", "benchmark_suite", "d", {"a": 1}, **kwargs)
    path2 = evaluation.record_run("m", "1.0.0", "benchmark_suite", "d", {"a": 1}, **kwargs)
    assert path1 == path2  # identical content → identical content-hash file
    path3 = evaluation.record_run("m", "1.0.0", "benchmark_suite", "d", {"a": 2}, **kwargs)
    assert path3 != path1
    assert len(evaluation.list_runs()) == 2


def test_run_record_rejects_bad_kind(eval_dir):
    with pytest.raises(evaluation.EvaluationError):
        evaluation.record_run("m", "1.0.0", "unit_test", "d", {})


def test_fwi_reference_run_recording(eval_dir):
    path = evaluation.record_fwi_reference_run(code_version="test")
    record = evaluation.get_run(os.path.basename(path)[:-5])
    assert record["model_id"] == "fwi_system_v1"
    assert record["kind"] == "equation_reference"
    assert record["dataset"] == "cffdrs reference outputs"
    checks = record["metrics"]["equation_checks"]
    assert checks["test_file"] == "tests/test_fwi.py"
    assert checks["test_count"] == evaluation._fwi_test_count() >= 8
    assert checks["result"] == "passed"
    assert "NOT a site-validated" in record["metrics"]["scope"]


# ---------------------------------------------------------------------------
# run_case with synthetic fetchers (fixtures, not product data)
# ---------------------------------------------------------------------------


def _daily_payload(start: date, end: date, variable, value_fn, source="synthetic fixture"):
    days = (end - start).days + 1
    dates = [start + timedelta(days=i) for i in range(days)]
    return {
        "time": [d.isoformat() for d in dates],
        variable: [value_fn(d) for d in dates],
        "source": source,
    }


def _case(gt_event_id):
    for case in _load(SUITE_PATH)["cases"]:
        if case["ground_truth_event_id"] == gt_event_id:
            return case
    raise AssertionError(f"no case for {gt_event_id}")


def _heat_fetchers(spike):
    """ERA5 Tmax fixture: baseline 18–22°C pattern; optional 3-day 30°C spike."""

    def fetch(lat, lon, start, end, variables):
        def value(d):
            if spike and date(2022, 7, 17) <= d <= date(2022, 7, 19):
                return 30.0
            if d.year == 2022:
                return 19.0
            return 18.0 + (d.timetuple().tm_yday % 5)
        return _daily_payload(date.fromisoformat(start), date.fromisoformat(end),
                              "temperature_2m_max", value, "ERA5 Tmax fixture")
    return fetch


def test_run_case_heat_passed():
    result = benchmark.run_case(
        _case("eu-heatwave-2022-07"), fetch_daily_climate=_heat_fetchers(spike=True))
    assert result["executed"] is True
    assert result["status"] == "passed"
    assert result["model_id"] == "heat_percentile_v1"
    assert result["window"] == "2022-07-15..2022-07-25"
    assert result["evidence"]["spells_overlapping_window"], result["evidence"]
    assert result["evidence"]["window_peak_tmax_c"]["tmax_c"] == 30.0
    assert result["data_sources"]


def test_run_case_heat_failed():
    result = benchmark.run_case(
        _case("eu-heatwave-2022-07"), fetch_daily_climate=_heat_fetchers(spike=False))
    assert result["executed"] is True
    assert result["status"] == "failed"
    assert result["evidence"]["spells_overlapping_window"] == []


def _wind_fetchers(spike):
    def fetch(lat, lon, start, end, variables):
        def value(d):
            if spike and d == date(2022, 2, 18):
                return 60.0
            if d.year == 2022:
                return 20.0
            return 28.0 + (d.timetuple().tm_yday % 7)
        return _daily_payload(date.fromisoformat(start), date.fromisoformat(end),
                              "wind_gusts_10m_max", value, "ERA5 gust fixture")
    return fetch


def test_run_case_wind_passed_and_failed():
    case = _case("storm-eunice-2022-02")
    passed = benchmark.run_case(case, fetch_daily_climate=_wind_fetchers(spike=True))
    assert passed["status"] == "passed"
    extreme = passed["evidence"]["extreme_days"]
    assert extreme and extreme[0]["date"] == "2022-02-18"
    assert extreme[0]["doy_percentile"] >= 95

    failed = benchmark.run_case(case, fetch_daily_climate=_wind_fetchers(spike=False))
    assert failed["status"] == "failed"
    assert failed["evidence"]["extreme_days"] == []


def _drought_fetch(dry):
    def fetch(lat, lon, start, end, variables):
        def value(d):
            if dry and d.year == 2022 and d >= date(2022, 6, 1):
                return 0.0
            return 2.0 + 0.1 * (d.year % 3)
        return _daily_payload(date.fromisoformat(start), date.fromisoformat(end),
                              "precipitation_sum", value, "ERA5 precip fixture")
    return fetch


def test_run_case_drought_passed_and_failed():
    case = _case("iberia-drought-2022")
    passed = benchmark.run_case(case, fetch_daily_climate=_drought_fetch(dry=True))
    assert passed["status"] == "passed"
    ev = passed["evidence"]
    assert ev["standardized_anomaly"] <= -0.8
    assert ev["current_period"]["end"] == "2022-08-31"
    assert ev["dry_spells_in_window"], ev

    failed = benchmark.run_case(case, fetch_daily_climate=_drought_fetch(dry=False))
    assert failed["status"] == "failed"


def _flood_fetchers(spike):
    def fetch_daily(lat, lon, start, end, variables):
        def value(d):
            if date(2021, 7, 12) <= d <= date(2021, 7, 20):
                if spike and d <= date(2021, 7, 14):
                    return 60.0
                if not spike:
                    return 0.5  # genuinely dry window vs a varied record
            return 1.0 + (d.timetuple().tm_yday % 3) * 0.5
        return _daily_payload(date.fromisoformat(start), date.fromisoformat(end),
                              "precipitation_sum", value, "ERA5 precip fixture")

    def fetch_discharge(lat, lon, start, end):
        def value(d):
            if date(2021, 7, 12) <= d <= date(2021, 7, 20):
                if spike and date(2021, 7, 14) <= d <= date(2021, 7, 16):
                    return 300.0
                if not spike:
                    return 5.0  # genuinely low-flow window vs a varied record
            return 10.0 + (d.timetuple().tm_yday % 2)
        return _daily_payload(date.fromisoformat(start), date.fromisoformat(end),
                              "river_discharge", value, "GloFAS discharge fixture")

    return fetch_daily, fetch_discharge


def test_run_case_flood_passed():
    fetch_daily, fetch_discharge = _flood_fetchers(spike=True)
    result = benchmark.run_case(
        _case("ahr-flood-2021-07"),
        fetch_daily_climate=fetch_daily, fetch_flood_discharge=fetch_discharge)
    assert result["executed"] is True
    assert result["status"] == "passed"
    ev = result["evidence"]
    assert ev["best_7day_total"]["percentile_vs_record"] >= 90
    assert ev["best_discharge_day"]["percentile_vs_own_series"] >= 90


def test_run_case_flood_failed():
    fetch_daily, fetch_discharge = _flood_fetchers(spike=False)
    result = benchmark.run_case(
        _case("ahr-flood-2021-07"),
        fetch_daily_climate=fetch_daily, fetch_flood_discharge=fetch_discharge)
    assert result["executed"] is True
    assert result["status"] == "failed"


def test_run_case_key_required_never_fetches():
    def explode(*a, **k):
        raise AssertionError("key_required case must not fetch")
    result = benchmark.run_case(
        _case("wildfire-firms-benchmark-placeholder"),
        fetch_daily_climate=explode, fetch_flood_discharge=explode)
    assert result["executed"] is False
    assert result["status"] == "key_required"
    assert "FIRMS_MAP_KEY" in result["evidence"]["reason"]


def test_run_case_error_is_captured_not_raised():
    def broken(lat, lon, start, end, variables):
        return {"error": "fixture outage"}
    result = benchmark.run_case(
        _case("storm-eunice-2022-02"), fetch_daily_climate=broken)
    assert result["executed"] is False
    assert result["status"] == "error"
    assert "fixture outage" in result["evidence"]["error"]


def test_run_suite_writes_immutable_run(eval_dir):
    fetch_daily, fetch_discharge = _flood_fetchers(spike=True)
    # Drive the full suite offline: heat/drought share the precip/tmax shape
    # via a dispatching fixture; wind and wildfire behave as declared above.
    def daily(lat, lon, start, end, variables):
        var = variables[0]
        if var == "temperature_2m_max":
            return _heat_fetchers(spike=True)(lat, lon, start, end, variables)
        if var == "wind_gusts_10m_max":
            return _wind_fetchers(spike=True)(lat, lon, start, end, variables)
        return _drought_fetch(dry=True)(lat, lon, start, end, variables)

    import src.climate.benchmark as bm

    orig_daily, orig_dis = bm._fetch_daily_climate, bm._fetch_flood_discharge
    bm._fetch_daily_climate, bm._fetch_flood_discharge = daily, fetch_discharge
    try:
        run = bm.run_suite()
    finally:
        bm._fetch_daily_climate, bm._fetch_flood_discharge = orig_daily, orig_dis

    summary = run["summary"]
    assert summary == {"total": 5, "passed": 4, "failed": 0,
                       "key_required": 1, "errors": 0}
    assert os.path.exists(run["run_file"])
    with open(run["run_file"], "r", encoding="utf-8") as fh:
        on_disk = json.load(fh)
    assert on_disk["summary"] == summary
    latest = bm.latest_run_summary()
    assert latest["run_file"] == run["run_file"]
    assert latest["summary"] == summary


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------


def test_ground_truth_endpoints(client):
    resp = client.get("/api/v2/ground-truth")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["count"] == 5

    resp = client.get("/api/v2/ground-truth?hazard=flood")
    body = resp.get_json()
    assert resp.status_code == 200
    assert body["count"] == 1
    assert body["events"][0]["id"] == "ahr-flood-2021-07"

    resp = client.get("/api/v2/ground-truth/eu-heatwave-2022-07")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "DOCUMENTED"

    assert client.get("/api/v2/ground-truth/no-such-event").status_code == 404


def test_benchmarks_endpoint(client):
    resp = client.get("/api/v2/benchmarks")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["suite"]["version"] == "1.0.0"
    assert len(body["suite"]["cases"]) == 5
    assert body["latest_run"] is None  # isolated, empty evaluation dir


def test_evaluations_endpoints(client):
    path = evaluation.record_fwi_reference_run(code_version="test")
    run_id = os.path.basename(path)[:-5]

    resp = client.get("/api/v2/evaluations")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["count"] == 1
    assert body["lifecycle_states"] == list(evaluation.LIFECYCLE_STATES)

    resp = client.get("/api/v2/evaluations?model_id=fwi_system_v1")
    assert resp.get_json()["count"] == 1
    resp = client.get("/api/v2/evaluations?model_id=heat_percentile_v1")
    assert resp.get_json()["count"] == 0

    resp = client.get(f"/api/v2/evaluations/{run_id}")
    assert resp.status_code == 200
    assert resp.get_json()["run_id"] == run_id

    assert client.get("/api/v2/evaluations/" + "f" * 64).status_code == 404
    assert client.get("/api/v2/evaluations/not-a-run-id").status_code == 404


def test_benchmarks_run_requires_auth(client):
    resp = client.post("/api/v2/benchmarks/run")
    assert resp.status_code == 401


def test_benchmarks_run_requires_admin(client, tmp_path):
    # A registered (non-admin) user is gated with 403, never executes the suite.
    resp = client.post("/api/v2/auth/register",
                       json={"email": "bench@example.org",
                             "password": "correct horse battery",
                             "display_name": "Bench User", "consent": True})
    assert resp.status_code == 201, resp.get_json()
    outbox = tmp_path / "outbox"
    files = sorted(outbox.glob("*_email_verification_*.eml"))
    assert files, "no verification email in outbox"
    import email as email_lib
    from email import policy

    msg = email_lib.message_from_string(
        files[-1].read_text(encoding="utf-8"), policy=policy.default)
    body = msg.get_body(("plain",))
    plain = body.get_content() if body else ""
    token = re.search(r"token=([A-Za-z0-9_\-]+)", plain).group(1)
    resp = client.get(f"/api/v2/auth/verify?token={token}")
    assert resp.status_code == 200, resp.get_json()
    session = resp.get_json()["session_token"]

    resp = client.post("/api/v2/benchmarks/run",
                       headers={"Authorization": f"Bearer {session}"})
    assert resp.status_code == 403
    assert resp.get_json()["upgrade"]["required_role"] == "admin"
