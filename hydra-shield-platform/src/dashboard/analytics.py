"""
HydraShield product analytics — first-party, privacy-conscious event store.

Why first-party: no third-party analytics dependency, no data leaves the
platform, no cross-site tracking. The event stream answers product
questions (which hazards/pages/solutions attract use, where the funnel
converts) without becoming surveillance.

Privacy design (docs/PRODUCT_ANALYTICS.md is the normative document):

- **No IP addresses stored.** Rate limiting uses the existing in-memory
  per-IP limiter (nothing persisted); events carry no network identity.
- **Pseudonymous session only.** The browser generates a random session id
  kept in localStorage (no cookie); the store persists only its HMAC-SHA256
  hash (``accounts.hash_token``), so even the pseudonym is not stored raw.
- **user_id only on explicit account events.** Browsing events never carry
  a user id; account/subscription events (``account_created``,
  ``subscription_started``, ``sms_enabled``, ``alert_created``) may carry
  the account id so conversion can be counted — that linkage is disclosed
  and consented at registration.
- **Coarse location by construction.** Coordinates are rounded to one
  decimal place (~11 km) server-side; precise user locations are never
  stored from analytics.
- **No sensitive data.** The whitelist rejects unknown event names and
  unknown fields; free-text is never accepted. No passwords, emails, phone
  numbers or message contents can enter this store.
- **Do Not Track honoured** client-side; retention is 12 months rolling
  (``purge_older_than``), and an admin can delete a session's events.

Tables are created with ``CREATE TABLE IF NOT EXISTS`` — additive only —
in the shared platform DB (``HYDRASHIELD_CACHE_DB``).
"""

from __future__ import annotations

import re
import sqlite3
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from .accounts import hash_token
from .cache import default_cache

#: Whitelisted product events (docs/PRODUCT_ANALYTICS.md §2). Unknown
#: event names are rejected — the store cannot be turned into a log of
#: arbitrary user actions.
ALLOWED_EVENTS = frozenset({
    "page_view",
    "hazard_selected",
    "location_analyzed",
    "map_opened",
    "map_layer_enabled",
    "historical_year_selected",
    "event_opened",
    "solution_viewed",
    "solution_saved",
    "report_previewed",
    "report_generated",
    "account_started",
    "account_created",
    "subscription_started",
    "sms_enabled",
    "alert_created",
    "qgis_interest",
    "contact_started",
})

#: Events that may carry an account id (explicit account actions only).
_ACCOUNT_EVENTS = frozenset({
    "account_created", "subscription_started", "sms_enabled", "alert_created",
})

#: Fields accepted per event (anything else is dropped silently).
_ALLOWED_FIELDS = frozenset({
    "event", "session_id", "page", "hazard", "lat", "lon", "feature",
    "referrer", "device", "language",
})

_MAX_BATCH = 20
_MAX_STR = 200
_PAGE_RE = re.compile(r"^[a-z0-9_./#-]{1,120}$", re.IGNORECASE)
_DEVICE_VALUES = frozenset({"desktop", "mobile", "tablet"})
RETENTION_DAYS = 365


def _utcnow() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _clean_str(value, limit: int = _MAX_STR) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()[:limit]
    return text or None


