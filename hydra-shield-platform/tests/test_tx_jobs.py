"""Tests for the standard TX Job Object (tx_core.jobs) and its web wiring.

Network-free: runners execute synchronously over injected fake engines; the
Flask blueprint is tested with the module runner replaced. The contract
under test: POST /api/tx/run -> job_id -> poll -> result, with idempotent
submission, honest failures, and no fabricated results.
"""

from __future__ import annotations

import time
from typing import Any, List

import pytest

import tx_core
from tx_core.engine import TXEngine
from tx_core.jobs import TxJob, TxJobRunner, TxJobStore, make_job_id

from tests.test_tx_core import FakeHazardModule, make_engine


# ---------------------------------------------------------------------------
# Deterministic job ids
# ---------------------------------------------------------------------------

def test_job_id_deterministic_and_input_sensitive():
    a = make_job_id(lat=41.5, lon=-8.6, hazards=["flood"], depth="standard")
    b = make_job_id(lat=41.5, lon=-8.6, hazards=["flood"], depth="standard")
    c = make_job_id(lat=41.51, lon=-8.6, hazards=["flood"], depth="standard")
    d = make_job_id(lat=41.5, lon=-8.6, hazards=["heat"], depth="standard")
    e = make_job_id(lat=41.5, lon=-8.6, hazards=None, depth="standard")
    f = make_job_id(lat=41.5, lon=-8.6, hazards=["flood"], depth="deep")
    assert a == b
    assert a.startswith("TXJ-")
    for other in (c, d, e, f):
        assert a != other


def test_job_id_hazards_order_insensitive():
    a = make_job_id(lat=1, lon=2, hazards=["flood", "heat"])
    b = make_job_id(lat=1, lon=2, hazards=["heat", "flood"])
    assert a == b


# ---------------------------------------------------------------------------
# TxJob / store
# ---------------------------------------------------------------------------

def test_job_status_dict_excludes_result_and_bookkeeping():
    job = TxJob(job_id="TXJ-20260901-abcdef12", request={"lat": 1, "lon": 2})
    d = job.to_status_dict()
    assert d["job_id"] == "TXJ-20260901-abcdef12"
    assert d["status"] == "queued"
    assert d["progress"] == {"completed": 0, "total": 0}
    assert "result" not in d
    assert "created_epoch" not in d
    assert d["tx_version"] == tx_core.TX_VERSION


def test_store_put_if_absent_is_atomic_idempotent():
    store = TxJobStore()
    first = TxJob(job_id="J1", request={})
    _, created1 = store.put_if_absent(first)
    second = TxJob(job_id="J1", request={"other": True})
    winner, created2 = store.put_if_absent(second)
    assert created1 is True
    assert created2 is False
    assert winner is first  # the original job wins the race


def test_store_update_and_unknown_field():
    store = TxJobStore()
    store.put_if_absent(TxJob(job_id="J1", request={}))
    job = store.update("J1", status="running")
    assert job.status == "running"
    assert store.get("J1").status == "running"
    with pytest.raises(AttributeError):
        store.update("J1", no_such_field=1)
    assert store.update("gone", status="running") is None


def test_store_ttl_eviction():
    store = TxJobStore(ttl_seconds=60)
    old = TxJob(job_id="OLD", request={})
    old.created_epoch = time.time() - 3600  # submitted an hour ago
    store.put_if_absent(old)
    store.put_if_absent(TxJob(job_id="NEW", request={}))
    assert store.get("OLD") is None
    assert store.get("NEW") is not None


def test_store_overflow_evicts_oldest():
    store = TxJobStore(max_jobs=2)
    for i in range(3):
        job = TxJob(job_id=f"J{i}", request={})
        job.created_epoch = time.time() + i  # J0 oldest
        store.put_if_absent(job)
    assert store.get("J0") is None
    assert store.get("J1") is not None
    assert store.get("J2") is not None


# ---------------------------------------------------------------------------
# Runner lifecycle (synchronous, fake engine)
# ---------------------------------------------------------------------------

