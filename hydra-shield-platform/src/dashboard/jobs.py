"""
Progressive analysis jobs.

The full real-data analysis takes 15-90 s on a cold cache. This module
provides the honest, stage-based job architecture behind the progressive
UI — no fake streaming, no fake progress:

    POST /api/analysis-jobs          -> create job (202, job_id)
    GET  /api/analysis-jobs/<id>     -> poll stage states + partial details

Design:
    - One pipeline implementation: the job runs
      ``HydraShieldRealAnalyser.analyse_point(..., on_stage=...)`` — the
      same real analysis that backs /api/analyze, with identical output.
    - Stage states are only ever PENDING -> RUNNING -> COMPLETE or
      UNAVAILABLE, driven by the real pipeline's stage callbacks.
    - A finished job writes its result into the shared analysis cache, so
      /api/analyze and /api/report reuse it (no duplicate analyses).
    - A fresh cached analysis short-circuits the job: all stages complete
      immediately and the job reports ``from_cache: true`` with the real
      generation timestamp ("using a recent analysis").
    - Concurrent requests for the same coordinates attach to the already
      running job (deduplication via the SQLite store).
    - Cancellation is client-side (stop polling): the server job finishes
      and its result is cached — nothing is lost, nothing fabricated.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime
from typing import Dict, List, Optional

from .cache import default_cache, TTL_ANALYSIS
from .real_analysis import HydraShieldRealAnalyser

_JOB_TTL_SECONDS = 6 * 3600.0


class AnalysisJobStore:
    """SQLite store for analysis jobs (same DB file as the cache)."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path = db_path or default_cache().db_path
        self._lock = threading.Lock()
        with self._lock, sqlite3.connect(self.db_path, timeout=10.0) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS analysis_jobs (
                    id TEXT PRIMARY KEY,
                    coord_key TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    status TEXT NOT NULL,
                    from_cache INTEGER NOT NULL DEFAULT 0,
                    stages TEXT NOT NULL,
                    result TEXT,
                    error TEXT
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_analysis_jobs_coord"
                " ON analysis_jobs(coord_key, status)"
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path, timeout=10.0)

    @staticmethod
    def _initial_stages() -> List[Dict]:
        return [
            {"id": sid, "label": label, "source": source,
             "status": "pending", "detail": {}}
            for sid, label, source in HydraShieldRealAnalyser.STAGES
        ]

    def create(self, coord_key: str, from_cache: bool = False) -> Dict:
        now = datetime.utcnow().timestamp()
        job = {
            "id": uuid.uuid4().hex[:16],
            "coord_key": coord_key,
            "created_at": now,
            "updated_at": now,
            "status": "running",
            "from_cache": from_cache,
            "stages": self._initial_stages(),
            "result": None,
            "error": None,
        }
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO analysis_jobs"
                " (id, coord_key, created_at, updated_at, status, from_cache,"
                "  stages, result, error) VALUES (?,?,?,?,?,?,?,?,?)",
                (job["id"], coord_key, now, now, "running",
                 1 if from_cache else 0, json.dumps(job["stages"]), None, None),
            )
        return job

    def _row_to_job(self, row) -> Optional[Dict]:
        if row is None:
            return None
        return {
            "id": row[0], "coord_key": row[1], "created_at": row[2],
            "updated_at": row[3], "status": row[4],
            "from_cache": bool(row[5]), "stages": json.loads(row[6]),
            "result": json.loads(row[7]) if row[7] else None,
            "error": row[8],
        }

    def get(self, job_id: str) -> Optional[Dict]:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT id, coord_key, created_at, updated_at, status,"
                " from_cache, stages, result, error FROM analysis_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
        return self._row_to_job(row)

    def find_running(self, coord_key: str) -> Optional[Dict]:
        """A still-fresh running job for these coordinates, if any."""
        cutoff = datetime.utcnow().timestamp() - _JOB_TTL_SECONDS
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT id, coord_key, created_at, updated_at, status,"
                " from_cache, stages, result, error FROM analysis_jobs"
                " WHERE coord_key = ? AND status = 'running' AND created_at >= ?"
                " ORDER BY created_at DESC LIMIT 1",
                (coord_key, cutoff),
            ).fetchone()
        return self._row_to_job(row)

    def _update(self, job_id: str, **fields) -> None:
        now = datetime.utcnow().timestamp()
        sets, vals = [], []
        for k, v in fields.items():
            sets.append(f"{k} = ?")
            vals.append(json.dumps(v) if isinstance(v, (dict, list)) else v)
        sets.append("updated_at = ?")
        vals.append(now)
        vals.append(job_id)
        with self._lock, self._connect() as conn:
            conn.execute(
                f"UPDATE analysis_jobs SET {', '.join(sets)} WHERE id = ?", vals
            )

    def update_stage(self, job_id: str, stage_id: str, status: str,
                     detail: Dict) -> None:
        job = self.get(job_id)
        if job is None:
            return
        for stage in job["stages"]:
            if stage["id"] == stage_id:
                stage["status"] = status
                if detail:
                    stage["detail"] = detail
                break
        self._update(job_id, stages=job["stages"])

    def finish(self, job_id: str, result: Dict, from_cache: bool = False) -> None:
        self._update(job_id, status="complete", result=result,
                     from_cache=1 if from_cache else 0)

    def fail(self, job_id: str, error: str) -> None:
        self._update(job_id, status="failed", error=error)


