"""Tests for the progressive analysis jobs and the three report types."""

import io
import os
import time

import pytest

os.environ["HYDRASHIELD_CACHE_DB"] = "/tmp/hydrashield_test_jobs_cache.sqlite3"
if os.path.exists(os.environ["HYDRASHIELD_CACHE_DB"]):
    os.remove(os.environ["HYDRASHIELD_CACHE_DB"])

from src.dashboard import jobs as jobs_module  # noqa: E402
from src.dashboard import report as report_module  # noqa: E402
from src.dashboard.api import create_app  # noqa: E402
from src.dashboard.cache import default_cache  # noqa: E402
from src.dashboard.real_analysis import HydraShieldRealAnalyser  # noqa: E402


def _fake_result(risk=55.0):
    return {
        "location": {"name": "Jobville", "latitude": 40.0, "longitude": -3.0},
        "generated_at": "2026-08-16T00:00:00Z",
        "analysis": {"risk": {"baseline": risk, "class": "High"}},
        "fire_danger": {"available": True, "fwi": 30.0},
        "provenance": {"fire_danger": {"kind": "derived"}},
    }


def _wait_for(store, job_id, status, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = store.get(job_id)
        if job["status"] == status:
            return job
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} did not reach {status}")


# --------------------------------------------------------------------------
# Job store & lifecycle
# --------------------------------------------------------------------------

def test_job_creation_initial_state(tmp_path):
    store = jobs_module.AnalysisJobStore(str(tmp_path / "jobs.sqlite3"))
    job = store.create("40.0,-3.0")
    assert job["status"] == "running"
    assert len(job["stages"]) == len(HydraShieldRealAnalyser.STAGES)
    assert all(s["status"] == "pending" for s in job["stages"])


def test_stage_transitions_are_recorded(tmp_path):
    store = jobs_module.AnalysisJobStore(str(tmp_path / "jobs.sqlite3"))
    job = store.create("40.0,-3.0")
    store.update_stage(job["id"], "weather", "running", {})
    store.update_stage(job["id"], "weather", "complete", {"temperature_c": 30.0})
    store.update_stage(job["id"], "satellite", "unavailable", {"reason": "clouds"})
    out = store.get(job["id"])
    w = next(s for s in out["stages"] if s["id"] == "weather")
    s = next(s for s in out["stages"] if s["id"] == "satellite")
    assert w["status"] == "complete" and w["detail"]["temperature_c"] == 30.0
    assert s["status"] == "unavailable" and "clouds" in s["detail"]["reason"]
    # others still pending
    assert next(s2 for s2 in out["stages"] if s2["id"] == "risk")["status"] == "pending"


def test_run_job_completes_and_populates_analysis_cache(tmp_path, monkeypatch):
    store = jobs_module.AnalysisJobStore(str(tmp_path / "jobs.sqlite3"))
    monkeypatch.setattr(
        HydraShieldRealAnalyser, "analyse_point",
        lambda self, lat, lon, name=None, on_stage=None: (
            on_stage("location", "complete", {"name": name}),
            on_stage("risk", "complete", {"risk": 55.0}),
            _fake_result(),
        )[-1],
    )
    job = store.create("40.0,-3.0")
    jobs_module._run_job(store, job["id"], 40.0, -3.0, "Jobville")
    out = store.get(job["id"])
    assert out["status"] == "complete"
    assert out["result"]["analysis"]["risk"]["baseline"] == 55.0
    assert next(s for s in out["stages"] if s["id"] == "location")["status"] == "complete"
    # shared analysis cache got the result (same key as /api/analyze)
    key = jobs_module._analysis_cache_key(40.0, -3.0, "Jobville")
    cached = default_cache().get(key)
    assert cached is not None and cached["analysis"]["risk"]["baseline"] == 55.0


def test_run_job_failure_is_honest(tmp_path, monkeypatch):
    store = jobs_module.AnalysisJobStore(str(tmp_path / "jobs.sqlite3"))
    def boom(self, lat, lon, name=None, on_stage=None):
        raise RuntimeError("pipeline exploded")
    monkeypatch.setattr(HydraShieldRealAnalyser, "analyse_point", boom)
    job = store.create("41.0,-4.0")
    jobs_module._run_job(store, job["id"], 41.0, -4.0, "X")
    out = store.get(job["id"])
    assert out["status"] == "failed"
    assert "pipeline exploded" in out["error"]
    assert out["result"] is None  # no fabricated result


def test_concurrent_requests_deduplicate(tmp_path, monkeypatch):
    store = jobs_module.AnalysisJobStore(str(tmp_path / "jobs.sqlite3"))
    started = []

    class _FakeThread:
        def __init__(self, target=None, args=(), daemon=None):
            self._target, self._args = target, args
        def start(self):
            started.append(1)  # never actually runs: job stays "running"

    monkeypatch.setattr(jobs_module.threading, "Thread", _FakeThread)
    monkeypatch.setattr(jobs_module, "AnalysisJobStore", lambda: store)
    first = jobs_module.start_analysis_job(42.0, -5.0, "A", store=store)
    second = jobs_module.start_analysis_job(42.0, -5.0, "A", store=store)
    assert first["id"] == second["id"]
    assert len(started) == 1  # only one worker thread


