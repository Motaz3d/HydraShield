"""
Watch registration and alerting (Phase 5).

A "watch" subscribes an email address to a location plus a risk threshold.
A periodic checker (`scripts/check_watches.py`, run by cron inside the
container or externally) re-analyses watched locations and records an alert
when the threshold is crossed.

Design constraints:
    - SQLite only (same file as the cache DB); no new infrastructure.
    - Email is sent via SMTP only when the SMTP_* environment variables are
      configured; otherwise alerts are recorded in the database and logged.
      No credentials are ever invented.
    - No user accounts: a watch is managed via an unguessable token id.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import uuid
from datetime import datetime
from typing import Dict, List, Optional

from .cache import default_cache
from . import mailer

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class WatchStore:
    """SQLite-backed store for watches and fired alerts."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path = db_path or default_cache().db_path
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path, timeout=10.0)

    def _init_db(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS watches (
                    id TEXT PRIMARY KEY,
                    location TEXT NOT NULL,
                    lat REAL NOT NULL,
                    lon REAL NOT NULL,
                    email TEXT NOT NULL,
                    threshold_risk REAL NOT NULL,
                    created_at TEXT NOT NULL,
                    last_checked TEXT,
                    last_risk REAL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    watch_id TEXT NOT NULL,
                    fired_at TEXT NOT NULL,
                    risk REAL NOT NULL,
                    risk_class TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
                """
            )

    def add_watch(
        self, location: str, lat: float, lon: float, email: str, threshold_risk: float
    ) -> Dict:
        """Register a watch. Returns the watch descriptor including its id."""
        if not _EMAIL_RE.match(email or ""):
            return {"error": "Invalid email address"}
        if not (0.0 < threshold_risk <= 100.0):
            return {"error": "Threshold must be in (0, 100]"}
        watch_id = uuid.uuid4().hex
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO watches (id, location, lat, lon, email, threshold_risk, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    watch_id,
                    location[:200],
                    float(lat),
                    float(lon),
                    email[:200],
                    float(threshold_risk),
                    datetime.utcnow().isoformat() + "Z",
                ),
            )
        return {
            "id": watch_id,
            "location": location,
            "threshold_risk": float(threshold_risk),
            "created_at": datetime.utcnow().isoformat() + "Z",
        }

    def remove_watch(self, watch_id: str) -> bool:
        """Remove a watch by id. Returns True when something was deleted."""
        with self._lock, self._connect() as conn:
            cur = conn.execute("DELETE FROM watches WHERE id = ?", (watch_id,))
            return cur.rowcount > 0

    def list_watches(self) -> List[Dict]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT id, location, lat, lon, email, threshold_risk, created_at,"
                " last_checked, last_risk FROM watches"
            ).fetchall()
        return [
            {
                "id": r[0],
                "location": r[1],
                "lat": r[2],
                "lon": r[3],
                "email": r[4],
                "threshold_risk": r[5],
                "created_at": r[6],
                "last_checked": r[7],
                "last_risk": r[8],
            }
            for r in rows
        ]

    def update_check(self, watch_id: str, risk: Optional[float]) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE watches SET last_checked = ?, last_risk = ? WHERE id = ?",
                (datetime.utcnow().isoformat() + "Z", risk, watch_id),
            )

    def record_alert(self, watch_id: str, risk: float, risk_class: str, channel: str, payload: Dict) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO alerts (watch_id, fired_at, risk, risk_class, channel, payload)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    watch_id,
                    datetime.utcnow().isoformat() + "Z",
                    float(risk),
                    risk_class,
                    channel,
                    json.dumps(payload, default=str)[:4000],
                ),
            )


def send_email_alert(to_addr: str, subject: str, body: str) -> bool:
    """
    Send an alert email through the central mailer (``src/dashboard/mailer.py``).

    Alert content semantics are unchanged: ``subject``/``body`` are delivered
    verbatim (wrapped in the Talaix ``alert`` template shell). When SMTP
    is configured the message is sent via STARTTLS SMTP and True is returned.
    When SMTP is not configured the mailer's dev backend records the message
    as an outbox ``.eml`` file (never sent) and False is returned, so the
    caller keeps recording the alert in the DB (``db_only`` channel) exactly
    as before — no credentials are ever assumed.

    Requires env: SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD (or legacy
    SMTP_PASS), SMTP_FROM.
    """
    result = mailer.send_mail(
        to_addr,
        "alert",
        {"subject": subject, "message": body},
        subject_override=subject,
    )
    return result["backend"] == "smtp"