def _sync_runner(engine: TXEngine) -> TxJobRunner:
    return TxJobRunner(
        store=TxJobStore(), engine_factory=lambda: engine, synchronous=True
    )


def test_runner_success_lifecycle():
    runner = _sync_runner(make_engine({"flood": FakeHazardModule("flood")}))
    job, created = runner.submit(lat=40.0, lon=-8.0, hazards=["flood"])
    assert created is True
    assert job.status == "succeeded"
    assert job.started_at and job.finished_at
    assert job.progress == {"completed": 1, "total": 1}
    assert job.error is None
    result = job.result
    assert result["analysis_id"].startswith("TX-")
    assert result["results"][0]["hazard"] == "flood"
    assert result["engine_version"] == tx_core.TX_VERSION


def test_runner_progress_per_hazard():
    runner = _sync_runner(make_engine({
        "flood": FakeHazardModule("flood"),
        "heat": FakeHazardModule("heat"),
    }))
    job, _ = runner.submit(lat=0, lon=0, hazards=["flood", "heat"])
    assert job.progress == {"completed": 2, "total": 2}


def test_runner_failure_is_honest():
    class BoomEngine:
        def analyze(self, **kw: Any) -> Any:
            raise RuntimeError("upstream exploded")

    runner = _sync_runner(BoomEngine())
    job, _ = runner.submit(lat=1, lon=2, hazards=["flood"])
    assert job.status == "failed"
    assert "upstream exploded" in job.error
    assert job.result is None  # never a fabricated result
    assert job.finished_at


def test_runner_idempotent_resubmission_does_not_rerun():
    calls: List[int] = []
    engine = make_engine({"flood": FakeHazardModule("flood")})

    def factory() -> TXEngine:
        calls.append(1)
        return engine

    runner = TxJobRunner(
        store=TxJobStore(), engine_factory=factory, synchronous=True
    )
    job1, created1 = runner.submit(lat=40, lon=-8, hazards=["flood"], depth="deep")
    job2, created2 = runner.submit(lat=40, lon=-8, hazards=["flood"], depth="deep")
    assert created1 is True
    assert created2 is False
    assert job1.job_id == job2.job_id
    assert len(calls) == 1  # second submission reused the existing job


def test_engine_progress_callback_errors_never_break_analysis():
    engine = make_engine({"flood": FakeHazardModule("flood")})

    def bad_callback(*a: Any) -> None:
        raise RuntimeError("callback exploded")

    result = engine.analyze(lat=1, lon=2, on_hazard=bad_callback)
    assert result.status == "ok"


def test_engine_on_hazard_reports_index_and_total():
    engine = make_engine({
        "flood": FakeHazardModule("flood"),
        "heat": FakeHazardModule("heat"),
    })
    seen: List[Any] = []
    engine.analyze(
        lat=1, lon=2,
        on_hazard=lambda r, done, total: seen.append((r.hazard, done, total)),
    )
    assert [(h, d, t) for h, d, t in seen] == [("flood", 1, 2), ("heat", 2, 2)]


# ---------------------------------------------------------------------------
# Web wiring — POST /api/tx/run -> poll -> result
# ---------------------------------------------------------------------------

@pytest.fixture()
def client():
    from src.dashboard.api import create_app

    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture()
def sync_runner(monkeypatch):
    """Replace the module runner with a synchronous one over a fake engine."""
    from src.dashboard import tx_api

    runner = _sync_runner(make_engine({"flood": FakeHazardModule("flood")}))
    monkeypatch.setattr(tx_api, "_JOB_RUNNER", runner)
    return runner


def test_tx_run_submit_poll_result(sync_runner, client):
    resp = client.post("/api/tx/run", json={
        "lat": 40.0, "lon": -8.0, "hazards": ["flood"], "depth": "deep",
        "name": "Peneda",
    })
    assert resp.status_code == 202
    body = resp.get_json()
    assert body["job_id"].startswith("TXJ-")
    assert body["status"] == "succeeded"  # synchronous test runner
    assert body["poll"] == f"/api/tx/jobs/{body['job_id']}"
    assert body["result_url"] == f"/api/tx/jobs/{body['job_id']}/result"
    assert "result" not in body  # status payload never carries the result body

    poll = client.get(body["poll"])
    assert poll.status_code == 200
    assert poll.get_json()["progress"] == {"completed": 1, "total": 1}

    result = client.get(body["result_url"])
    assert result.status_code == 200
    envelope = result.get_json()
    assert envelope["analysis_id"].startswith("TX-")
    assert envelope["location"] == {"lat": 40.0, "lon": -8.0, "name": "Peneda"}
    assert envelope["results"][0]["hazard"] == "flood"
    assert envelope["depth"] == "deep"