def test_fresh_cache_shortcircuits_job(tmp_path):
    store = jobs_module.AnalysisJobStore(str(tmp_path / "jobs.sqlite3"))
    result = _fake_result(61.0)
    key = jobs_module._analysis_cache_key(43.0, -6.0, "Cachedtown")
    default_cache().set(key, result, 900)
    job = jobs_module.start_analysis_job(43.0, -6.0, "Cachedtown", store=store)
    assert job["status"] == "complete"
    assert job["from_cache"] is True
    assert all(s["status"] == "complete" for s in job["stages"])
    assert job["result"]["analysis"]["risk"]["baseline"] == 61.0


def test_public_payload_hides_result_until_complete(tmp_path):
    store = jobs_module.AnalysisJobStore(str(tmp_path / "jobs.sqlite3"))
    job = store.create("40.0,-3.0")
    payload = jobs_module.public_job_payload(job)
    assert "result" not in payload  # never display a score before it exists
    store.finish(job["id"], _fake_result())
    payload = jobs_module.public_job_payload(store.get(job["id"]))
    assert payload["result"]["analysis"]["risk"]["baseline"] == 55.0
    assert payload["generated_at"] == "2026-08-16T00:00:00Z"


# --------------------------------------------------------------------------
# API endpoints
# --------------------------------------------------------------------------

@pytest.fixture()
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_create_job_requires_input(client):
    resp = client.post("/api/analysis-jobs", json={})
    assert resp.status_code == 400


def test_create_and_poll_job(client, monkeypatch, tmp_path):
    monkeypatch.setattr(
        HydraShieldRealAnalyser, "analyse_point",
        lambda self, lat, lon, name=None, on_stage=None: (
            on_stage("location", "complete", {"name": name}),
            _fake_result(48.0),
        )[-1],
    )
    resp = client.post("/api/analysis-jobs", json={"lat": 44.0, "lon": -7.0})
    assert resp.status_code == 202
    body = resp.get_json()
    assert body["status"] in ("running", "complete")
    assert len(body["stages"]) == len(HydraShieldRealAnalyser.STAGES)
    job_id = body["id"]
    # poll until complete
    for _ in range(200):
        resp = client.get(f"/api/analysis-jobs/{job_id}")
        assert resp.status_code == 200
        out = resp.get_json()
        if out["status"] == "complete":
            break
        time.sleep(0.05)
    assert out["status"] == "complete"
    assert out["result"]["analysis"]["risk"]["baseline"] == 48.0
    assert next(s for s in out["stages"] if s["id"] == "location")["status"] == "complete"


def test_poll_unknown_job_is_404(client):
    resp = client.get("/api/analysis-jobs/doesnotexist")
    assert resp.status_code == 404


def test_create_job_geocoding_failure_is_404(client, monkeypatch):
    from src.dashboard import real_data
    monkeypatch.setattr(real_data, "geocode_location",
                        lambda q: {"error": "Location not found: x"})
    resp = client.post("/api/analysis-jobs", json={"location": "NoSuchPlaceXYZ"})
    assert resp.status_code == 404


# --------------------------------------------------------------------------
# Report types (same analysis object, three audiences)
# --------------------------------------------------------------------------

def _payload():
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
    from test_decision_support import _report_payload
    return _report_payload()


def _pdf_text(pdf_bytes):
    pypdf = pytest.importorskip("pypdf")
    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def test_three_report_types_from_same_analysis():
    pytest.importorskip("reportlab")
    payload = _payload()
    simple = report_module.build_report_pdf(payload, report_type="simple")
    decision = report_module.build_report_pdf(payload, report_type="decision")
    scientific = report_module.build_report_pdf(payload, report_type="scientific")
    for pdf in (simple, decision, scientific):
        assert pdf[:5] == b"%PDF-"
    # Same underlying score everywhere (same analysis object).
    for text in (_pdf_text(simple), _pdf_text(decision), _pdf_text(scientific)):
        assert "68.0" in text or "68" in text
        assert "NOT VALIDATED" in text
        assert "not a probability" in text or "probability of fire" in text


def test_simple_report_is_short_and_excludes_appendix():
    pytest.importorskip("reportlab")
    payload = _payload()
    simple_text = _pdf_text(report_module.build_report_pdf(payload, report_type="simple"))
    sci_text = _pdf_text(report_module.build_report_pdf(payload, report_type="scientific"))
    assert "Methodology appendix" not in simple_text
    assert "Methodology appendix" in sci_text
    assert "Van Wagner" in sci_text
    assert "References" in sci_text
    assert "What should you do?" in simple_text
    assert len(report_module.build_report_pdf(payload, report_type="simple")) < \
        len(report_module.build_report_pdf(payload, report_type="scientific"))


def test_report_type_validation():
    pytest.importorskip("reportlab")
    with pytest.raises(ValueError):
        report_module.build_report_pdf(_payload(), report_type="bogus")


def test_report_endpoint_type_param(client, monkeypatch):
    pytest.importorskip("reportlab")
    import src.dashboard.api as api_module
    monkeypatch.setattr(api_module, "_cached_analysis",
                        lambda lat, lon, name: _payload())
    resp = client.get("/api/report?lat=37.6&lon=-6.5&type=simple")
    assert resp.status_code == 200
    assert resp.mimetype == "application/pdf"
    assert resp.data[:5] == b"%PDF-"
    resp = client.get("/api/report?lat=37.6&lon=-6.5&type=bogus")
    assert resp.status_code == 400
