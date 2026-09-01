"""
Talaix Stripe billing blueprint (Stage 7).

Env-driven, no secrets in code. When the Stripe env vars are absent the
endpoints return honest 503 / billing_enabled=false so dev/tests keep running.

Endpoints (all under ``/api/v2/billing``):

    GET  /config                     public config + price catalog
    POST /checkout                   start a subscription checkout session
    POST /checkout/report            start a one-time report purchase
    POST /portal                     customer portal for existing subscribers
    POST /webhook                   Stripe event receiver (idempotent)
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from datetime import datetime
from typing import Dict, List, Optional

from flask import Blueprint, current_app, g, jsonify, request

from .accounts import ROLE_RANK, DEFAULT_ROLE, UserStore
from .auth_api import current_user, require_role

log = logging.getLogger(__name__)

billing_bp = Blueprint("billing", __name__, url_prefix="/api/v2/billing")

_PRICE_KEYS = {
    "professional_monthly",
    "professional_yearly",
    "business_monthly",
    "business_yearly",
    "seat_monthly",
    "report_decision",
    "report_scientific",
}

_TIER_ROLES = {
    "professional": "professional",
    "business": "business",
}

_REPORT_KINDS = {
    "decision": "report_decision",
    "scientific": "report_scientific",
}

_STRIPE_STATUS_MAP = {
    "active": "active",
    "trialing": "active",
    "past_due": "past_due",
    "canceled": "canceled",
    "unpaid": "canceled",
    "incomplete": "past_due",
    "incomplete_expired": "canceled",
}


def _utcnow() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _stripe_secret() -> Optional[str]:
    return os.environ.get("STRIPE_SECRET_KEY") or None


def _stripe_publishable() -> Optional[str]:
    return os.environ.get("STRIPE_PUBLISHABLE_KEY") or None


def _stripe_webhook_secret() -> Optional[str]:
    return os.environ.get("STRIPE_WEBHOOK_SECRET") or None


def _public_base_url() -> str:
    return os.environ.get("TALAIX_PUBLIC_BASE_URL", "https://talaix.com").rstrip("/")


def _tax_enabled() -> bool:
    return os.environ.get("STRIPE_TAX_ENABLED", "").strip().lower() in ("1", "true", "yes")


def billing_enabled() -> bool:
    """True when the operator has configured Stripe (secret key present)."""
    return bool(_stripe_secret())


def _config_path() -> str:
    return os.path.join(
        os.path.dirname(__file__), "..", "..", "config", "stripe_prices.json"
    )


def _load_prices() -> Dict[str, Dict]:
    """Load the committed price catalog. Missing file = empty catalog."""
    path = _config_path()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items() if k in _PRICE_KEYS}


def _price_id(key: str) -> Optional[str]:
    price = _load_prices().get(key) or {}
    pid = (price.get("price_id") or "").strip()
    return pid or None


def _err(message: str, status: int, **extra):
    payload = {"error": message, "status": status}
    payload.update(extra)
    return jsonify(payload), status


# ---------------------------------------------------------------------------
# Billing data store (additive SQLite tables on the shared cache DB)
# ---------------------------------------------------------------------------


class BillingStore:
    """SQLite-backed store for billing events, Stripe customers and purchases."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path = db_path or UserStore().db_path
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path, timeout=10.0)

    def _init_db(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS billing_events (
                    stripe_event_id TEXT PRIMARY KEY,
                    processed_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS billing_customers (
                    user_id INTEGER PRIMARY KEY,
                    stripe_customer_id TEXT UNIQUE NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS billing_purchases (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    stripe_checkout_session_id TEXT UNIQUE NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )

    def record_event(self, stripe_event_id: str) -> bool:
        """
        Insert a Stripe event idempotently. Returns True when the event was
        newly recorded, False when it already existed.
        """
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO billing_events (stripe_event_id, processed_at)"
                " VALUES (?, ?)",
                (stripe_event_id, _utcnow()),
            )
            return cur.rowcount > 0

    def forget_event(self, stripe_event_id: str) -> None:
        """Drop a recorded event id so a Stripe redelivery is reprocessed."""
        with self._lock, self._connect() as conn:
            conn.execute(
                "DELETE FROM billing_events WHERE stripe_event_id = ?",
                (stripe_event_id,),
            )

    def set_customer(self, user_id: int, stripe_customer_id: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO billing_customers"
                " (user_id, stripe_customer_id, created_at) VALUES (?, ?, ?)",
                (user_id, stripe_customer_id, _utcnow()),
            )

    def get_customer(self, user_id: int) -> Optional[str]:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT stripe_customer_id FROM billing_customers WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        return row[0] if row else None

    def record_purchase(
        self,
        user_id: int,
        kind: str,
        stripe_checkout_session_id: str,
        status: str = "completed",
    ) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO billing_purchases"
                " (user_id, kind, stripe_checkout_session_id, status, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (user_id, kind, stripe_checkout_session_id, status, _utcnow()),
            )


# ---------------------------------------------------------------------------
# UserStore extensions used by webhooks
# ---------------------------------------------------------------------------


def _subscription_period_end(subscription: Dict) -> Optional[str]:
    """
    Tolerant extraction of the current period end from a Stripe subscription
    object. Never invents a date.
    """
    raw = None
    if isinstance(subscription, dict):
        raw = subscription.get("current_period_end")
        if raw is None:
            items = subscription.get("items") or {}
            data = items.get("data") or []
            if data and isinstance(data[0], dict):
                raw = data[0].get("current_period_end")
    if raw is None:
        return None
    try:
        ts = int(raw)
        return datetime.utcfromtimestamp(ts).isoformat() + "Z"
    except (TypeError, ValueError):
        return None


def _role_for_tier(tier: Optional[str]) -> Optional[str]:
    return _TIER_ROLES.get((tier or "").lower())


def _promote_user_for_tier(store: UserStore, user_id: int, tier: str) -> None:
    role = _role_for_tier(tier)
    if role is None:
        return
    user = store.get_user(user_id)
    if user is None:
        return
    if ROLE_RANK.get(user["role"], 0) < ROLE_RANK.get(role, 0):
        with store._lock, store._connect() as conn:
            conn.execute("UPDATE users SET role = ? WHERE id = ?", (role, user_id))
        store.audit(user_id, "role_promotion", target=role,
                    meta={"source": "stripe_checkout", "tier": tier})


def _demote_if_subscription_role(store: UserStore, user_id: int, tier: str) -> None:
    """
    Demote the user to registered only when their current role is exactly the
    paid tier this subscription granted. Operator/admin roles are never touched.
    """
    role = _role_for_tier(tier)
    if role is None:
        return
    user = store.get_user(user_id)
    if user is None:
        return
    if user["role"] != role:
        return
    with store._lock, store._connect() as conn:
        conn.execute("UPDATE users SET role = ? WHERE id = ?", (DEFAULT_ROLE, user_id))
    store.audit(user_id, "role_demotion", target=DEFAULT_ROLE,
                meta={"source": "stripe_subscription_deleted", "tier": tier})


def _upsert_subscription_from_stripe(
    store: UserStore,
    user_id: int,
    tier: str,
    stripe_subscription_id: str,
    status: str,
    ends_at: Optional[str],
) -> None:
    started = _utcnow()
    with store._lock, store._connect() as conn:
        row = conn.execute(
            "SELECT id FROM subscriptions WHERE external_ref = ?",
            (stripe_subscription_id,),
        ).fetchone()
        if row is not None:
            conn.execute(
                "UPDATE subscriptions SET tier = ?, status = ?, ends_at = ?"
                " WHERE id = ?",
                (tier, status, ends_at, row[0]),
            )
        else:
            conn.execute(
                "INSERT INTO subscriptions"
                " (owner_user_id, tier, status, started_at, ends_at, external_ref)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (user_id, tier, status, started, ends_at, stripe_subscription_id),
            )


def _subscription_by_external_ref(store: UserStore, external_ref: str) -> Optional[Dict]:
    with store._lock, store._connect() as conn:
        row = conn.execute(
            "SELECT id, owner_user_id, tier, status, started_at, ends_at, external_ref"
            " FROM subscriptions WHERE external_ref = ?",
            (external_ref,),
        ).fetchone()
    if row is None:
        return None
    return {
        "id": row[0], "owner_user_id": row[1], "tier": row[2], "status": row[3],
        "started_at": row[4], "ends_at": row[5], "external_ref": row[6],
    }


# ---------------------------------------------------------------------------
# Stripe client helpers
# ---------------------------------------------------------------------------


def _stripe_module():
    """Lazy import of the Stripe SDK so the app starts when it is absent."""
    import stripe

    return stripe


def _stripe_client():
    stripe = _stripe_module()
    stripe.api_key = _stripe_secret()
    return stripe


# ---------------------------------------------------------------------------
# Public endpoints
# ---------------------------------------------------------------------------


@billing_bp.get("/config")
def billing_config():
    """Public billing configuration and price catalog."""
    prices = _load_prices()
    products = {}
    for key in _PRICE_KEYS:
        entry = prices.get(key) or {}
        try:
            amount = float(entry.get("amount_eur", 0))
        except (TypeError, ValueError):
            amount = 0.0
        products[key] = {
            "amount_eur": amount,
            "interval": entry.get("interval") or "one_time",
        }
    enabled = billing_enabled()
    return jsonify({
        "billing_enabled": enabled,
        "publishable_key": _stripe_publishable() if enabled else None,
        "products": products,
    })


@billing_bp.post("/checkout")
@require_role("registered")
def checkout():
    """Start a Stripe Checkout session for a Professional/Business subscription."""
    if not billing_enabled():
        return _err("Billing is not configured", 503)
    data = request.get_json(silent=True) or {}
    tier = (data.get("tier") or "").strip().lower()
    interval = (data.get("interval") or "").strip().lower()
    if tier not in ("professional", "business"):
        return _err("tier must be 'professional' or 'business'", 400)
    if interval not in ("monthly", "yearly"):
        return _err("interval must be 'monthly' or 'yearly'", 400)
    price_key = f"{tier}_{interval}"
    price_id = _price_id(price_key)
    if not price_id:
        return _err(f"Price not configured for {price_key}", 503)

    user = g.current_user
    stripe = _stripe_client()
    base = _public_base_url()
    params = {
        "mode": "subscription",
        "line_items": [{"price": price_id, "quantity": 1}],
        "client_reference_id": str(user["id"]),
        "customer_email": user["email"],
        "metadata": {
            "talaix_user_id": str(user["id"]),
            "talaix_tier": tier,
        },
        "success_url": f"{base}/account.html?subscribed=1",
        "cancel_url": f"{base}/account.html?checkout=cancelled",
    }
    if _tax_enabled():
        params["automatic_tax"] = {"enabled": True}
    session = stripe.checkout.Session.create(**params)
    return jsonify({"url": session.url})


@billing_bp.post("/checkout/report")
@require_role("registered")
def checkout_report():
    """Start a one-time Checkout session for a pay-per-use report."""
    if not billing_enabled():
        return _err("Billing is not configured", 503)
    data = request.get_json(silent=True) or {}
    kind = (data.get("kind") or "").strip().lower()
    if kind not in _REPORT_KINDS:
        return _err("kind must be 'decision' or 'scientific'", 400)
    price_key = _REPORT_KINDS[kind]
    price_id = _price_id(price_key)
    if not price_id:
        return _err(f"Price not configured for {price_key}", 503)

    user = g.current_user
    stripe = _stripe_client()
    base = _public_base_url()
    params = {
        "mode": "payment",
        "line_items": [{"price": price_id, "quantity": 1}],
        "client_reference_id": str(user["id"]),
        "customer_email": user["email"],
        "metadata": {
            "talaix_user_id": str(user["id"]),
            "talaix_kind": f"report_{kind}",
        },
        "success_url": f"{base}/account.html?purchased=report&subscribed=1",
        "cancel_url": f"{base}/account.html?checkout=cancelled",
    }
    if _tax_enabled():
        params["automatic_tax"] = {"enabled": True}
    session = stripe.checkout.Session.create(**params)
    return jsonify({"url": session.url})


@billing_bp.post("/portal")
@require_role("registered")
def customer_portal():
    """Create a Stripe customer portal session for the signed-in user."""
    if not billing_enabled():
        return _err("Billing is not configured", 503)
    user = g.current_user
    customer_id = BillingStore().get_customer(user["id"])
    if not customer_id:
        return _err("No Stripe customer found", 404)
    stripe = _stripe_client()
    base = _public_base_url()
    session = stripe.billing_portal.Session.create(
        customer=customer_id,
        return_url=f"{base}/account.html",
    )
    return jsonify({"url": session.url})


# ---------------------------------------------------------------------------
# Webhook
# ---------------------------------------------------------------------------


@billing_bp.post("/webhook")
def webhook():
    """Receive and idempotently process Stripe webhook events."""
    secret = _stripe_webhook_secret()
    if not secret:
        return _err("Webhook not configured", 503)

    payload = request.get_data(as_text=True)
    sig_header = request.headers.get("Stripe-Signature", "")
    stripe = _stripe_module()
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, secret)
    except stripe.error.SignatureVerificationError:
        return _err("Invalid signature", 400)
    except ValueError:
        return _err("Invalid payload", 400)
    if not isinstance(event, dict):
        # stripe-python >= 15 returns an Event object, not a dict.
        event = event.to_dict()

    event_id = event.get("id")
    if not event_id:
        return _err("Missing event id", 400)

    billing_store = BillingStore()
    if not billing_store.record_event(event_id):
        return jsonify({"status": "duplicate"}), 200

    data_obj = event.get("data", {}).get("object", {})
    event_type = event.get("type", "")

    try:
        if event_type == "checkout.session.completed":
            _handle_checkout_session_completed(data_obj)
        elif event_type == "customer.subscription.updated":
            _handle_subscription_updated(data_obj)
        elif event_type == "customer.subscription.deleted":
            _handle_subscription_deleted(data_obj)
        elif event_type == "invoice.payment_succeeded":
            _handle_invoice_payment(data_obj, succeeded=True)
        elif event_type == "invoice.payment_failed":
            _handle_invoice_payment(data_obj, succeeded=False)
        else:
            return jsonify({"status": "ignored"}), 200
    except Exception:
        # A handler that fails after the event was recorded must not let the
        # Stripe redelivery be swallowed as a duplicate: forget the event and
        # let the error surface so Stripe retries with backoff.
        billing_store.forget_event(event_id)
        raise

    return jsonify({"status": "ok"}), 200