def test_tx_run_idempotent_resubmission(sync_runner, client):
    payload = {"lat": 40.0, "lon": -8.0, "hazards": ["flood"]}
    first = client.post("/api/tx/run", json=payload)
    second = client.post("/api/tx/run", json=payload)
    assert first.status_code == 202
    assert second.status_code == 200  # same deterministic job, not re-run
    assert first.get_json()["job_id"] == second.get_json()["job_id"]


def test_tx_run_hazards_comma_string(sync_runner, client):
    resp = client.post("/api/tx/run", json={
        "lat": 40.0, "lon": -8.0, "hazards": "flood, ghost",
    })
    assert resp.status_code == 202
    job = sync_runner.get(resp.get_json()["job_id"])
    assert job.request["hazards"] == ["flood", "ghost"]


def test_tx_run_validation(sync_runner, client):
    assert client.post("/api/tx/run", data="not json",
                       content_type="text/plain").status_code == 400
    assert client.post("/api/tx/run", json={}).status_code == 400
    assert client.post("/api/tx/run", json={"lat": "x", "lon": 0}).status_code == 400
    assert client.post("/api/tx/run", json={"lat": 95, "lon": 0}).status_code == 400
    assert client.post("/api/tx/run", json={"lat": 0, "lon": -181}).status_code == 400
    assert client.post("/api/tx/run", json={"lat": 0, "lon": 0,
                                            "depth": "ultra"}).status_code == 400
    assert client.post("/api/tx/run", json={"lat": 0, "lon": 0,
                                            "hazards": 42}).status_code == 400


def test_tx_job_unknown_is_404(sync_runner, client):
    assert client.get("/api/tx/jobs/TXJ-19990101-deadbeef").status_code == 404
    assert client.get("/api/tx/jobs/TXJ-19990101-deadbeef/result").status_code == 404


def test_tx_job_result_not_ready_is_409(sync_runner, client):
    job = TxJob(job_id="TXJ-20260901-queued01", request={"lat": 0, "lon": 0})
    sync_runner.store.put_if_absent(job)
    resp = client.get(f"/api/tx/jobs/{job.job_id}/result")
    assert resp.status_code == 409
    body = resp.get_json()
    assert body["status"] == "queued"
    assert "not finished" in body["error"]


def test_tx_job_result_failed_is_honest_409(sync_runner, client):
    job = TxJob(job_id="TXJ-20260901-failed01", request={"lat": 0, "lon": 0},
                status="failed", error="upstream exploded")
    sync_runner.store.put_if_absent(job)
    resp = client.get(f"/api/tx/jobs/{job.job_id}/result")
    assert resp.status_code == 409
    body = resp.get_json()
    assert body["status"] == "failed"
    assert "upstream exploded" in body["error"]


def test_tx_run_failed_job_via_web(sync_runner, monkeypatch, client):
    from src.dashboard import tx_api

    class BoomEngine:
        def analyze(self, **kw: Any) -> Any:
            raise RuntimeError("upstream exploded")

    runner = TxJobRunner(
        store=TxJobStore(), engine_factory=lambda: BoomEngine(), synchronous=True
    )
    monkeypatch.setattr(tx_api, "_JOB_RUNNER", runner)
    resp = client.post("/api/tx/run", json={"lat": 1, "lon": 2})
    assert resp.status_code == 202
    body = resp.get_json()
    assert body["status"] == "failed"
    poll = client.get(body["poll"]).get_json()
    assert poll["status"] == "failed"
    assert "upstream exploded" in poll["error"]
