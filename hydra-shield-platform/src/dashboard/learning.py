"""
Learning from history — prediction-vs-observation record store.

Every comparison of a Talaix prediction/indicator against a real
observation is recorded here with full context:

    model version, prediction time, observation time, predicted condition,
    observed outcome, error, lesson, confidence, data sources

Rules:
    - Records are evidence, not promotions: a model is NEVER automatically
      promoted, calibrated or re-weighted from records in this store — and
      never from a single successful event.
    - Observations must be real (NASA FIRMS detections, satellite aerosol
      products, official records). A comparison without a real observation
      is not recorded.
    - The store shares the platform SQLite cache/watch database (same
      operational footprint as the action-plan audit trail).
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from datetime import datetime
from typing import Dict, List, Optional

from .cache import default_cache

_KINDS = ("ignition", "smoke", "risk", "fire_danger")


class LearningStore:
    """SQLite-backed store of prediction-vs-observation comparison records."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        # Same database file as the TTL cache / watch store.
        self.db_path = db_path or default_cache().db_path
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS learning_records (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    model_version TEXT,
                    location TEXT,
                    prediction_time TEXT,
                    observation_time TEXT,
                    predicted TEXT,
                    observed TEXT,
                    error TEXT,
                    lesson TEXT,
                    confidence TEXT,
                    sources TEXT
                )
                """
            )

    def record(
        self,
        kind: str,
        model_version: str,
        location: str,
        prediction_time: Optional[str],
        observation_time: Optional[str],
        predicted: Dict,
        observed: Dict,
        error: Optional[str] = None,
        lesson: Optional[str] = None,
        confidence: Optional[str] = None,
        sources: Optional[List[str]] = None,
    ) -> str:
        """Insert one comparison record; returns its id."""
        if kind not in _KINDS:
            raise ValueError(f"kind must be one of {_KINDS}")
        if not observed:
            raise ValueError("an observed outcome is required — never record without one")
        rec_id = uuid.uuid4().hex[:16]
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO learning_records (id, created_at, kind, model_version,"
                " location, prediction_time, observation_time, predicted, observed,"
                " error, lesson, confidence, sources)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    rec_id,
                    datetime.utcnow().isoformat() + "Z",
                    kind,
                    model_version,
                    location,
                    prediction_time,
                    observation_time,
                    json.dumps(predicted, default=str),
                    json.dumps(observed, default=str),
                    error,
                    lesson,
                    confidence,
                    json.dumps(sources or [], default=str),
                ),
            )
        return rec_id

    def list(self, kind: Optional[str] = None, limit: int = 100) -> List[Dict]:
        """Read records back (newest first), optionally filtered by kind."""
        limit = min(max(int(limit), 1), 500)
        sql = ("SELECT id, created_at, kind, model_version, location,"
               " prediction_time, observation_time, predicted, observed,"
               " error, lesson, confidence, sources FROM learning_records")
        args: tuple = ()
        if kind:
            sql += " WHERE kind = ?"
            args = (kind,)
        sql += " ORDER BY created_at DESC LIMIT ?"
        args = args + (limit,)
        with self._lock, self._connect() as conn:
            rows = conn.execute(sql, args).fetchall()
        cols = ["id", "created_at", "kind", "model_version", "location",
                "prediction_time", "observation_time", "predicted", "observed",
                "error", "lesson", "confidence", "sources"]
        out = []
        for row in rows:
            rec = dict(zip(cols, row))
            for field in ("predicted", "observed", "sources"):
                try:
                    rec[field] = json.loads(rec[field]) if rec[field] else None
                except (ValueError, TypeError):
                    pass
            out.append(rec)
        return out


def record_comparison(**kwargs) -> str:
    """Module-level convenience wrapper around ``LearningStore.record``."""
    return LearningStore().record(**kwargs)