def _handle_checkout_session_completed(session: Dict) -> None:
    mode = session.get("mode")
    user_id_raw = session.get("metadata", {}).get("talaix_user_id") or session.get("client_reference_id")
    try:
        user_id = int(user_id_raw)
    except (TypeError, ValueError):
        return

    store = UserStore()
    user = store.get_user(user_id)
    if user is None:
        return

    customer_id = session.get("customer")
    if customer_id:
        BillingStore().set_customer(user_id, str(customer_id))

    if mode == "subscription":
        tier = session.get("metadata", {}).get("talaix_tier")
        if tier not in ("professional", "business"):
            return
        stripe_sub_id = session.get("subscription")
        if not stripe_sub_id:
            return
        stripe = _stripe_client()
        subscription = stripe.Subscription.retrieve(stripe_sub_id)
        if not isinstance(subscription, dict):
            # stripe-python >= 15 returns a Subscription object, not a dict.
            subscription = subscription.to_dict()
        status = _STRIPE_STATUS_MAP.get(subscription.get("status"), "active")
        ends_at = _subscription_period_end(subscription)
        _upsert_subscription_from_stripe(
            store, user_id, tier, stripe_sub_id, status, ends_at)
        _promote_user_for_tier(store, user_id, tier)
        # Confirmation email is best-effort: a paid activation must never
        # fail (and be retried) because SMTP hiccupped. Failures are logged.
        try:
            from . import mailer

            mailer.send_mail(
                user["email"],
                "subscription_confirmation_paid",
                {
                    "display_name": user.get("display_name") or "",
                    "tier": tier,
                    "status": status,
                    "started_at": _utcnow(),
                },
            )
        except Exception:
            log.warning(
                "subscription confirmation email failed for user %s",
                user_id, exc_info=True)
    elif mode == "payment":
        kind = session.get("metadata", {}).get("talaix_kind", "")
        if kind.startswith("report_"):
            BillingStore().record_purchase(
                user_id,
                kind,
                session.get("id", ""),
                status="completed",
            )


