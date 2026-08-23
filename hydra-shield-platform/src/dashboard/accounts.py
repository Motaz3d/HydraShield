"""
Talaix user accounts (Stage 6) — SQLite store.

Implements the data model of docs/USER_AND_SUBSCRIPTION_ARCHITECTURE.md §3
in the shared platform SQLite database (same file as the cache / watches;
``HYDRASHIELD_CACHE_DB``). All tables are created with
``CREATE TABLE IF NOT EXISTS`` — additive only, never destructive.

Security norms (docs §3/§4):

- Passwords: PBKDF2-HMAC-SHA256 (stdlib ``hashlib``, 120 000 iterations,
  per-user random salt). Plaintext passwords are never stored or logged.
- Tokens (email verification, sessions): ``secrets.token_urlsafe(32)``
  random values, stored **hashed** — HMAC-SHA256 keyed with a server-side
  secret. The secret comes from ``HYDRASHIELD_SECRET_KEY``; when unset, a
  development fallback is derived from machine-stable attributes (hostname
  + user home), which keeps tokens verifiable across restarts on one
  machine but MUST be replaced by an explicit secret in production
  (documented in ``.env.example``). Plaintext tokens never touch the DB.
- Comparisons are constant-time (``hmac.compare_digest``).
- All SQL is parameterised.
- The audit log records security events (register/verify/login/logout/
  key create/role change) — never passwords or tokens.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import platform
import re
import secrets
import sqlite3
import threading
from datetime import datetime
from typing import Dict, List, Optional

from .cache import default_cache

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

MIN_PASSWORD_LENGTH = 10
PBKDF2_ITERATIONS = 120_000

SESSION_TTL_SECONDS = 30 * 24 * 3600          # 30 days
EMAIL_TOKEN_TTL_SECONDS = 24 * 3600           # 24 hours

# Progressive-gating ranks (docs §1/§2): a session user must rank >= the
# required role. Nothing sensitive is granted by default.
ROLE_RANK = {
    "anonymous": 0,
    "visitor": 1,
    "registered": 2,
    "subscriber": 3,
    "professional": 3,
    "business": 4,
    "municipality": 4,
    "government": 4,
    "admin": 5,
}

DEFAULT_ROLE = "registered"

# Per-tier API rate limits (requests per 60 s sliding window) used by the
# v2 auth blueprint on top of the per-IP limiter.
TIER_RATE_LIMITS = {
    "anonymous": (30, 60.0),
    "visitor": (60, 60.0),
    "registered": (120, 60.0),
    "subscriber": (600, 60.0),
    "professional": (600, 60.0),
    "business": (1200, 60.0),
    "municipality": (1200, 60.0),
    "government": (1200, 60.0),
    "admin": (6000, 60.0),
}


def _utcnow() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _parse_ts(value: str) -> float:
    return datetime.fromisoformat(value.rstrip("Z")).timestamp()


def _server_key() -> bytes:
    """Server-side HMAC key for token hashing (see module docstring)."""
    key = os.environ.get("HYDRASHIELD_SECRET_KEY")
    if key:
        return key.encode("utf-8")
    basis = f"hydrashield-dev-token-key|{platform.node()}|{os.path.expanduser('~')}"
    return hashlib.sha256(basis.encode("utf-8")).digest()


def hash_token(token: str) -> str:
    """HMAC-SHA256 of a plaintext token with the server-side key."""
    return hmac.new(_server_key(), token.encode("utf-8"), hashlib.sha256).hexdigest()


class UserStore:
    """SQLite-backed store for users, sessions and account data."""

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
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    display_name TEXT,
                    role TEXT NOT NULL DEFAULT 'registered',
                    status TEXT NOT NULL DEFAULT 'pending',
                    email_verified_at TEXT,
                    created_at TEXT NOT NULL,
                    last_login_at TEXT
                );
                CREATE TABLE IF NOT EXISTS email_tokens (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    token_hash TEXT NOT NULL,
                    purpose TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    used_at TEXT
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    token_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    ip TEXT,
                    user_agent TEXT
                );
                CREATE TABLE IF NOT EXISTS organizations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    kind TEXT,
                    seats INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS organization_members (
                    org_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    role TEXT NOT NULL DEFAULT 'member',
                    PRIMARY KEY (org_id, user_id)
                );
                CREATE TABLE IF NOT EXISTS subscriptions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_user_id INTEGER,
                    owner_org_id INTEGER,
                    tier TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    started_at TEXT NOT NULL,
                    ends_at TEXT,
                    external_ref TEXT
                );
                CREATE TABLE IF NOT EXISTS api_keys (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    key_hash TEXT NOT NULL,
                    label TEXT,
                    created_at TEXT NOT NULL,
                    revoked_at TEXT
                );
                CREATE TABLE IF NOT EXISTS saved_locations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    lat REAL NOT NULL,
                    lon REAL NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS analysis_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    anon_id TEXT,
                    hazard TEXT,
                    lat REAL,
                    lon REAL,
                    params_json TEXT,
                    summary_json TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS report_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    report_type TEXT,
                    hazard TEXT,
                    lat REAL,
                    lon REAL,
                    params_json TEXT,
                    report_meta_json TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS alert_subscriptions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    hazard TEXT NOT NULL DEFAULT 'wildfire',
                    lat REAL NOT NULL,
                    lon REAL NOT NULL,
                    threshold_json TEXT,
                    channel TEXT NOT NULL DEFAULT 'email',
                    created_at TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS usage_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    endpoint TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    meta_json TEXT
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
    # Validation
    # ------------------------------------------------------------------

    @staticmethod
    def validate_email(email: str) -> Optional[str]:
        """Return an error message when the email is invalid, else None."""
        if not email or not _EMAIL_RE.match(email) or len(email) > 254:
            return "A valid email address is required"
        return None

    @staticmethod
    def validate_password(password: str) -> Optional[str]:
        """Return an error message when the password is too weak, else None."""
        if not password or len(password) < MIN_PASSWORD_LENGTH:
            return f"Password must be at least {MIN_PASSWORD_LENGTH} characters"
        if len(password) > 512:
            return "Password is too long"
        return None

    # ------------------------------------------------------------------
    # Password hashing (PBKDF2-HMAC-SHA256, per-user salt)
    # ------------------------------------------------------------------

    @staticmethod
    def hash_password(password: str) -> str:
        salt = secrets.token_bytes(16)
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
        return f"pbkdf2-sha256${PBKDF2_ITERATIONS}${salt.hex()}${dk.hex()}"

    @staticmethod
    def verify_password(password: str, stored: str) -> bool:
        try:
            scheme, iterations, salt_hex, dk_hex = stored.split("$")
            if scheme != "pbkdf2-sha256":
                return False
            dk = hashlib.pbkdf2_hmac(
                "sha256", password.encode("utf-8"),
                bytes.fromhex(salt_hex), int(iterations))
        except (ValueError, TypeError):
            return False
        return hmac.compare_digest(dk.hex(), dk_hex)

    # ------------------------------------------------------------------
    # Users
    # ------------------------------------------------------------------

    @staticmethod
    def _public_user(row) -> Dict:
        return {
            "id": row[0],
            "email": row[1],
            "display_name": row[3],
            "role": row[4],
            "status": row[5],
            "email_verified_at": row[6],
            "created_at": row[7],
            "last_login_at": row[8],
        }

    _USER_COLS = ("id, email, password_hash, display_name, role, status,"
                  " email_verified_at, created_at, last_login_at")

    def register_user(
        self,
        email: str,
        password: str,
        display_name: Optional[str] = None,
        consent: bool = False,
    ) -> Dict:
        """
        Create an unverified user (least privilege: default role
        ``registered``, status ``pending``). Returns the public user dict
        or ``{"error": …}``. ``consent`` records the GDPR registration
        consent given at sign-up (audit-trailed, never the password).
        """
        email = (email or "").strip().lower()
        err = self.validate_email(email) or self.validate_password(password)
        if err:
            return {"error": err}
        if self.get_user_by_email(email) is not None:
            return {"error": "This email address is already registered"}
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO users (email, password_hash, display_name, role, status, created_at)"
                " VALUES (?, ?, ?, ?, 'pending', ?)",
                (
                    email,
                    self.hash_password(password),
                    (display_name or "").strip()[:200] or None,
                    DEFAULT_ROLE,
                    _utcnow(),
                ),
            )
            user_id = cur.lastrowid
        # GDPR: record the registration consent (in-memory helper + durable
        # audit entry); only the fact of consent is stored, never secrets.
        from ..security.gdpr import GdprCompliance

        GdprCompliance().record_consent(
            str(user_id), "account_registration", bool(consent), lawful_basis="consent")
        self.audit(user_id, "register", target=email,
                   meta={"consent": bool(consent)})
        return self.get_user(user_id)

    def get_user(self, user_id: int) -> Optional[Dict]:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                f"SELECT {self._USER_COLS} FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
        return self._public_user(row) if row else None

    def get_user_by_email(self, email: str) -> Optional[Dict]:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                f"SELECT {self._USER_COLS} FROM users WHERE email = ?",
                ((email or "").strip().lower(),),
            ).fetchone()
        return self._public_user(row) if row else None

    def check_password(self, email: str, password: str) -> Optional[Dict]:
        """Return the public user when email+password match, else None."""
        with self._lock, self._connect() as conn:
            row = conn.execute(
                f"SELECT {self._USER_COLS} FROM users WHERE email = ?",
                ((email or "").strip().lower(),),
            ).fetchone()
        if row is None:
            # Run a dummy verification so timing does not reveal whether the
            # account exists.
            self.verify_password(password or "", self.hash_password("x" * 16))
            return None
        if not self.verify_password(password or "", row[2]):
            return None
        return self._public_user(row)

    def update_user(self, user_id: int, display_name: Optional[str] = None) -> Optional[Dict]:
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE users SET display_name = ? WHERE id = ?",
                ((display_name or "").strip()[:200] or None, user_id),
            )
        return self.get_user(user_id)

    def mark_email_verified(self, user_id: int) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE users SET status = 'active', email_verified_at = ? WHERE id = ?",
                (_utcnow(), user_id),
            )

    def touch_login(self, user_id: int) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE users SET last_login_at = ? WHERE id = ?",
                (_utcnow(), user_id),
            )

    def set_password(self, user_id: int, new_password: str) -> Optional[str]:
        """Set a new password (reset flow). Returns an error message or None."""
        err = self.validate_password(new_password)
        if err:
            return err
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?",
                (self.hash_password(new_password), user_id),
            )
        return None

    def delete_user_sessions(self, user_id: int) -> int:
        """Invalidate every session of a user (password reset / compromise)."""
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM sessions WHERE user_id = ?", (user_id,)
            )
            return cur.rowcount

    # ------------------------------------------------------------------
    # Email tokens (verification etc.) — stored hashed, TTL'd
    # ------------------------------------------------------------------

    def create_email_token(
        self, user_id: int, purpose: str,
        ttl_seconds: float = EMAIL_TOKEN_TTL_SECONDS,
    ) -> str:
        """Create a purpose-bound email token; returns the plaintext token
        (only the HMAC hash is stored)."""
        token = secrets.token_urlsafe(32)
        expires = datetime.utcfromtimestamp(
            datetime.utcnow().timestamp() + ttl_seconds).isoformat() + "Z"
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO email_tokens (user_id, token_hash, purpose, expires_at)"
                " VALUES (?, ?, ?, ?)",
                (user_id, hash_token(token), purpose, expires),
            )
        return token

    def consume_email_token(self, token: str, purpose: str) -> Optional[int]:
        """
        Validate a plaintext email token for ``purpose``: it must exist
        (by hash), be unexpired and unused. Marks it used and returns the
        user id, else None.
        """
        if not token:
            return None
        digest = hash_token(token)
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT id, user_id, expires_at, used_at FROM email_tokens"
                " WHERE token_hash = ? AND purpose = ?",
                (digest, purpose),
            ).fetchone()
            if row is None or row[3] is not None:
                return None
            if _parse_ts(row[2]) < datetime.utcnow().timestamp():
                return None
            conn.execute(
                "UPDATE email_tokens SET used_at = ? WHERE id = ?",
                (_utcnow(), row[0]),
            )
            return row[1]

    # ------------------------------------------------------------------
    # Sessions — Bearer token / cookie, stored hashed
    # ------------------------------------------------------------------

    def create_session(
        self,
        user_id: int,
        ip: Optional[str] = None,
        user_agent: Optional[str] = None,
        ttl_seconds: float = SESSION_TTL_SECONDS,
    ) -> str:
        """Create a session; returns the plaintext token (only its HMAC
        hash is stored)."""
        token = secrets.token_urlsafe(32)
        now = datetime.utcnow().timestamp()
        expires = datetime.utcfromtimestamp(now + ttl_seconds).isoformat() + "Z"
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO sessions (user_id, token_hash, created_at, expires_at, ip, user_agent)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (user_id, hash_token(token), _utcnow(), expires,
                 (ip or "")[:64], (user_agent or "")[:256]),
            )
        return token

    def get_session_user(self, token: str) -> Optional[Dict]:
        """Resolve a session token (Bearer or cookie) to its active user."""
        if not token:
            return None
        digest = hash_token(token)
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT user_id, expires_at FROM sessions WHERE token_hash = ?",
                (digest,),
            ).fetchone()
        if row is None or _parse_ts(row[1]) < datetime.utcnow().timestamp():
            return None
        user = self.get_user(row[0])
        if user is None or user["status"] != "active":
            return None
        return self._maybe_promote_operator(user)

    def _maybe_promote_operator(self, user: Dict) -> Dict:
        """Server-side operator promotion: accounts whose email is listed in
        HYDRASHIELD_OPERATOR_EMAILS (comma-separated, server env only)
        receive the admin role. There is NO endpoint or client path to set
        a role — promotion happens here, at session resolution, from the
        server environment. Idempotent and audited."""
        emails = {e.strip().lower()
                  for e in os.environ.get("HYDRASHIELD_OPERATOR_EMAILS", "").split(",")
                  if e.strip()}
        if not emails or (user.get("email") or "").lower() not in emails:
            return user
        if ROLE_RANK.get(user["role"], 0) >= ROLE_RANK["admin"]:
            return user
        with self._lock, self._connect() as conn:
            conn.execute("UPDATE users SET role = 'admin' WHERE id = ?",
                         (user["id"],))
        self.audit(user["id"], "operator_promotion", target=user["email"],
                   meta={"via": "HYDRASHIELD_OPERATOR_EMAILS"})
        user = self.get_user(user["id"])
        return user

    def delete_session(self, token: str) -> bool:
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM sessions WHERE token_hash = ?",
                (hash_token(token or ""),),
            )
            return cur.rowcount > 0

    # ------------------------------------------------------------------
    # API keys (external consumers) — ``hs_`` + 192-bit random, stored
    # HMAC-hashed like sessions; plaintext returned ONCE at creation.
    # Keys are read-only credentials: they identify the consumer for usage
    # metering and never grant write access (enforced in auth_api).
    # ------------------------------------------------------------------

    @staticmethod
    def _api_key_row(row) -> Dict:
        return {
            "id": row[0], "label": row[1], "created_at": row[2],
            "revoked": row[3] is not None, "revoked_at": row[3],
        }

    def create_api_key(self, user_id: int, label: Optional[str] = None) -> Dict:
        """
        Create an API key for a user. Returns
        ``{"id", "key", "label", "created_at"}`` — the plaintext ``key``
        (``hs_`` + ``secrets.token_urlsafe(24)``) is returned ONLY here;
        just its HMAC hash is stored.
        """
        key = "hs_" + secrets.token_urlsafe(24)
        label = (label or "").strip()[:200] or None
        created = _utcnow()
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO api_keys (user_id, key_hash, label, created_at)"
                " VALUES (?, ?, ?, ?)",
                (user_id, hash_token(key), label, created),
            )
            key_id = cur.lastrowid
        self.audit(user_id, "api_key_created", target="self",
                   meta={"key_id": key_id, "label": label})
        return {"id": key_id, "key": key, "label": label, "created_at": created}

    def list_api_keys(self, user_id: int) -> List[Dict]:
        """Own API keys (id/label/created_at/revoked — never the hash)."""
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT id, label, created_at, revoked_at FROM api_keys"
                " WHERE user_id = ? ORDER BY id",
                (user_id,),
            ).fetchall()
        return [self._api_key_row(r) for r in rows]

    def revoke_api_key(self, user_id: int, key_id: int) -> bool:
        """Revoke one of the user's keys (per-user isolation). Idempotent
        only for active keys; returns False when the key does not exist or
        is already revoked."""
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "UPDATE api_keys SET revoked_at = ?"
                " WHERE id = ? AND user_id = ? AND revoked_at IS NULL",
                (_utcnow(), key_id, user_id),
            )
        if cur.rowcount > 0:
            self.audit(user_id, "api_key_revoked", target="self",
                       meta={"key_id": key_id})
        return cur.rowcount > 0

    def get_user_by_api_key(self, key: str) -> Optional[Dict]:
        """
        Resolve a plaintext API key to its active user: the key is hashed
        and looked up among non-revoked keys (single digest equality, so
        there is no per-byte early-exit timing signal on the plaintext).
        Returns None for unknown or revoked keys.
        """
        if not key:
            return None
        digest = hash_token(key)
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT user_id FROM api_keys"
                " WHERE key_hash = ? AND revoked_at IS NULL",
                (digest,),
            ).fetchone()
        if row is None:
            return None
        user = self.get_user(row[0])
        if user is None or user["status"] != "active":
            return None
        return user

    # ------------------------------------------------------------------
    # Subscriptions (self-service; recorded, never charged — docs
    # USER_AND_SUBSCRIPTION_ARCHITECTURE.md §7: ``external_ref`` awaits a
    # payment provider). Activating promotes the account to the
    # ``subscriber`` tier; cancelling returns it to ``registered``.
    # ------------------------------------------------------------------

    @staticmethod
    def _subscription_row(row) -> Dict:
        return {
            "id": row[0], "tier": row[1], "status": row[2],
            "started_at": row[3], "ends_at": row[4],
        }

    def get_active_subscription(self, user_id: int) -> Optional[Dict]:
        """The user's active self-service subscription, else None."""
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT id, tier, status, started_at, ends_at FROM subscriptions"
                " WHERE owner_user_id = ? AND status = 'active'"
                " ORDER BY id DESC LIMIT 1",
                (user_id,),
            ).fetchone()
        return self._subscription_row(row) if row else None

    def activate_subscription(self, user_id: int, tier: str = "subscriber") -> Dict:
        """
        Activate a subscription for the user. Idempotent: an already-active
        subscription is returned unchanged. Promotes the role only when the
        current role ranks below the tier (operator/admin roles are never
        touched). Audited as ``subscribe``.
        """
        started = _utcnow()
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT id, tier, status, started_at, ends_at FROM subscriptions"
                " WHERE owner_user_id = ? AND status = 'active'"
                " ORDER BY id DESC LIMIT 1",
                (user_id,),
            ).fetchone()
            if row is not None:
                return self._subscription_row(row)
            cur = conn.execute(
                "INSERT INTO subscriptions"
                " (owner_user_id, tier, status, started_at)"
                " VALUES (?, ?, 'active', ?)",
                (user_id, (tier or "subscriber")[:40], started),
            )
            sub_id = cur.lastrowid
        user = self.get_user(user_id)
        if user and ROLE_RANK.get(user["role"], 0) < ROLE_RANK.get(tier, 3):
            with self._lock, self._connect() as conn:
                conn.execute("UPDATE users SET role = ? WHERE id = ?",
                             ((tier or "subscriber")[:40], user_id))
        self.audit(user_id, "subscribe", target=tier,
                   meta={"subscription_id": sub_id})
        return {"id": sub_id, "tier": tier, "status": "active",
                "started_at": started, "ends_at": None}

    def cancel_subscription(self, user_id: int) -> Optional[Dict]:
        """
        Cancel the user's active subscription (idempotent — returns None
        when none is active). The role is demoted only when it is exactly
        the self-service ``subscriber`` tier; higher/operator roles are
        never demoted here. Audited as ``unsubscribe``.
        """
        ended = _utcnow()
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT id, tier, status, started_at, ends_at FROM subscriptions"
                " WHERE owner_user_id = ? AND status = 'active'"
                " ORDER BY id DESC LIMIT 1",
                (user_id,),
            ).fetchone()
            if row is None:
                return None
            active = self._subscription_row(row)
            conn.execute(
                "UPDATE subscriptions SET status = 'cancelled', ends_at = ?"
                " WHERE id = ?",
                (ended, active["id"]),
            )
        user = self.get_user(user_id)
        if user and user["role"] == active["tier"] == "subscriber":
            with self._lock, self._connect() as conn:
                conn.execute(
                    "UPDATE users SET role = ? WHERE id = ?",
                    (DEFAULT_ROLE, user_id))
        self.audit(user_id, "unsubscribe", target=active["tier"],
                   meta={"subscription_id": active["id"]})
        active["status"] = "cancelled"
        active["ends_at"] = ended
        return active

    # ------------------------------------------------------------------
    # Saved locations (per-user isolation enforced in every query)
    # ------------------------------------------------------------------

    def add_location(self, user_id: int, name: str, lat: float, lon: float) -> Dict:
        name = (name or "").strip()[:200]
        if not name:
            return {"error": "A location name is required"}
        if not (-90.0 <= float(lat) <= 90.0 and -180.0 <= float(lon) <= 180.0):
            return {"error": "lat/lon out of range"}
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO saved_locations (user_id, name, lat, lon, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (user_id, name, float(lat), float(lon), _utcnow()),
            )
            loc_id = cur.lastrowid
        return {"id": loc_id, "name": name, "lat": float(lat), "lon": float(lon)}

    def list_locations(self, user_id: int) -> List[Dict]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT id, name, lat, lon, created_at FROM saved_locations"
                " WHERE user_id = ? ORDER BY id",
                (user_id,),
            ).fetchall()
        return [{"id": r[0], "name": r[1], "lat": r[2], "lon": r[3],
                 "created_at": r[4]} for r in rows]

    def delete_location(self, user_id: int, location_id: int) -> bool:
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM saved_locations WHERE id = ? AND user_id = ?",
                (location_id, user_id),
            )
            return cur.rowcount > 0

    # ------------------------------------------------------------------
    # Alert subscriptions (account-based path; supersedes anon watches)
    # ------------------------------------------------------------------

    def add_alert(
        self,
        user_id: int,
        hazard: str,
        lat: float,
        lon: float,
        threshold: Optional[Dict] = None,
        channel: str = "email",
    ) -> Dict:
        if not (-90.0 <= float(lat) <= 90.0 and -180.0 <= float(lon) <= 180.0):
            return {"error": "lat/lon out of range"}
        hazard = (hazard or "wildfire").strip()[:40]
        channel = (channel or "email").strip()[:40]
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO alert_subscriptions"
                " (user_id, hazard, lat, lon, threshold_json, channel, created_at, active)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, 1)",
                (user_id, hazard, float(lat), float(lon),
                 json.dumps(threshold or {}, default=str)[:1000], channel, _utcnow()),
            )
            alert_id = cur.lastrowid
        return {"id": alert_id, "hazard": hazard, "lat": float(lat),
                "lon": float(lon), "threshold": threshold or {},
                "channel": channel, "active": True}

    def list_alerts(self, user_id: int) -> List[Dict]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT id, hazard, lat, lon, threshold_json, channel, created_at, active"
                " FROM alert_subscriptions WHERE user_id = ? ORDER BY id",
                (user_id,),
            ).fetchall()
        return [
            {
                "id": r[0], "hazard": r[1], "lat": r[2], "lon": r[3],
                "threshold": json.loads(r[4] or "{}"), "channel": r[5],
                "created_at": r[6], "active": bool(r[7]),
            }
            for r in rows
        ]

    def delete_alert(self, user_id: int, alert_id: int) -> bool:
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM alert_subscriptions WHERE id = ? AND user_id = ?",
                (alert_id, user_id),
            )
            return cur.rowcount > 0

    # ------------------------------------------------------------------
    # History (analyses + reports) and usage
    # ------------------------------------------------------------------

    def record_analysis(
        self,
        user_id: Optional[int],
        hazard: str,
        lat: float,
        lon: float,
        params: Optional[Dict] = None,
        summary: Optional[Dict] = None,
        anon_id: Optional[str] = None,
    ) -> int:
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO analysis_history"
                " (user_id, anon_id, hazard, lat, lon, params_json, summary_json, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (user_id, anon_id, (hazard or "")[:40], lat, lon,
                 json.dumps(params or {}, default=str)[:4000],
                 json.dumps(summary or {}, default=str)[:4000], _utcnow()),
            )
            return cur.lastrowid

    def record_report(
        self,
        user_id: int,
        report_type: str,
        hazard: str,
        lat: float,
        lon: float,
        params: Optional[Dict] = None,
        report_meta: Optional[Dict] = None,
    ) -> int:
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO report_history"
                " (user_id, report_type, hazard, lat, lon, params_json, report_meta_json, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (user_id, (report_type or "")[:40], (hazard or "")[:40], lat, lon,
                 json.dumps(params or {}, default=str)[:4000],
                 json.dumps(report_meta or {}, default=str)[:4000], _utcnow()),
            )
            return cur.lastrowid

    def get_history(self, user_id: int, limit: int = 50) -> Dict:
        with self._lock, self._connect() as conn:
            analyses = conn.execute(
                "SELECT id, hazard, lat, lon, params_json, summary_json, created_at"
                " FROM analysis_history WHERE user_id = ? ORDER BY id DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
            reports = conn.execute(
                "SELECT id, report_type, hazard, lat, lon, params_json, report_meta_json, created_at"
                " FROM report_history WHERE user_id = ? ORDER BY id DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
        return {
            "analyses": [
                {"id": r[0], "hazard": r[1], "lat": r[2], "lon": r[3],
                 "params": json.loads(r[4] or "{}"),
                 "summary": json.loads(r[5] or "{}"), "created_at": r[6]}
                for r in analyses
            ],
            "reports": [
                {"id": r[0], "report_type": r[1], "hazard": r[2], "lat": r[3],
                 "lon": r[4], "params": json.loads(r[5] or "{}"),
                 "report_meta": json.loads(r[6] or "{}"), "created_at": r[7]}
                for r in reports
            ],
        }

    def log_usage(self, user_id: Optional[int], endpoint: str, meta: Optional[Dict] = None) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO usage_log (user_id, endpoint, created_at, meta_json)"
                " VALUES (?, ?, ?, ?)",
                (user_id, (endpoint or "")[:200], _utcnow(),
                 json.dumps(meta or {}, default=str)[:2000]),
            )

    def get_usage(self, user_id: int, limit: int = 100) -> List[Dict]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT id, endpoint, created_at, meta_json FROM usage_log"
                " WHERE user_id = ? ORDER BY id DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
        return [{"id": r[0], "endpoint": r[1], "created_at": r[2],
                 "meta": json.loads(r[3] or "{}")} for r in rows]

    # ------------------------------------------------------------------
    # Audit log — security events only, never passwords or tokens
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

    def list_audit(self, user_id: Optional[int] = None, limit: int = 100) -> List[Dict]:
        with self._lock, self._connect() as conn:
            if user_id is None:
                rows = conn.execute(
                    "SELECT id, actor_user_id, action, target, meta_json, created_at"
                    " FROM audit_log ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, actor_user_id, action, target, meta_json, created_at"
                    " FROM audit_log WHERE actor_user_id = ? ORDER BY id DESC LIMIT ?",
                    (user_id, limit),
                ).fetchall()
        return [
            {"id": r[0], "actor_user_id": r[1], "action": r[2], "target": r[3],
             "meta": json.loads(r[4] or "{}"), "created_at": r[5]}
            for r in rows
        ]