# --------------------------------------------------------------------------
# Job lifecycle
# --------------------------------------------------------------------------

def _coord_key(lat: float, lon: float) -> str:
    return f"{round(float(lat), 4)},{round(float(lon), 4)}"


def _analysis_cache_key(lat: float, lon: float, name: str) -> str:
    """Must match the key used by snapshot.cached_analysis / /api/analyze."""
    cache = default_cache()
    return cache.make_key("analysis", round(float(lat), 4), round(float(lon), 4), name)


def _complete_job_from_cache(store: AnalysisJobStore, job: Dict, cached: Dict) -> Dict:
    """Short-circuit: mark every stage complete from the real cached result."""
    for stage in job["stages"]:
        stage["status"] = "complete"
        stage["detail"] = {"cached": True}
    store._update(job["id"], stages=job["stages"])
    store.finish(job["id"], cached, from_cache=True)
    return store.get(job["id"])


def _run_job(store: AnalysisJobStore, job_id: str,
             lat: float, lon: float, name: str) -> None:
    """Worker: run the real staged analysis, persisting every transition."""
    def on_stage(stage_id: str, status: str, detail: Dict) -> None:
        store.update_stage(job_id, stage_id, status, detail)

    try:
        result = HydraShieldRealAnalyser().analyse_point(lat, lon, name=name,
                                                         on_stage=on_stage)
    except Exception as exc:
        store.fail(job_id, f"Analysis failed: {exc}")
        return
    if "error" in result:
        store.fail(job_id, result["error"])
        return
    # Hand the result to the shared analysis cache (same key as /api/analyze).
    try:
        default_cache().set(_analysis_cache_key(lat, lon, name), result, TTL_ANALYSIS)
    except Exception:
        pass
    store.finish(job_id, result)


def start_analysis_job(lat: float, lon: float, name: str,
                       store: Optional[AnalysisJobStore] = None) -> Dict:
    """
    Start (or reuse) a progressive analysis job for a point.

    Order: fresh analysis-cache hit -> instant complete job; already-running
    job for the same coordinates -> attach (deduplication); otherwise a new
    job on a background thread.
    """
    store = store or AnalysisJobStore()
    lat, lon = float(lat), float(lon)
    name = name or f"{lat:.4f}, {lon:.4f}"
    key = _coord_key(lat, lon)

    cache = default_cache()
    cached = cache.get(_analysis_cache_key(lat, lon, name))
    if cached is not None and "error" not in cached:
        job = store.create(key, from_cache=True)
        return _complete_job_from_cache(store, job, cached)

    running = store.find_running(key)
    if running is not None:
        return running

    job = store.create(key)
    thread = threading.Thread(
        target=_run_job, args=(store, job["id"], lat, lon, name), daemon=True
    )
    thread.start()
    return store.get(job["id"])


def get_analysis_job(job_id: str,
                     store: Optional[AnalysisJobStore] = None) -> Optional[Dict]:
    return (store or AnalysisJobStore()).get(job_id)


def public_job_payload(job: Dict) -> Dict:
    """Shape a job for the API: stages first, result only when finished."""
    out = {
        "id": job["id"],
        "status": job["status"],
        "from_cache": job["from_cache"],
        "created_at": datetime.utcfromtimestamp(job["created_at"]).isoformat() + "Z",
        "stages": job["stages"],
        "error": job["error"],
    }
    if job["status"] == "complete" and job["result"] is not None:
        out["result"] = job["result"]
        out["generated_at"] = (job["result"] or {}).get("generated_at")
    return out