def _handle_subscription_updated(subscription: Dict) -> None:
    stripe_sub_id = subscription.get("id")
    if not stripe_sub_id:
        return
    store = UserStore()
    sub = _subscription_by_external_ref(store, stripe_sub_id)
    if sub is None:
        return
    status = _STRIPE_STATUS_MAP.get(subscription.get("status"), sub["status"])
    ends_at = _subscription_period_end(subscription)
    metadata_tier = subscription.get("metadata", {}).get("talaix_tier")
    tier = metadata_tier if metadata_tier in ("professional", "business") else sub["tier"]
    with store._lock, store._connect() as conn:
        conn.execute(
            "UPDATE subscriptions SET tier = ?, status = ?, ends_at = ? WHERE id = ?",
            (tier, status, ends_at, sub["id"]),
        )
    if tier != sub["tier"]:
        # Sync the role to match the new paid tier, both for upgrades and
        # downgrades, but never touch operator/admin/government roles.
        user = store.get_user(sub["owner_user_id"])
        protected = {"admin", "municipality", "government"}
        if user and user["role"] not in protected and tier in _TIER_ROLES:
            new_role = _TIER_ROLES[tier]
            with store._lock, store._connect() as conn:
                conn.execute("UPDATE users SET role = ? WHERE id = ?",
                             (new_role, sub["owner_user_id"]))
            store.audit(sub["owner_user_id"], "role_sync", target=new_role,
                        meta={"source": "stripe_subscription_updated",
                              "previous_tier": sub["tier"], "tier": tier})


def _handle_subscription_deleted(subscription: Dict) -> None:
    stripe_sub_id = subscription.get("id")
    if not stripe_sub_id:
        return
    store = UserStore()
    sub = _subscription_by_external_ref(store, stripe_sub_id)
    if sub is None:
        return
    ended = _utcnow()
    with store._lock, store._connect() as conn:
        conn.execute(
            "UPDATE subscriptions SET status = ?, ends_at = ? WHERE id = ?",
            ("canceled", ended, sub["id"]),
        )
    _demote_if_subscription_role(store, sub["owner_user_id"], sub["tier"])


def _handle_invoice_payment(invoice: Dict, succeeded: bool) -> None:
    stripe_sub_id = invoice.get("subscription")
    if not stripe_sub_id:
        return
    store = UserStore()
    sub = _subscription_by_external_ref(store, stripe_sub_id)
    if sub is None:
        return
    status = "active" if succeeded else "past_due"
    # We do not have a period end on the invoice itself here; keep the existing
    # ends_at unless a subscription object is available.
    ends_at = sub["ends_at"]
    with store._lock, store._connect() as conn:
        conn.execute(
            "UPDATE subscriptions SET status = ?, ends_at = ? WHERE id = ?",
            (status, ends_at, sub["id"]),
        )
