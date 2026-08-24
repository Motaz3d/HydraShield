"""
Marketing operations store — the operator's working state over the
file-based marketing workspace.

The workspace (``marketing/*.json``) is the research memory: it is
SCP-synced from the Git repo on every deploy and bind-mounted read-only
into the api container, so UI edits could never live there safely (a
deploy would silently overwrite them). This store keeps the operator's
*working* state — pipeline status changes, next actions, follow-up dates
and logged interactions — in the shared platform DB (persistent volume),
and ``admin_intel`` overlays it onto the workspace view. Deploy-safe,
per-operator audited, never destructive.

Vocabulary mirrors the workspace schemas (docs/MARKETING_INTELLIGENCE.md):
outreach_status: researched | qualified | draft_prepared | contacted |
                 responded | opportunity
status:          open | won | lost
priority:        high | medium | low
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from datetime import datetime
from typing import Dict, List, Optional

from .cache import default_cache

OUTREACH_STATUSES = ("researched", "qualified", "draft_prepared",
                     "contacted", "responded", "opportunity")
LEAD_STATUSES = ("open", "won", "lost")
LEAD_PRIORITIES = ("high", "medium", "low")
INTERACTION_TYPES = ("email", "call", "meeting", "demo", "note", "linkedin",
                     "followup", "proposal", "subscription", "trial", "renewal")
SCHEDULED_STATUSES = ("scheduled", "sent", "failed", "cancelled")

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,120}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_SEND_AT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}")


def _utcnow() -> str:
    return datetime.utcnow().isoformat() + "Z"


class MarketingStore:
    """SQLite-backed store for the operator's lead-pipeline state."""

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
                CREATE TABLE IF NOT EXISTS lead_state (
                    lead_slug TEXT PRIMARY KEY,
                    outreach_status TEXT,
                    status TEXT,
                    priority TEXT,
                    next_action TEXT,
                    next_followup TEXT,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS lead_interactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    lead_slug TEXT NOT NULL,
                    date TEXT NOT NULL,
                    type TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS scheduled_outreach (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    lead_slug TEXT NOT NULL,
                    to_email TEXT NOT NULL,
                    contact_name TEXT,
                    template TEXT NOT NULL,
                    context_json TEXT NOT NULL,
                    send_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'scheduled',
                    error TEXT,
                    created_at TEXT NOT NULL,
                    sent_at TEXT
                );
                """
            )
            # Additive migrations for existing databases (never destructive).
            cols = {r[1] for r in conn.execute(
                "PRAGMA table_info(lead_state)").fetchall()}
            if "excluded" not in cols:
                conn.execute(
                    "ALTER TABLE lead_state ADD COLUMN excluded INTEGER")
            if "exclude_reason" not in cols:
                conn.execute(
                    "ALTER TABLE lead_state ADD COLUMN exclude_reason TEXT")

    _STATE_COLS = ("lead_slug, outreach_status, status, priority, next_action,"
                   " next_followup, COALESCE(excluded, 0), exclude_reason, updated_at")

    @staticmethod
    def _state_row(row) -> Dict:
        return {"lead_slug": row[0], "outreach_status": row[1], "status": row[2],
                "priority": row[3], "next_action": row[4],
                "next_followup": row[5], "excluded": bool(row[6]),
                "exclude_reason": row[7], "updated_at": row[8]}

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    @staticmethod
    def valid_slug(slug: str) -> bool:
        return bool(slug) and bool(_SLUG_RE.match(slug))

    # ------------------------------------------------------------------
    # Lead pipeline state (sparse overlay: only changed fields stored)
    # ------------------------------------------------------------------

    def update_state(self, lead_slug: str, **fields) -> Optional[Dict]:
        """Upsert pipeline fields for a lead. Returns the merged stored
        state, or None on invalid input."""
        if not self.valid_slug(lead_slug):
            return None
        allowed = {
            "outreach_status": lambda v: v in OUTREACH_STATUSES,
            "status": lambda v: v in LEAD_STATUSES,
            "priority": lambda v: v in LEAD_PRIORITIES,
            "next_action": lambda v: isinstance(v, str) and len(v) <= 300,
            "next_followup": lambda v: v is None or bool(_DATE_RE.match(v or "")),
            # Competitor/irrelevant exclusion: excluded leads stay in the
            # research base but leave every outreach plan and the map.
            "excluded": lambda v: v in (True, False, 0, 1),
            "exclude_reason": lambda v: isinstance(v, str) and len(v) <= 200,
        }
        clean = {}
        for key, value in fields.items():
            if key not in allowed or not allowed[key](value):
                return None
            if key == "excluded":
                clean[key] = 1 if value in (True, 1) else 0
            else:
                clean[key] = (value or None) if isinstance(value, str) else value
        if not clean:
            return None
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO lead_state (lead_slug, updated_at) VALUES (?, ?)"
                " ON CONFLICT(lead_slug) DO NOTHING",
                (lead_slug, _utcnow()),
            )
            sets = ", ".join(f"{k} = ?" for k in clean)
            conn.execute(
                f"UPDATE lead_state SET {sets}, updated_at = ? WHERE lead_slug = ?",
                (*clean.values(), _utcnow(), lead_slug),
            )
        return self.get_state(lead_slug)

    def get_state(self, lead_slug: str) -> Optional[Dict]:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                f"SELECT {self._STATE_COLS} FROM lead_state WHERE lead_slug = ?",
                (lead_slug,),
            ).fetchone()
        return self._state_row(row) if row else None

    def list_states(self) -> List[Dict]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                f"SELECT {self._STATE_COLS} FROM lead_state"
            ).fetchall()
        return [self._state_row(r) for r in rows]

    # ------------------------------------------------------------------
    # Interaction log
    # ------------------------------------------------------------------

    def add_interaction(
        self,
        lead_slug: str,
        summary: str,
        type: str = "note",
        date: Optional[str] = None,
    ) -> Optional[Dict]:
        if not self.valid_slug(lead_slug):
            return None
        summary = (summary or "").strip()[:1000]
        if not summary:
            return None
        if type not in INTERACTION_TYPES:
            return None
        date = (date or "").strip() or _utcnow()[:10]
        if not _DATE_RE.match(date):
            return None
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO lead_interactions (lead_slug, date, type, summary, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (lead_slug, date, type, summary, _utcnow()),
            )
            iid = cur.lastrowid
        return {"id": iid, "lead_slug": lead_slug, "date": date,
                "type": type, "summary": summary}

    def list_interactions(self, lead_slug: Optional[str] = None) -> List[Dict]:
        with self._lock, self._connect() as conn:
            if lead_slug:
                rows = conn.execute(
                    "SELECT id, lead_slug, date, type, summary FROM lead_interactions"
                    " WHERE lead_slug = ? ORDER BY date DESC, id DESC",
                    (lead_slug,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, lead_slug, date, type, summary FROM lead_interactions"
                    " ORDER BY date DESC, id DESC LIMIT 500"
                ).fetchall()
        return [{"id": r[0], "lead_slug": r[1], "date": r[2],
                 "type": r[3], "summary": r[4]} for r in rows]

    # ------------------------------------------------------------------
    # Scheduled outreach
    # ------------------------------------------------------------------

    @staticmethod
    def _scheduled_row(row) -> Dict:
        return {
            "id": row[0],
            "lead_slug": row[1],
            "to_email": row[2],
            "contact_name": row[3],
            "template": row[4],
            "context": json.loads(row[5] or "{}"),
            "send_at": row[6],
            "status": row[7],
            "error": row[8],
            "created_at": row[9],
            "sent_at": row[10],
        }

    def schedule_send(
        self,
        lead_slug: str,
        to_email: str,
        contact_name: Optional[str],
        template: str,
        context: Dict,
        send_at: str,
    ) -> Optional[Dict]:
        """Queue an outreach email for future delivery. Returns the row or
        None on invalid input."""
        if not self.valid_slug(lead_slug):
            return None
        if not to_email or not _EMAIL_RE.match(to_email):
            return None
        if not template or not isinstance(template, str) or len(template) > 60:
            return None
        if contact_name is not None and (
            not isinstance(contact_name, str) or len(contact_name) > 200
        ):
            return None
        if not send_at or not _SEND_AT_RE.match(send_at):
            return None
        if not isinstance(context, dict):
            return None
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO scheduled_outreach"
                " (lead_slug, to_email, contact_name, template, context_json,"
                " send_at, status, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (lead_slug, to_email, contact_name, template,
                 json.dumps(context), send_at, "scheduled", _utcnow()),
            )
            iid = cur.lastrowid
        return self.get_scheduled(iid)

    def list_scheduled(
        self,
        lead_slug: Optional[str] = None,
        status: Optional[str] = None,
        due_before: Optional[str] = None,
    ) -> List[Dict]:
        """Scheduled outreach rows, ordered by send_at ASC."""
        clauses: List[str] = []
        params: List = []
        if lead_slug is not None:
            clauses.append("lead_slug = ?")
            params.append(lead_slug)
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        if due_before is not None:
            clauses.append("status = ? AND send_at <= ?")
            params.extend(["scheduled", due_before])
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT id, lead_slug, to_email, contact_name, template,"
                " context_json, send_at, status, error, created_at, sent_at"
                f" FROM scheduled_outreach{where} ORDER BY send_at ASC, id ASC",
                params,
            ).fetchall()
        return [self._scheduled_row(r) for r in rows]

    def get_scheduled(self, scheduled_id: int) -> Optional[Dict]:
        if not isinstance(scheduled_id, int):
            return None
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT id, lead_slug, to_email, contact_name, template,"
                " context_json, send_at, status, error, created_at, sent_at"
                " FROM scheduled_outreach WHERE id = ?",
                (scheduled_id,),
            ).fetchone()
        return self._scheduled_row(row) if row else None

    def mark_scheduled(
        self,
        scheduled_id: int,
        status: str,
        error: Optional[str] = None,
    ) -> Optional[Dict]:
        """Mark a scheduled row as sent or failed. Returns the row or None."""
        if status not in ("sent", "failed"):
            return None
        row = self.get_scheduled(scheduled_id)
        if row is None:
            return None
        sent_at = _utcnow() if status == "sent" else row.get("sent_at")
        error = (error or "")[:500]
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE scheduled_outreach SET status = ?, error = ?, sent_at = ?"
                " WHERE id = ?",
                (status, error, sent_at, scheduled_id),
            )
        return self.get_scheduled(scheduled_id)

    def cancel_scheduled(self, scheduled_id: int) -> Optional[Dict]:
        """Cancel a scheduled row. Only rows still scheduled may be cancelled."""
        row = self.get_scheduled(scheduled_id)
        if row is None or row.get("status") != "scheduled":
            return None
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE scheduled_outreach SET status = ? WHERE id = ?",
                ("cancelled", scheduled_id),
            )
        return self.get_scheduled(scheduled_id)