def _round_coord(value) -> Optional[float]:
    """Round a coordinate to 1 decimal place (~11 km) — privacy by
    construction. Non-numeric or out-of-range values become None."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if not (-90.0 <= v <= 90.0 or -180.0 <= v <= 180.0):
        return None
    return round(v, 1)


class AnalyticsStore:
    """SQLite-backed store for pseudonymous product events."""

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
                CREATE TABLE IF NOT EXISTS analytics_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,
                    event TEXT NOT NULL,
                    session_hash TEXT,
                    page TEXT,
                    hazard TEXT,
                    lat REAL,
                    lon REAL,
                    feature TEXT,
                    referrer TEXT,
                    device TEXT,
                    language TEXT,
                    user_id INTEGER
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_analytics_event_ts "
                "ON analytics_events (event, ts)"
            )

    # -- write ---------------------------------------------------------

    def record(self, event: Dict, user_id: Optional[int] = None) -> Dict:
        """Validate and store one event. Returns {"recorded": True} or
        {"error": ...}. Never raises on bad input — analytics must never
        break the product."""
        name = event.get("event")
        if name not in ALLOWED_EVENTS:
            return {"error": f"unknown event {str(name)[:40]!r}"}
        session = _clean_str(event.get("session_id"), 64)
        page = _clean_str(event.get("page"), 120)
        if page and not _PAGE_RE.match(page):
            page = None
        hazard = _clean_str(event.get("hazard"), 40)
        feature = _clean_str(event.get("feature"), 120)
        referrer = _clean_str(event.get("referrer"), 200)
        device = _clean_str(event.get("device"), 20)
        if device not in _DEVICE_VALUES:
            device = None
        language = _clean_str(event.get("language"), 20)
        # user_id only for explicit account events, only from the
        # authenticated server-side session (never trusted from the body).
        uid = user_id if name in _ACCOUNT_EVENTS else None
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO analytics_events (ts, event, session_hash, page,"
                " hazard, lat, lon, feature, referrer, device, language,"
                " user_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (_utcnow(), name,
                 hash_token(session) if session else None,
                 page, hazard,
                 _round_coord(event.get("lat")), _round_coord(event.get("lon")),
                 feature, referrer, device, language, uid),
            )
        return {"recorded": True}

    # -- read (admin aggregation lives in analytics_admin.py) ----------

    def count(self) -> int:
        with self._connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM analytics_events").fetchone()[0]

    def purge_older_than(self, days: int = RETENTION_DAYS) -> int:
        """Retention enforcement: delete events older than ``days``.
        Returns the number of deleted rows."""
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat() + "Z"
        with self._lock, self._connect() as conn:
            cur = conn.execute("DELETE FROM analytics_events WHERE ts < ?", (cutoff,))
            return cur.rowcount

    def delete_session(self, session_id: str) -> int:
        """Delete every event of one pseudonymous session (erasure
        capability). The raw session id is hashed the same way as at
        write time, so it can be found without ever being stored."""
        digest = hash_token(session_id)
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM analytics_events WHERE session_hash = ?", (digest,))
            return cur.rowcount


# ---------------------------------------------------------------------------
# Ingest API (Flask blueprint, registered in create_app())
# ---------------------------------------------------------------------------

from flask import Blueprint, jsonify, request  # noqa: E402

from .auth_api import require_role  # noqa: E402  (no module-level cycle)

analytics_bp = Blueprint("product_analytics", __name__, url_prefix="/api/v2")


@analytics_bp.post("/analytics/event")
def analytics_event():
    """First-party product event ingest.

    Accepts one event object or ``{"events": [...]}`` (max 20). Fields
    outside the whitelist are dropped; unknown event names are rejected.
    Pseudonymous browsing events only — account-conversion events are
    recorded server-side where the account id legitimately exists (see
    ``auth_api.verify``), so this endpoint never accepts user identity.
    Rate-limited per IP like every public POST. Returns 202.
    """
    from .auth_api import _rate  # shared per-IP limiter

    if not _rate("v2analytics", 60, 60.0):
        return jsonify({"error": "Rate limit exceeded", "status": 429}), 429

    data = request.get_json(silent=True) or {}
    events = data.get("events") if isinstance(data.get("events"), list) else [data]
    events = events[:_MAX_BATCH]

    store = AnalyticsStore()
    recorded = 0
    for raw in events:
        if not isinstance(raw, dict):
            continue
        event = {k: raw.get(k) for k in _ALLOWED_FIELDS if k in raw}
        if store.record(event).get("recorded"):
            recorded += 1
    return jsonify({"recorded": recorded}), 202


# ---------------------------------------------------------------------------
# Admin aggregates (internal only — never public)
# ---------------------------------------------------------------------------

_FUNNEL = [
    "page_view", "location_analyzed", "solution_viewed", "report_generated",
    "account_created", "alert_created", "sms_enabled", "subscription_started",
    "contact_started",
]


@analytics_bp.get("/admin/analytics/summary")
@require_role("admin")
def admin_analytics_summary():
    """Aggregate product metrics. Admin-only; counts, never row-level data."""
    store = AnalyticsStore()
    with store._connect() as conn:
        total = conn.execute("SELECT COUNT(*) FROM analytics_events").fetchone()[0]
        sessions = conn.execute(
            "SELECT COUNT(DISTINCT session_hash) FROM analytics_events "
            "WHERE session_hash IS NOT NULL").fetchone()[0]
        funnel = {}
        for name in _FUNNEL:
            funnel[name] = conn.execute(
                "SELECT COUNT(*) FROM analytics_events WHERE event = ?",
                (name,)).fetchone()[0]
        by_event = dict(conn.execute(
            "SELECT event, COUNT(*) FROM analytics_events GROUP BY event "
            "ORDER BY COUNT(*) DESC").fetchall())
    return jsonify({
        "total_events": total,
        "distinct_pseudonymous_sessions": sessions,
        "by_event": by_event,
        "funnel": funnel,
        "note": "Aggregates only. Sessions are HMAC-hashed pseudonyms; no "
                "row-level export exists.",
    })


@analytics_bp.get("/admin/analytics/top")
@require_role("admin")
def admin_analytics_top():
    """Top values for a dimension: page | hazard | referrer | feature."""
    dimension = (request.args.get("dimension") or "page").strip()
    if dimension not in ("page", "hazard", "referrer", "feature"):
        return jsonify({"error": "dimension must be one of page|hazard|referrer|feature",
                        "status": 400}), 400
    try:
        limit = min(int(request.args.get("limit", 20)), 100)
    except ValueError:
        limit = 20
    store = AnalyticsStore()
    with store._connect() as conn:
        rows = conn.execute(
            f"SELECT {dimension}, COUNT(*) AS n FROM analytics_events "
            f"WHERE {dimension} IS NOT NULL GROUP BY {dimension} "
            f"ORDER BY n DESC LIMIT ?", (limit,)).fetchall()
    return jsonify({"dimension": dimension,
                    "top": [{"value": r[0], "count": r[1]} for r in rows]})


@analytics_bp.get("/admin/analytics/daily")
@require_role("admin")
def admin_analytics_daily():
    """Daily event counts for the last N days (max 90)."""
    try:
        days = min(int(request.args.get("days", 30)), 90)
    except ValueError:
        days = 30
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat() + "Z"
    store = AnalyticsStore()
    with store._connect() as conn:
        rows = conn.execute(
            "SELECT substr(ts, 1, 10) AS day, COUNT(*) FROM analytics_events "
            "WHERE ts >= ? GROUP BY day ORDER BY day", (cutoff,)).fetchall()
    return jsonify({"days": [{"day": r[0], "count": r[1]} for r in rows]})
