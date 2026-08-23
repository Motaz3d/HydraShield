"""
Talaix notification store (Stage 7) — SQLite, shared platform DB.

Stores everything the alerting engine needs in the same shared SQLite
database as the cache / watches / accounts (``HYDRASHIELD_CACHE_DB``). All
tables are created with ``CREATE TABLE IF NOT EXISTS`` — additive only,
never destructive.

Tables:

- ``phone_numbers`` — one verified (or pending) E.164 phone per user.
  Verification is a 6-digit code, stored HMAC-hashed (reusing
  ``accounts.hash_token``) with a 10-minute TTL; the plaintext code is
  never stored.
- ``alert_prefs`` — per-user notification preferences (channels on/off,
  quiet hours, language, daily cap).
- ``alert_rules`` — per-user hazard/location rules with a severity
  threshold (``HIGH`` | ``EXTREME``) and the last observed severity for
  transition detection.
- ``alert_records`` — fired (or suppressed) alert events, one row per
  rule transition; id is content-derived (``al_<hash16>``).
- ``alert_deliveries`` — per-channel delivery outcome for each alert
  record (sent | outbox | held_quiet_hours | suppressed_duplicate |
  failed | disabled).
- ``webhook_subscriptions`` — per-user outbound webhook targets (HTTPS
  URL, HMAC signing secret stored as ``secret_hash``, comma-separated
  event list); capped at ``MAX_WEBHOOKS_PER_USER`` per user. The signing
  secret is returned to the subscriber once at creation (see
  ``webhooks.generate_secret``) and is never logged or audited.

Security norms (same as ``accounts.py``): parameterised SQL everywhere,
per-user isolation in every query, constant-time code comparison, audit
log entries for security-relevant actions — never verification codes,
provider credentials or message secrets.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import threading
import time
from datetime import datetime
from typing import Dict, List, Optional

from .accounts import hash_token
from .cache import default_cache

VERIFY_CODE_TTL_SECONDS = 10 * 60          # 10 minutes
DEFAULT_MAX_PER_DAY = 10
DEFAULT_LANGUAGE = "en"

SEVERITY_THRESHOLDS = ("HIGH", "EXTREME")

MAX_WEBHOOKS_PER_USER = 5
WEBHOOK_EVENTS = ("alert_fired", "significant_change")

_QUIET_HHMM_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _utcnow() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _today() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d")


def _valid_hazards() -> List[str]:
    from ..climate.ontology import HazardType

    return [h.value for h in HazardType]


class NotifyStore:
    """SQLite-backed store for phones, preferences, rules and alert history."""

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
                CREATE TABLE IF NOT EXISTS phone_numbers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    e164 TEXT UNIQUE NOT NULL,
                    verified_at TEXT,
                    created_at TEXT NOT NULL,
                    verify_code_hash TEXT,
                    verify_expires TEXT
                );
                CREATE TABLE IF NOT EXISTS alert_prefs (
                    user_id INTEGER PRIMARY KEY,
                    sms_enabled INTEGER NOT NULL DEFAULT 0,
                    email_enabled INTEGER NOT NULL DEFAULT 1,
                    quiet_start TEXT,
                    quiet_end TEXT,
                    language TEXT NOT NULL DEFAULT 'en',
                    max_per_day INTEGER NOT NULL DEFAULT 10
                );
                CREATE TABLE IF NOT EXISTS alert_rules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    hazard TEXT NOT NULL,
                    lat REAL NOT NULL,
                    lon REAL NOT NULL,
                    name TEXT,
                    severity_threshold TEXT NOT NULL DEFAULT 'HIGH',
                    active INTEGER NOT NULL DEFAULT 1,
                    last_severity TEXT,
                    last_checked TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS alert_records (
                    id TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    rule_id INTEGER NOT NULL,
                    hazard TEXT NOT NULL,
                    lat REAL,
                    lon REAL,
                    severity TEXT NOT NULL,
                    trigger TEXT NOT NULL,
                    analysis_id TEXT,
                    data_version TEXT,
                    created_at TEXT NOT NULL,
                    suppressed INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS alert_deliveries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    alert_id TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    target TEXT,
                    status TEXT NOT NULL,
                    provider_message_id TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS webhook_subscriptions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    url TEXT NOT NULL,
                    secret_hash TEXT NOT NULL,
                    events TEXT NOT NULL DEFAULT 'alert_fired',
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    actor_user_id INTEGER,
                    action TEXT NOT NULL,
                    target TEXT,
                    meta_json TEXT,
                    created_at TEXT NOT NULL
                );
                """
            )

    # ------------------------------------------------------------------
    # Audit log — security events only, never codes or credentials
    # ------------------------------------------------------------------

    def audit(
        self,
        actor_user_id: Optional[int],
        action: str,
        target: Optional[str] = None,
        meta: Optional[Dict] = None,
    ) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO audit_log (actor_user_id, action, target, meta_json, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (actor_user_id, (action or "")[:80], (target or "")[:200],
                 json.dumps(meta or {}, default=str)[:2000], _utcnow()),
            )

    # ------------------------------------------------------------------
    # Phone numbers (per-user isolation; verification code hashed, TTL 10 min)
    # ------------------------------------------------------------------

    @staticmethod
    def _phone_row(row) -> Dict:
        return {
            "id": row[0], "user_id": row[1], "e164": row[2],
            "verified_at": row[3], "created_at": row[4],
            "verified": bool(row[3]),
        }

    def upsert_phone(self, user_id: int, e164: str) -> Dict:
        """
        Register (or re-register) a phone number for a user: unverified,
        with a fresh 6-digit verification code (only the HMAC hash is
        stored). Returns ``{"phone": …, "code": …}`` — the plaintext code
        is returned solely so the caller can deliver it via SMS; it is
        never stored and must never be included in an API response.
        """
        code = f"{secrets.randbelow(1000000):06d}"
        expires = datetime.utcfromtimestamp(
            time.time() + VERIFY_CODE_TTL_SECONDS).isoformat() + "Z"
        with self._lock, self._connect() as conn:
            existing = conn.execute(
                "SELECT id, user_id FROM phone_numbers WHERE e164 = ?",
                (e164,),
            ).fetchone()
            if existing is not None and existing[1] != user_id:
                return {"error": "This phone number is registered to another account"}
            if existing is not None:
                conn.execute(
                    "UPDATE phone_numbers SET verified_at = NULL, verify_code_hash = ?,"
                    " verify_expires = ? WHERE id = ?",
                    (hash_token(code), expires, existing[0]),
                )
                phone_id = existing[0]
            else:
                cur = conn.execute(
                    "INSERT INTO phone_numbers"
                    " (user_id, e164, verified_at, created_at, verify_code_hash, verify_expires)"
                    " VALUES (?, ?, NULL, ?, ?, ?)",
                    (user_id, e164, _utcnow(), hash_token(code), expires),
                )
                phone_id = cur.lastrowid
        self.audit(user_id, "phone_registered", target="self",
                   meta={"phone_id": phone_id})
        return {"phone": self.get_phone(user_id), "code": code}

    def get_phone(self, user_id: int) -> Optional[Dict]:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT id, user_id, e164, verified_at, created_at"
                " FROM phone_numbers WHERE user_id = ? ORDER BY id DESC LIMIT 1",
                (user_id,),
            ).fetchone()
        return self._phone_row(row) if row else None

    def get_verified_phone(self, user_id: int) -> Optional[Dict]:
        phone = self.get_phone(user_id)
        return phone if phone and phone["verified"] else None

    def verify_phone(self, user_id: int, code: str) -> Dict:
        """
        Verify a 6-digit code for the user's pending phone: hashed,
        constant-time comparison, TTL enforced. On success the number is
        marked verified. Returns ``{"verified": True}`` or
        ``{"error": …}``.
        """
        failure: Optional[str] = None
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT id, verify_code_hash, verify_expires, verified_at"
                " FROM phone_numbers WHERE user_id = ? ORDER BY id DESC LIMIT 1",
                (user_id,),
            ).fetchone()
            if row is None:
                return {"error": "No phone number registered"}
            if row[3] is not None:
                return {"error": "Phone number already verified"}
            if not code or not row[1]:
                return {"error": "Invalid verification code"}
            expires = datetime.fromisoformat(
                row[2].replace("Z", "+00:00")).timestamp()
            if expires < time.time():
                failure = "expired"
            elif not hmac.compare_digest(hash_token(str(code).strip()), row[1]):
                failure = "mismatch"
            else:
                conn.execute(
                    "UPDATE phone_numbers SET verified_at = ?, verify_code_hash = NULL,"
                    " verify_expires = NULL WHERE id = ?",
                    (_utcnow(), row[0]),
                )
        if failure is not None:
            self.audit(user_id, "phone_verify_failed", target="self",
                       meta={"reason": failure})
            return {"error": ("Verification code expired" if failure == "expired"
                              else "Invalid verification code")}
        self.audit(user_id, "phone_verified", target="self")
        return {"verified": True, "phone": self.get_phone(user_id)}

    def delete_phone(self, user_id: int) -> bool:
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM phone_numbers WHERE user_id = ?", (user_id,))
        if cur.rowcount > 0:
            self.audit(user_id, "phone_deleted", target="self")
        return cur.rowcount > 0

    # ------------------------------------------------------------------
    # Preferences (defaults: sms on after verification, email on, no quiet
    # hours, language "en", max 10/day)
    # ------------------------------------------------------------------

    @staticmethod
    def _prefs_row(row) -> Dict:
        return {
            "user_id": row[0],
            "sms_enabled": bool(row[1]),
            "email_enabled": bool(row[2]),
            "quiet_hours": (
                {"start": row[3], "end": row[4]} if row[3] and row[4] else None
            ),
            "language": row[5],
            "max_per_day": row[6],
        }

    def get_prefs(self, user_id: int) -> Dict:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT user_id, sms_enabled, email_enabled, quiet_start, quiet_end,"
                " language, max_per_day FROM alert_prefs WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO alert_prefs (user_id) VALUES (?)", (user_id,))
                row = conn.execute(
                    "SELECT user_id, sms_enabled, email_enabled, quiet_start, quiet_end,"
                    " language, max_per_day FROM alert_prefs WHERE user_id = ?",
                    (user_id,),
                ).fetchone()
        return self._prefs_row(row)

    def update_prefs(
        self,
        user_id: int,
        sms_enabled: Optional[bool] = None,
        email_enabled: Optional[bool] = None,
        quiet_hours: Optional[Dict] = "unset",
        language: Optional[str] = None,
        max_per_day: Optional[int] = None,
    ) -> Dict:
        """Update preferences. ``quiet_hours`` distinguishes 'unset' (leave),
        None (clear) and {"start","end"} (set, both HH:MM UTC)."""
        self.get_prefs(user_id)  # ensure the row exists
        sets, params = [], []
        if sms_enabled is not None:
            sets.append("sms_enabled = ?")
            params.append(1 if sms_enabled else 0)
        if email_enabled is not None:
            sets.append("email_enabled = ?")
            params.append(1 if email_enabled else 0)
        if quiet_hours != "unset":
            if quiet_hours is None:
                sets += ["quiet_start = NULL", "quiet_end = NULL"]
            else:
                start, end = quiet_hours.get("start"), quiet_hours.get("end")
                if not (_QUIET_HHMM_RE.match(start or "") and _QUIET_HHMM_RE.match(end or "")):
                    return {"error": "quiet_hours must be {'start','end'} in HH:MM (UTC) or null"}
                sets += ["quiet_start = ?", "quiet_end = ?"]
                params += [start, end]
        if language is not None:
            language = str(language).strip()[:10]
            if not re.match(r"^[a-z]{2}(-[A-Za-z]{2})?$", language):
                return {"error": "language must be a code like 'en' or 'en-US'"}
            sets.append("language = ?")
            params.append(language)
        if max_per_day is not None:
            try:
                max_per_day = int(max_per_day)
            except (TypeError, ValueError):
                return {"error": "max_per_day must be an integer"}
            if not (1 <= max_per_day <= 100):
                return {"error": "max_per_day must be between 1 and 100"}
            sets.append("max_per_day = ?")
            params.append(max_per_day)
        if sets:
            with self._lock, self._connect() as conn:
                conn.execute(
                    f"UPDATE alert_prefs SET {', '.join(sets)} WHERE user_id = ?",
                    (*params, user_id),
                )
        return {"prefs": self.get_prefs(user_id)}

    # ------------------------------------------------------------------
    # Alert rules
    # ------------------------------------------------------------------

    @staticmethod
    def _rule_row(row) -> Dict:
        return {
            "id": row[0], "user_id": row[1], "hazard": row[2],
            "lat": row[3], "lon": row[4], "name": row[5],
            "severity_threshold": row[6], "active": bool(row[7]),
            "last_severity": row[8], "last_checked": row[9],
            "created_at": row[10],
        }

    _RULE_COLS = ("id, user_id, hazard, lat, lon, name, severity_threshold,"
                  " active, last_severity, last_checked, created_at")

    def add_rule(
        self,
        user_id: int,
        hazard: str,
        lat: float,
        lon: float,
        name: Optional[str] = None,
        severity_threshold: str = "HIGH",
    ) -> Dict:
        hazard = (hazard or "").strip().lower()[:40]
        if hazard not in _valid_hazards():
            return {"error": f"Unknown hazard (valid: {', '.join(_valid_hazards())})"}
        if not (-90.0 <= float(lat) <= 90.0 and -180.0 <= float(lon) <= 180.0):
            return {"error": "lat/lon out of range"}
        threshold = (severity_threshold or "").strip().upper()
        if threshold not in SEVERITY_THRESHOLDS:
            return {"error": "severity_threshold must be HIGH or EXTREME"}
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO alert_rules"
                " (user_id, hazard, lat, lon, name, severity_threshold, active, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, 1, ?)",
                (user_id, hazard, float(lat), float(lon),
                 (name or "").strip()[:200] or None, threshold, _utcnow()),
            )
            rule_id = cur.lastrowid
        self.audit(user_id, "alert_rule_created", target="self",
                   meta={"rule_id": rule_id, "hazard": hazard,
                         "threshold": threshold})
        return {"rule": self.get_rule(rule_id)}

    def get_rule(self, rule_id: int) -> Optional[Dict]:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                f"SELECT {self._RULE_COLS} FROM alert_rules WHERE id = ?",
                (rule_id,),
            ).fetchone()
        return self._rule_row(row) if row else None

    def list_rules(self, user_id: int, active_only: bool = False) -> List[Dict]:
        sql = f"SELECT {self._RULE_COLS} FROM alert_rules WHERE user_id = ?"
        if active_only:
            sql += " AND active = 1"
        with self._lock, self._connect() as conn:
            rows = conn.execute(sql + " ORDER BY id", (user_id,)).fetchall()
        return [self._rule_row(r) for r in rows]

    def list_active_rules(self) -> List[Dict]:
        """All active rules across users (periodic checker only)."""
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                f"SELECT {self._RULE_COLS} FROM alert_rules WHERE active = 1"
                " ORDER BY id"
            ).fetchall()
        return [self._rule_row(r) for r in rows]

    def delete_rule(self, user_id: int, rule_id: int) -> bool:
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM alert_rules WHERE id = ? AND user_id = ?",
                (rule_id, user_id),
            )
        if cur.rowcount > 0:
            self.audit(user_id, "alert_rule_deleted", target="self",
                       meta={"rule_id": rule_id})
        return cur.rowcount > 0

    def delete_rules_for_user(self, user_id: int) -> int:
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM alert_rules WHERE user_id = ?", (user_id,))
        return cur.rowcount

    def update_rule_state(
        self,
        rule_id: int,
        last_severity: Optional[str],
        last_checked: Optional[str] = None,
    ) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE alert_rules SET last_severity = ?, last_checked = ? WHERE id = ?",
                (last_severity, last_checked or _utcnow(), rule_id),
            )

    # ------------------------------------------------------------------
    # Webhook subscriptions (per-user isolation; cap 5/user; the signing
    # secret is generated here and returned ONCE — see webhooks.py)
    # ------------------------------------------------------------------

    @staticmethod
    def _webhook_row(row, include_secret: bool = False) -> Dict:
        webhook = {
            "id": row[0], "user_id": row[1], "url": row[2],
            "events": [e for e in (row[4] or "").split(",") if e],
            "active": bool(row[5]), "created_at": row[6],
        }
        if include_secret:
            webhook["secret_hash"] = row[3]
        return webhook

    _WEBHOOK_COLS = "id, user_id, url, secret_hash, events, active, created_at"

    def add_webhook(self, user_id: int, url: str, events: List[str]) -> Dict:
        """
        Create a webhook subscription. Returns
        ``{"webhook": …, "secret": <signing secret>}`` — the secret is
        returned ONLY here (it is the HMAC key for
        ``X-Talaix-Signature``; see ``webhooks.generate_secret``) and
        must never be logged or included in later API responses. URL
        validation (HTTPS + SSRF guard) happens in the API layer
        (``webhooks.target_allowed``) before this is called.
        """
        url = (url or "").strip()[:500]
        if not url:
            return {"error": "A webhook url is required"}
        clean_events = []
        for event in events or []:
            event = (event or "").strip()
            if event not in WEBHOOK_EVENTS:
                return {"error": f"Unknown event (valid: {', '.join(WEBHOOK_EVENTS)})"}
            if event not in clean_events:
                clean_events.append(event)
        if not clean_events:
            return {"error": "At least one event is required "
                             f"(valid: {', '.join(WEBHOOK_EVENTS)})"}
        from . import webhooks as webhooks_module

        secret = webhooks_module.generate_secret()
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM webhook_subscriptions WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            if int(row[0]) >= MAX_WEBHOOKS_PER_USER:
                return {"error": f"Webhook limit reached ({MAX_WEBHOOKS_PER_USER})"}
            cur = conn.execute(
                "INSERT INTO webhook_subscriptions"
                " (user_id, url, secret_hash, events, active, created_at)"
                " VALUES (?, ?, ?, ?, 1, ?)",
                (user_id, url, secret, ",".join(clean_events), _utcnow()),
            )
            webhook_id = cur.lastrowid
        # Audit: operational facts only — never the signing secret.
        self.audit(user_id, "webhook_created", target="self",
                   meta={"webhook_id": webhook_id, "events": clean_events})
        return {"webhook": self.get_webhook(user_id, webhook_id), "secret": secret}

    def get_webhook(self, user_id: int, webhook_id: int) -> Optional[Dict]:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                f"SELECT {self._WEBHOOK_COLS} FROM webhook_subscriptions"
                " WHERE id = ? AND user_id = ?",
                (webhook_id, user_id),
            ).fetchone()
        return self._webhook_row(row) if row else None

    def list_webhooks(self, user_id: int) -> List[Dict]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                f"SELECT {self._WEBHOOK_COLS} FROM webhook_subscriptions"
                " WHERE user_id = ? ORDER BY id",
                (user_id,),
            ).fetchall()
        return [self._webhook_row(r) for r in rows]

    def list_active_webhooks_for_event(self, user_id: int, event_type: str) -> List[Dict]:
        """Active subscriptions of a user that include ``event_type``
        (internal dispatch use only — rows include the signing secret)."""
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                f"SELECT {self._WEBHOOK_COLS} FROM webhook_subscriptions"
                " WHERE user_id = ? AND active = 1 ORDER BY id",
                (user_id,),
            ).fetchall()
        return [
            self._webhook_row(r, include_secret=True)
            for r in rows
            if event_type in (r[4] or "").split(",")
        ]

    def delete_webhook(self, user_id: int, webhook_id: int) -> bool:
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM webhook_subscriptions WHERE id = ? AND user_id = ?",
                (webhook_id, user_id),
            )
        if cur.rowcount > 0:
            self.audit(user_id, "webhook_deleted", target="self",
                       meta={"webhook_id": webhook_id})
        return cur.rowcount > 0

    # ------------------------------------------------------------------
    # Alert records + deliveries
    # ------------------------------------------------------------------

    @staticmethod
    def make_alert_id(rule_id: int, hazard: str, severity: str, trigger: str,
                      analysis_id: str, created_at: str) -> str:
        """Content-derived alert id: ``al_<hash16>``."""
        digest = hashlib.sha256(
            f"{rule_id}|{hazard}|{severity}|{trigger}|{analysis_id}|{created_at}"
            .encode("utf-8")
        ).hexdigest()[:16]
        return f"al_{digest}"

    def record_alert(
        self,
        user_id: int,
        rule_id: int,
        hazard: str,
        lat: Optional[float],
        lon: Optional[float],
        severity: str,
        trigger: str,
        analysis_id: Optional[str],
        data_version: Optional[str],
        suppressed: bool = False,
        created_at: Optional[str] = None,
    ) -> str:
        created = created_at or _utcnow()
        alert_id = self.make_alert_id(rule_id, hazard, severity, trigger,
                                      analysis_id or "", created)
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO alert_records"
                " (id, user_id, rule_id, hazard, lat, lon, severity, trigger,"
                "  analysis_id, data_version, created_at, suppressed)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (alert_id, user_id, rule_id, (hazard or "")[:40], lat, lon,
                 (severity or "")[:20], (trigger or "")[:40],
                 (analysis_id or "")[:80], (data_version or "")[:200],
                 created, 1 if suppressed else 0),
            )
        return alert_id

    def record_delivery(
        self,
        alert_id: str,
        channel: str,
        target: Optional[str],
        status: str,
        provider_message_id: Optional[str] = None,
    ) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO alert_deliveries"
                " (alert_id, channel, target, status, provider_message_id, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (alert_id, (channel or "")[:10], (target or "")[:200],
                 (status or "")[:40], (provider_message_id or "")[:200], _utcnow()),
            )

    def find_recent_alert(
        self,
        rule_id: int,
        hazard: str,
        severity: str,
        trigger: str,
        within_seconds: float,
    ) -> Optional[Dict]:
        """Most recent alert for the same rule+hazard+severity+trigger inside
        the cooldown window (dedupe), else None."""
        cutoff = datetime.utcfromtimestamp(
            time.time() - within_seconds).isoformat() + "Z"
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT id, user_id, rule_id, hazard, severity, trigger, created_at"
                " FROM alert_records"
                " WHERE rule_id = ? AND hazard = ? AND severity = ? AND trigger = ?"
                " AND created_at >= ? ORDER BY created_at DESC LIMIT 1",
                (rule_id, hazard, severity, trigger, cutoff),
            ).fetchone()
        if row is None:
            return None
        return {"id": row[0], "user_id": row[1], "rule_id": row[2],
                "hazard": row[3], "severity": row[4], "trigger": row[5],
                "created_at": row[6]}

    def count_deliveries_today(self, user_id: int) -> int:
        """Deliveries today (UTC) that consumed notification budget
        (sent | outbox | held_quiet_hours), across all channels."""
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM alert_deliveries d"
                " JOIN alert_records r ON r.id = d.alert_id"
                " WHERE r.user_id = ? AND d.created_at >= ?"
                " AND d.status IN ('sent', 'outbox', 'held_quiet_hours')",
                (user_id, _today()),
            ).fetchone()
        return int(row[0]) if row else 0

    def list_history(self, user_id: int, limit: int = 50) -> List[Dict]:
        """Own alert records (newest first) with their deliveries."""
        with self._lock, self._connect() as conn:
            records = conn.execute(
                "SELECT id, rule_id, hazard, lat, lon, severity, trigger,"
                " analysis_id, data_version, created_at, suppressed"
                " FROM alert_records WHERE user_id = ?"
                " ORDER BY created_at DESC, id DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
            deliveries = conn.execute(
                "SELECT alert_id, channel, target, status, provider_message_id,"
                " created_at FROM alert_deliveries"
                " WHERE alert_id IN"
                " (SELECT id FROM alert_records WHERE user_id = ?)"
                " ORDER BY id",
                (user_id,),
            ).fetchall()
        by_alert: Dict[str, List[Dict]] = {}
        for d in deliveries:
            by_alert.setdefault(d[0], []).append({
                "channel": d[1], "target": d[2], "status": d[3],
                "provider_message_id": d[4], "created_at": d[5],
            })
        return [
            {
                "id": r[0], "rule_id": r[1], "hazard": r[2], "lat": r[3],
                "lon": r[4], "severity": r[5], "trigger": r[6],
                "analysis_id": r[7], "data_version": r[8],
                "created_at": r[9], "suppressed": bool(r[10]),
                "deliveries": by_alert.get(r[0], []),
            }
            for r in records
        ]
