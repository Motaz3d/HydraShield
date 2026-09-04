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
                     "contacted", "responded", "replied", "opportunity")
LEAD_STATUSES = ("open", "won", "lost")
LEAD_PRIORITIES = ("high", "medium", "low")
INTERACTION_TYPES = ("email", "call", "meeting", "demo", "note", "linkedin",
                     "followup", "proposal", "subscription", "trial", "renewal",
                     "reply", "unsubscribe", "registered", "bounce")
SCHEDULED_STATUSES = ("scheduled", "sent", "failed", "cancelled", "skipped_unsubscribed")
WAVE_STATUSES = ("pending", "sent", "failed", "cancelled", "skipped_unsubscribed",
                 "skipped_undeliverable")

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
                    auto_send INTEGER DEFAULT 0,
                    unsubscribed INTEGER DEFAULT 0,
                    unsub_reason TEXT,
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
                CREATE TABLE IF NOT EXISTS lead_contacts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    lead_slug TEXT NOT NULL,
                    email TEXT NOT NULL,
                    name TEXT,
                    position TEXT,
                    department TEXT,
                    confidence INTEGER,
                    source TEXT NOT NULL DEFAULT 'hunter',
                    verification TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE(lead_slug, email)
                );
                CREATE TABLE IF NOT EXISTS campaign_waves (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    campaign TEXT NOT NULL,
                    lead_slug TEXT NOT NULL,
                    wave INTEGER NOT NULL,
                    template TEXT NOT NULL,
                    context_json TEXT NOT NULL,
                    send_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    error TEXT,
                    created_at TEXT NOT NULL,
                    sent_at TEXT,
                    UNIQUE(campaign, lead_slug, wave)
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
            if "auto_send" not in cols:
                conn.execute(
                    "ALTER TABLE lead_state ADD COLUMN auto_send INTEGER DEFAULT 0")
            if "unsubscribed" not in cols:
                conn.execute(
                    "ALTER TABLE lead_state ADD COLUMN unsubscribed INTEGER DEFAULT 0")
            if "unsub_reason" not in cols:
                conn.execute(
                    "ALTER TABLE lead_state ADD COLUMN unsub_reason TEXT")
            contact_cols = {r[1] for r in conn.execute(
                "PRAGMA table_info(lead_contacts)").fetchall()}
            if "verification" not in contact_cols:
                conn.execute(
                    "ALTER TABLE lead_contacts ADD COLUMN verification TEXT")
            sched_cols = {r[1] for r in conn.execute(
                "PRAGMA table_info(scheduled_outreach)").fetchall()}
            if "attempts" not in sched_cols:
                conn.execute(
                    "ALTER TABLE scheduled_outreach"
                    " ADD COLUMN attempts INTEGER DEFAULT 0")
            # Campaign waves (Phase 18).
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
            if "campaign_waves" not in tables:
                conn.executescript(
                    """
                    CREATE TABLE campaign_waves (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        campaign TEXT NOT NULL,
                        lead_slug TEXT NOT NULL,
                        wave INTEGER NOT NULL,
                        template TEXT NOT NULL,
                        context_json TEXT NOT NULL,
                        send_at TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'pending',
                        error TEXT,
                        created_at TEXT NOT NULL,
                        sent_at TEXT,
                        UNIQUE(campaign, lead_slug, wave)
                    );
                    CREATE INDEX idx_campaign_waves_status_send_at
                        ON campaign_waves(status, send_at);
                    CREATE INDEX idx_campaign_waves_lead
                        ON campaign_waves(lead_slug, status);
                    """
                )

    _STATE_COLS = ("lead_slug, outreach_status, status, priority, next_action,"
                   " next_followup, COALESCE(excluded, 0), exclude_reason,"
                   " COALESCE(auto_send, 0), COALESCE(unsubscribed, 0),"
                   " unsub_reason, updated_at")

    @staticmethod
    def _state_row(row) -> Dict:
        return {"lead_slug": row[0], "outreach_status": row[1], "status": row[2],
                "priority": row[3], "next_action": row[4],
                "next_followup": row[5], "excluded": bool(row[6]),
                "exclude_reason": row[7], "auto_send": bool(row[8]),
                "unsubscribed": bool(row[9]), "unsub_reason": row[10],
                "updated_at": row[11]}

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

    def set_auto_send(self, lead_slug: str, enabled: bool) -> bool:
        """Enable or disable auto-send for a lead."""
        if not self.valid_slug(lead_slug):
            return False
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO lead_state (lead_slug, updated_at) VALUES (?, ?)"
                " ON CONFLICT(lead_slug) DO NOTHING",
                (lead_slug, _utcnow()),
            )
            conn.execute(
                "UPDATE lead_state SET auto_send = ?, updated_at = ?"
                " WHERE lead_slug = ?",
                (1 if enabled else 0, _utcnow(), lead_slug),
            )
        return True

    def unsubscribe(self, lead_slug: str, reason: Optional[str] = None) -> bool:
        """Mark a lead as unsubscribed and record an optional reason."""
        if not self.valid_slug(lead_slug):
            return False
        reason = (reason or "").strip()[:200] or None
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO lead_state (lead_slug, updated_at) VALUES (?, ?)"
                " ON CONFLICT(lead_slug) DO NOTHING",
                (lead_slug, _utcnow()),
            )
            conn.execute(
                "UPDATE lead_state SET unsubscribed = 1, unsub_reason = ?,"
                " updated_at = ? WHERE lead_slug = ?",
                (reason, _utcnow(), lead_slug),
            )
        return True

    def is_unsubscribed(self, lead_slug: str) -> bool:
        """Return True if the lead has opted out of outreach."""
        if not self.valid_slug(lead_slug):
            return False
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(unsubscribed, 0) FROM lead_state"
                " WHERE lead_slug = ?",
                (lead_slug,),
            ).fetchone()
        return bool(row[0]) if row else False

    def sent_today_count(self) -> int:
        """Number of emails sent today via immediate, scheduled or campaign sends."""
        today = _utcnow()[:10]
        with self._lock, self._connect() as conn:
            immediate = conn.execute(
                "SELECT COUNT(*) FROM lead_interactions"
                " WHERE type = 'email' AND date >= ?",
                (today,),
            ).fetchone()[0] or 0
            scheduled = conn.execute(
                "SELECT COUNT(*) FROM scheduled_outreach"
                " WHERE status = 'sent' AND sent_at >= ?",
                (today,),
            ).fetchone()[0] or 0
            waves = conn.execute(
                "SELECT COUNT(*) FROM campaign_waves"
                " WHERE status = 'sent' AND sent_at >= ?",
                (today,),
            ).fetchone()[0] or 0
        return int(immediate) + int(scheduled) + int(waves)

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
            "attempts": row[11] or 0,
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
                " context_json, send_at, status, error, created_at, sent_at,"
                " COALESCE(attempts, 0)"
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
                " context_json, send_at, status, error, created_at, sent_at,"
                " COALESCE(attempts, 0)"
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
        """Mark a scheduled row as sent, failed or skipped. Returns the row or None."""
        if status not in ("sent", "failed", "skipped_unsubscribed",
                          "skipped_undeliverable"):
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

    def cancel_scheduled_for_lead(self, lead_slug: str) -> int:
        """Cancel all scheduled outreach rows for a lead. Returns count changed."""
        if not self.valid_slug(lead_slug):
            return 0
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "UPDATE scheduled_outreach SET status = ?"
                " WHERE lead_slug = ? AND status = ?",
                ("cancelled", lead_slug, "scheduled"),
            )
            return cur.rowcount

    def reschedule_scheduled(
        self,
        scheduled_id: int,
        send_at: str,
        error: Optional[str] = None,
    ) -> Optional[Dict]:
        """Push a still-scheduled row to a later send_at after a transient
        failure, incrementing its attempts counter. Returns the row, or None
        when the row is unknown or no longer scheduled."""
        if not _SEND_AT_RE.match(send_at or ""):
            return None
        row = self.get_scheduled(scheduled_id)
        if row is None or row.get("status") != "scheduled":
            return None
        error = (error or "")[:500]
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE scheduled_outreach SET send_at = ?, error = ?,"
                " attempts = COALESCE(attempts, 0) + 1 WHERE id = ?",
                (send_at, error, scheduled_id),
            )
        return self.get_scheduled(scheduled_id)

    # ------------------------------------------------------------------
    # Campaign waves (periodic outreach)
    # ------------------------------------------------------------------

    @staticmethod
    def _wave_row(row) -> Dict:
        return {
            "id": row[0],
            "campaign": row[1],
            "lead_slug": row[2],
            "wave": row[3],
            "template": row[4],
            "context": json.loads(row[5] or "{}"),
            "send_at": row[6],
            "status": row[7],
            "error": row[8],
            "created_at": row[9],
            "sent_at": row[10],
        }

    def enqueue_wave(
        self,
        campaign: str,
        lead_slug: str,
        wave: int,
        template: str,
        context: Dict,
        send_at: str,
    ) -> Optional[Dict]:
        """Queue a campaign wave row. Returns the row or None on invalid input."""
        if not self.valid_slug(lead_slug):
            return None
        campaign = str(campaign or "").strip()[:80]
        if not campaign:
            return None
        if not isinstance(wave, int) or wave < 1:
            return None
        if not template or not isinstance(template, str) or len(template) > 60:
            return None
        if not isinstance(context, dict):
            return None
        if not send_at or not _SEND_AT_RE.match(send_at):
            return None
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO campaign_waves"
                " (campaign, lead_slug, wave, template, context_json, send_at, status, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (campaign, lead_slug, wave, template,
                 json.dumps(context), send_at, "pending", _utcnow()),
            )
            if cur.lastrowid is None:
                # Already enqueued for this campaign/lead/wave.
                return None
            iid = cur.lastrowid
        return self.get_wave(iid)

    def get_wave(self, wave_id: int) -> Optional[Dict]:
        if not isinstance(wave_id, int):
            return None
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT id, campaign, lead_slug, wave, template, context_json,"
                " send_at, status, error, created_at, sent_at"
                " FROM campaign_waves WHERE id = ?",
                (wave_id,),
            ).fetchone()
        return self._wave_row(row) if row else None

    def pending_waves(
        self,
        due_before: Optional[str] = None,
        campaign: Optional[str] = None,
    ) -> List[Dict]:
        clauses: List[str] = []
        params: List = []
        if campaign is not None:
            clauses.append("campaign = ?")
            params.append(campaign)
        if due_before is not None:
            clauses.append("status = ? AND send_at <= ?")
            params.extend(["pending", due_before])
        else:
            clauses.append("status = ?")
            params.append("pending")
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT id, campaign, lead_slug, wave, template, context_json,"
                " send_at, status, error, created_at, sent_at"
                f" FROM campaign_waves{where} ORDER BY send_at ASC, id ASC",
                params,
            ).fetchall()
        return [self._wave_row(r) for r in rows]

    def mark_wave(
        self,
        wave_id: int,
        status: str,
        error: Optional[str] = None,
    ) -> Optional[Dict]:
        if status not in WAVE_STATUSES:
            return None
        row = self.get_wave(wave_id)
        if row is None:
            return None
        sent_at = _utcnow() if status == "sent" else row.get("sent_at")
        error = (error or "")[:500]
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE campaign_waves SET status = ?, error = ?, sent_at = ?"
                " WHERE id = ?",
                (status, error, sent_at, wave_id),
            )
        return self.get_wave(wave_id)

    def cancel_waves_for_lead(self, lead_slug: str, campaign: Optional[str] = None) -> int:
        """Cancel pending campaign waves for a lead. Returns count changed."""
        if not self.valid_slug(lead_slug):
            return 0
        with self._lock, self._connect() as conn:
            if campaign:
                cur = conn.execute(
                    "UPDATE campaign_waves SET status = ?"
                    " WHERE lead_slug = ? AND campaign = ? AND status = ?",
                    ("cancelled", lead_slug, campaign, "pending"),
                )
            else:
                cur = conn.execute(
                    "UPDATE campaign_waves SET status = ?"
                    " WHERE lead_slug = ? AND status = ?",
                    ("cancelled", lead_slug, "pending"),
                )
            return cur.rowcount

    def campaign_stats(self, campaign: Optional[str] = None) -> List[Dict]:
        """Per-campaign statistics with per-wave breakdown."""
        with self._lock, self._connect() as conn:
            where = " WHERE campaign = ?" if campaign else ""
            params = (campaign,) if campaign else ()
            rows = conn.execute(
                "SELECT campaign, wave, status, COUNT(*)"
                f" FROM campaign_waves{where}"
                " GROUP BY campaign, wave, status",
                params,
            ).fetchall()
            reply_rows = conn.execute(
                "SELECT i.lead_slug, ls.outreach_status, ls.unsubscribed"
                " FROM lead_interactions i"
                " LEFT JOIN lead_state ls ON ls.lead_slug = i.lead_slug"
                " WHERE i.type IN ('reply', 'unsubscribe')"
            ).fetchall()
            lead_rows = conn.execute(
                "SELECT campaign, lead_slug, status, wave"
                " FROM campaign_waves" + where,
                params,
            ).fetchall()

        # Build campaign map.
        by_campaign: Dict[str, Dict] = {}
        for cam, wave, status, count in rows:
            entry = by_campaign.setdefault(cam, {"campaign": cam, "waves": {}})
            wave_entry = entry["waves"].setdefault(wave, {"wave": wave})
            wave_entry[status] = count

        # Attach lead lists and reply/unsubscribe flags.
        lead_map: Dict[str, Dict[str, Dict]] = {}
        for cam, lead_slug, status, wave in lead_rows:
            lead_map.setdefault(cam, {}).setdefault(lead_slug, {"waves": []})
            lead_map[cam][lead_slug]["waves"].append({"wave": wave, "status": status})

        reply_map: Dict[str, set] = {}
        unsub_map: Dict[str, set] = {}
        for lead_slug, out_status, unsubscribed in reply_rows:
            if out_status == "replied":
                for cam, leads in lead_map.items():
                    if lead_slug in leads:
                        reply_map.setdefault(cam, set()).add(lead_slug)
            if unsubscribed:
                for cam, leads in lead_map.items():
                    if lead_slug in leads:
                        unsub_map.setdefault(cam, set()).add(lead_slug)

        for cam, leads in lead_map.items():
            entry = by_campaign.setdefault(cam, {"campaign": cam, "waves": {}})
            entry["leads"] = [
                {
                    "slug": slug,
                    "replied": slug in reply_map.get(cam, set()),
                    "unsubscribed": slug in unsub_map.get(cam, set()),
                    "waves": info["waves"],
                }
                for slug, info in sorted(leads.items())
            ]
            entry["replies"] = len(reply_map.get(cam, set()))
            entry["unsubscribed"] = len(unsub_map.get(cam, set()))

        # Normalize wave dicts into sorted lists.
        for entry in by_campaign.values():
            waves = []
            for wave_num in sorted(entry["waves"]):
                w = entry["waves"][wave_num]
                waves.append({
                    "wave": wave_num,
                    "pending": w.get("pending", 0),
                    "sent": w.get("sent", 0),
                    "failed": w.get("failed", 0),
                    "cancelled": w.get("cancelled", 0),
                    "skipped_unsubscribed": w.get("skipped_unsubscribed", 0),
                })
            entry["waves"] = waves

        return list(by_campaign.values())

    # ------------------------------------------------------------------
    # Lead contacts (discovered via Hunter.io)
    # ------------------------------------------------------------------

    @staticmethod
    def _contact_row(row) -> Dict:
        return {
            "id": row[0],
            "lead_slug": row[1],
            "email": row[2],
            "name": row[3],
            "position": row[4],
            "department": row[5],
            "confidence": row[6],
            "source": row[7],
            "verification": row[8],
            "created_at": row[9],
        }

    def add_contacts(
        self,
        lead_slug: str,
        contacts: List[Dict],
        source: str = "hunter",
    ) -> Optional[int]:
        """Insert discovered contacts for a lead, deduplicating by
        (lead_slug, email). Returns the number of newly added contacts, or
        None on invalid input."""
        if not self.valid_slug(lead_slug):
            return None
        if not isinstance(contacts, list) or not isinstance(source, str):
            return None
        source = source.strip()[:50] or "hunter"

        rows = []
        for c in contacts:
            email = str(c.get("email") or "").strip()
            if not email or not _EMAIL_RE.match(email):
                continue
            name = str(c.get("name") or "").strip()[:200]
            position = str(c.get("position") or "").strip()[:200]
            department = str(c.get("department") or "").strip()[:200]
            confidence = c.get("confidence")
            if confidence is not None:
                try:
                    confidence = int(confidence)
                    if not 0 <= confidence <= 100:
                        confidence = None
                except (TypeError, ValueError):
                    confidence = None
            verification = str(c.get("verification") or "").strip()[:20] or None
            rows.append(
                (lead_slug, email, name or None, position or None,
                 department or None, confidence, source, verification, _utcnow())
            )
        if not rows:
            return 0
        with self._lock, self._connect() as conn:
            changes_before = conn.total_changes
            conn.executemany(
                "INSERT OR IGNORE INTO lead_contacts"
                " (lead_slug, email, name, position, department, confidence,"
                " source, verification, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
            return conn.total_changes - changes_before

    def set_contact_verification(
        self,
        contact_id: int,
        verification: str,
    ) -> Optional[Dict]:
        """Update the verification status of a stored contact."""
        if not isinstance(contact_id, int):
            return None
        verification = str(verification or "").strip()[:20] or None
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT id, lead_slug, email, name, position, department,"
                " confidence, source, verification, created_at"
                " FROM lead_contacts WHERE id = ?",
                (contact_id,),
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                "UPDATE lead_contacts SET verification = ? WHERE id = ?",
                (verification, contact_id),
            )
        return self.get_contact(contact_id)

    def get_contact(self, contact_id: int) -> Optional[Dict]:
        """Fetch a single stored contact by id."""
        if not isinstance(contact_id, int):
            return None
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT id, lead_slug, email, name, position, department,"
                " confidence, source, verification, created_at"
                " FROM lead_contacts WHERE id = ?",
                (contact_id,),
            ).fetchone()
        return self._contact_row(row) if row else None

    def list_contacts(self, lead_slug: Optional[str] = None) -> List[Dict]:
        """Stored contacts for a lead (or all contacts if no slug),
        highest-confidence first."""
        with self._lock, self._connect() as conn:
            if lead_slug:
                rows = conn.execute(
                    "SELECT id, lead_slug, email, name, position, department,"
                    " confidence, source, verification, created_at FROM lead_contacts"
                    " WHERE lead_slug = ?"
                    " ORDER BY (confidence IS NULL), confidence DESC, id",
                    (lead_slug,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, lead_slug, email, name, position, department,"
                    " confidence, source, verification, created_at FROM lead_contacts"
                    " ORDER BY id"
                ).fetchall()
        return [self._contact_row(r) for r in rows]

    def delete_contact(self, contact_id: int) -> Optional[Dict]:
        """Delete a stored contact by id. Returns the deleted row or None."""
        if not isinstance(contact_id, int):
            return None
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT id, lead_slug, email, name, position, department,"
                " confidence, source, verification, created_at"
                " FROM lead_contacts WHERE id = ?",
                (contact_id,),
            ).fetchone()
            if row is None:
                return None
            conn.execute("DELETE FROM lead_contacts WHERE id = ?", (contact_id,))
        return self._contact_row(row)
