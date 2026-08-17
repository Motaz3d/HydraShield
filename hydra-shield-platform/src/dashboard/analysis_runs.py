"""
Reproducible analysis runs — one immutable-addressable record per analysis.

Every record captures what was asked (endpoint, hazard, lat/lon, params),
what answered (result hash, uncertainty, evidence), and under which
versions (model registry versions, integrated dataset ids, methodology),
so a past answer can be traced — or challenged — later.

Reproducibility discipline:

- ``analysis_id`` is ``"ar_" + evidence_id`` over the canonical basis
  (endpoint, hazard, lat, lon, params, result_hash, model_versions,
  dataset_versions, methodology, uncertainty, evidence). Volatile request
  timestamps (``executed_at``) are NEVER part of the basis — re-running
  the same analysis under the same versions with the same result yields
  the same id (the row is upserted with a fresh ``executed_at``).
- ``result_hash`` is the SHA-256 content hash of the full result payload,
  so the id stays stable under harmless re-serialisation only when the
  content is truly identical.

Stored in the shared platform SQLite DB (``HYDRASHIELD_CACHE_DB``), table
``analysis_runs`` — additive only, ``CREATE TABLE IF NOT EXISTS``.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Dict, List, Optional

from ..climate.evidence import content_hash, evidence_id
from .cache import default_cache

_LOCK = threading.Lock()


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _connect(db_path: str) -> sqlite3.Connection:
    return sqlite3.connect(db_path, timeout=10.0)


def _db_path(db_path: Optional[str]) -> str:
    return db_path or default_cache().db_path


def _init_db(db_path: str) -> None:
    with _LOCK, _connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS analysis_runs (
                analysis_id TEXT PRIMARY KEY,
                endpoint TEXT NOT NULL,
                hazard TEXT,
                lat REAL,
                lon REAL,
                params_json TEXT,
                dataset_versions_json TEXT,
                model_versions_json TEXT,
                methodology TEXT,
                executed_at TEXT NOT NULL,
                result_hash TEXT NOT NULL,
                uncertainty_json TEXT,
                evidence_json TEXT
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_analysis_runs_hazard "
            "ON analysis_runs (hazard, executed_at)"
        )


def _canonical_basis(endpoint: str, hazard: Optional[str],
                     lat: Optional[float], lon: Optional[float],
                     params: Optional[dict], result_hash: str,
                     model_versions: Optional[dict],
                     dataset_versions: Optional[dict],
                     methodology: Optional[str],
                     uncertainty: Optional[dict],
                     evidence: Optional[list]) -> dict:
    """The canonical, timestamp-free basis for the analysis id.

    Declared and stable: changing this mapping changes every future id, so
    it must only evolve deliberately (never add volatile fields).
    """
    return {
        "endpoint": endpoint,
        "hazard": hazard,
        "lat": lat,
        "lon": lon,
        "params": params or {},
        "result_hash": result_hash,
        "model_versions": model_versions or {},
        "dataset_versions": dataset_versions or {},
        "methodology": methodology,
        "uncertainty": uncertainty,
        "evidence": evidence,
    }


def record_run(endpoint: str, hazard: Optional[str],
               lat: Optional[float], lon: Optional[float],
               params: Optional[dict], result,
               model_versions: Optional[dict] = None,
               dataset_versions: Optional[dict] = None,
               methodology: Optional[str] = None,
               uncertainty: Optional[dict] = None,
               evidence: Optional[list] = None,
               db_path: Optional[str] = None) -> str:
    """Record one analysis run; returns its content-derived analysis_id.

    ``result`` is the full JSON-serialisable result payload. Re-recording
    the identical run (same canonical basis) upserts the row with a fresh
    ``executed_at`` — the id is a fingerprint of the analysis, not of the
    moment it ran.
    """
    path = _db_path(db_path)
    _init_db(path)

    result_hash = content_hash(result)
    basis = _canonical_basis(endpoint, hazard, lat, lon, params, result_hash,
                             model_versions, dataset_versions, methodology,
                             uncertainty, evidence)
    analysis_id = "ar_" + evidence_id(basis)

    with _LOCK, _connect(path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO analysis_runs (analysis_id, endpoint,"
            " hazard, lat, lon, params_json, dataset_versions_json,"
            " model_versions_json, methodology, executed_at, result_hash,"
            " uncertainty_json, evidence_json)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (analysis_id, endpoint, hazard, lat, lon,
             json.dumps(params or {}, sort_keys=True, default=str),
             json.dumps(dataset_versions or {}, sort_keys=True, default=str),
             json.dumps(model_versions or {}, sort_keys=True, default=str),
             methodology, _utcnow_iso(), result_hash,
             json.dumps(uncertainty, sort_keys=True, default=str)
             if uncertainty is not None else None,
             json.dumps(evidence, sort_keys=True, default=str)
             if evidence is not None else None),
        )
    return analysis_id


def _row_to_dict(row) -> dict:
    def _load(text):
        return json.loads(text) if text is not None else None

    return {
        "analysis_id": row[0],
        "endpoint": row[1],
        "hazard": row[2],
        "lat": row[3],
        "lon": row[4],
        "params": _load(row[5]),
        "dataset_versions": _load(row[6]),
        "model_versions": _load(row[7]),
        "methodology": row[8],
        "executed_at": row[9],
        "result_hash": row[10],
        "uncertainty": _load(row[11]),
        "evidence": _load(row[12]),
    }


def get_run(analysis_id: str, db_path: Optional[str] = None) -> Optional[Dict]:
    """One recorded run by id, or None (honest miss)."""
    path = _db_path(db_path)
    _init_db(path)
    with _LOCK, _connect(path) as conn:
        row = conn.execute(
            "SELECT analysis_id, endpoint, hazard, lat, lon, params_json,"
            " dataset_versions_json, model_versions_json, methodology,"
            " executed_at, result_hash, uncertainty_json, evidence_json"
            " FROM analysis_runs WHERE analysis_id = ?",
            (analysis_id,),
        ).fetchone()
    return _row_to_dict(row) if row else None


def list_runs(limit: int = 50, hazard: Optional[str] = None,
              db_path: Optional[str] = None) -> List[Dict]:
    """Most recent recorded runs (newest first), optionally per hazard."""
    path = _db_path(db_path)
    _init_db(path)
    limit = max(1, min(int(limit), 200))
    sql = (
        "SELECT analysis_id, endpoint, hazard, lat, lon, params_json,"
        " dataset_versions_json, model_versions_json, methodology,"
        " executed_at, result_hash, uncertainty_json, evidence_json"
        " FROM analysis_runs"
    )
    params: list = []
    if hazard:
        sql += " WHERE hazard = ?"
        params.append(hazard)
    sql += " ORDER BY executed_at DESC, analysis_id LIMIT ?"
    params.append(limit)
    with _LOCK, _connect(path) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_row_to_dict(r) for r in rows]
