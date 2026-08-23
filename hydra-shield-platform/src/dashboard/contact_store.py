"""
Inbound contact messages (Commercial Center leads) — SQLite store.

The public ``POST /api/v2/contact`` endpoint used to deliver submissions by
email only; nothing was queryable afterwards. This store persists each
submission (the sender explicitly addressed the platform) so the operator
can see inbound prospects in the Commercial Center, alongside the outbound
marketing workspace. Same shared platform DB (``HYDRASHIELD_CACHE_DB``),
additive ``CREATE TABLE IF NOT EXISTS`` — never destructive.

Messages are operator-only data: they are served exclusively through the
admin-gated ``/api/v2/admin/contacts`` endpoints, never on public paths.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime
from typing import Dict, List, Optional

from .cache import default_cache

CONTACT_STATUSES = ("new", "contacted", "qualified", "closed")


def _utcnow() -> str:
    return datetime.utcnow().isoformat() + "Z"


class ContactStore:
    """SQLite-backed store for inbound contact-form messages."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path = db_path or default_cache().db_path
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path, timeout=10.0)

    def _init_db(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS contact_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT,
                    email TEXT NOT NULL,
                    organization TEXT,
                    interest TEXT,
                    message TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'new',
                    created_at TEXT NOT NULL
                );
                """
            )

    def add_message(
        self,
        email: str,
        message: str,
        name: Optional[str] = None,
        organization: Optional[str] = None,
        interest: Optional[str] = None,
    ) -> int:
        """Persist an inbound contact message; returns its id."""
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO contact_messages"
                " (name, email, organization, interest, message, status, created_at)"
                " VALUES (?, ?, ?, ?, ?, 'new', ?)",
                ((name or "")[:200], (email or "")[:254],
                 (organization or "")[:200], (interest or "")[:100],
                 (message or "")[:5000], _utcnow()),
            )
            return cur.lastrowid

    def list_messages(self, limit: int = 200) -> List[Dict]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT id, name, email, organization, interest, message,"
                " status, created_at FROM contact_messages"
                " ORDER BY id DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
        return [
            {"id": r[0], "name": r[1], "email": r[2], "organization": r[3],
             "interest": r[4], "message": r[5], "status": r[6],
             "created_at": r[7]}
            for r in rows
        ]

    def set_status(self, message_id: int, status: str) -> bool:
        """Update the pipeline status of a message (new → contacted →
        qualified → closed). Returns False for unknown ids or statuses."""
        if status not in CONTACT_STATUSES:
            return False
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "UPDATE contact_messages SET status = ? WHERE id = ?",
                (status, int(message_id)),
            )
            return cur.rowcount > 0
