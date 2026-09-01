"""
Tests for the Stripe billing blueprint.

All Stripe SDK calls are monkey-patched; no network traffic and no real keys.
The catalog uses the committed ``config/stripe_prices.json`` (empty price ids
in Git) so the tests exercise price lookup by key.
"""

import email as email_lib
import email.policy
import json
import re
import sqlite3
from types import SimpleNamespace

import pytest

from src.dashboard.accounts import UserStore
from src.dashboard.api import create_app


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """Isolated DB + outbox + billing env per test."""
    db_path = tmp_path / "billing.sqlite3"
    monkeypatch.setenv("HYDRASHIELD_CACHE_DB", str(db_path))
    monkeypatch.setenv("HYDRASHIELD_OUTBOX_DIR", str(tmp_path / "outbox"))
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_12345")
    monkeypatch.setenv("STRIPE_PUBLISHABLE_KEY", "pk_test_12345")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test_12345")
    monkeypatch.setenv("TALAIX_PUBLIC_BASE_URL", "https://talaix.test")
    for var in ("SMTP_HOST", "SMTP_USER"):
        monkeypatch.delenv(var, raising=False)
    import src.dashboard.cache as cache_mod
    import src.dashboard.api as api_module

    monkeypatch.setattr(cache_mod, "_default_cache", None)
    api_module._rate_limiter._hits.clear()
    yield {"db": db_path, "outbox": tmp_path / "outbox"}
    api_module._rate_limiter._hits.clear()


@pytest.fixture()
def client(env):
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture(autouse=True)
def catalog_prices(monkeypatch):
    """Provide non-empty Stripe price ids for the committed catalog keys."""
    import src.dashboard.billing as billing_mod

    prices = {
        key: {"price_id": f"price_{key}", "amount_eur": amount, "interval": interval}
        for key, amount, interval in [
            ("professional_monthly", 49, "month"),
            ("professional_yearly", 490, "year"),
            ("business_monthly", 249, "month"),
            ("business_yearly", 2490, "year"),
            ("seat_monthly", 25, "month"),
            ("report_decision", 19, "one_time"),
            ("report_scientific", 39, "one_time"),
        ]
    }
    monkeypatch.setattr(billing_mod, "_load_prices", lambda: prices)
    return prices


@pytest.fixture()
def fake_stripe(monkeypatch):
    """Replace the Stripe SDK with deterministic fakes."""
    calls = {
        "checkout_create": [],
        "portal_create": [],
        "subscription_retrieve": [],
    }

    class SignatureVerificationError(Exception):
        pass

    class FakeCheckoutSessions:
        @staticmethod
        def create(**kwargs):
            calls["checkout_create"].append(kwargs)
            return SimpleNamespace(url="https://checkout.stripe.test/session")

    class FakePortalSessions:
        @staticmethod
        def create(**kwargs):
            calls["portal_create"].append(kwargs)
            return SimpleNamespace(url="https://billing.stripe.test/portal")

    class FakeStripeObject:
        """Mimics stripe-python >= 15: API resources are not dicts; they
        require .to_dict() (calling .get on them raises AttributeError)."""

        def __init__(self, payload):
            self._payload = payload

        def to_dict(self):
            return self._payload

    class FakeSubscription:
        @staticmethod
        def retrieve(sub_id):
            calls["subscription_retrieve"].append(sub_id)
            return FakeStripeObject({
                "id": sub_id,
                "status": "active",
                "current_period_end": 1893456000,
                "items": {"data": [{"current_period_end": 1893456000}]},
            })

    class FakeWebhook:
        @staticmethod
        def construct_event(payload, sig_header, secret):
            if sig_header == "bad-sig":
                raise SignatureVerificationError("bad signature")
            return FakeStripeObject(json.loads(payload))

    fake_module = SimpleNamespace(
        error=SimpleNamespace(SignatureVerificationError=SignatureVerificationError),
        checkout=SimpleNamespace(Session=FakeCheckoutSessions),
        billing_portal=SimpleNamespace(Session=FakePortalSessions),
        Subscription=FakeSubscription,
        Webhook=FakeWebhook,
    )
    monkeypatch.setattr("src.dashboard.billing._stripe_module", lambda: fake_module)
    return calls


def _auth_headers(client, env, email="user@example.org"):
    resp = client.post(
        "/api/v2/auth/register",
        json={"email": email, "password": "correct horse battery", "consent": True},
    )
    assert resp.status_code == 201, resp.get_json()
    files = sorted(env["outbox"].glob("*_email_verification_*.eml"))
    msg = email_lib.message_from_string(
        files[-1].read_text(encoding="utf-8"), policy=email_lib.policy.default)
    token = re.search(r"token=([A-Za-z0-9_\-]+)",
                      msg.get_body(("plain",)).get_content()).group(1)
    resp = client.get(f"/api/v2/auth/verify?token={token}")
    assert resp.status_code == 200, resp.get_json()
    return {"Authorization": f"Bearer {resp.get_json()['session_token']}"}


def _role(env, email):
    conn = sqlite3.connect(str(env["db"]))
    row = conn.execute("SELECT role FROM users WHERE email = ?", (email,)).fetchone()
    conn.close()
    return row[0]


def _webhook(client, event_type, data_obj, event_id="evt_1"):
    payload = json.dumps({"id": event_id, "type": event_type, "data": {"object": data_obj}})
    return client.post(
        "/api/v2/billing/webhook",
        data=payload,
        headers={"Stripe-Signature": "valid-sig", "Content-Type": "text/plain"},
    )


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def test_billing_config_public_and_shows_catalog(client, env):
    resp = client.get("/api/v2/billing/config")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["billing_enabled"] is True
    assert body["publishable_key"] == "pk_test_12345"
    products = body["products"]
    assert products["professional_monthly"]["amount_eur"] == 49
    assert products["professional_monthly"]["interval"] == "month"
    assert products["report_decision"]["interval"] == "one_time"


def test_billing_config_disabled_without_secret(client, env, monkeypatch):
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    resp = client.get("/api/v2/billing/config")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["billing_enabled"] is False
    assert body["publishable_key"] is None


# ---------------------------------------------------------------------------
# Checkout
# ---------------------------------------------------------------------------


def test_checkout_requires_auth(client):
    assert client.post("/api/v2/billing/checkout",
                       json={"tier": "professional", "interval": "monthly"}).status_code == 401


def test_checkout_rejects_invalid_tier_or_interval(client, env):
    headers = _auth_headers(client, env)
    assert client.post("/api/v2/billing/checkout",
                       headers=headers, json={"tier": "enterprise", "interval": "monthly"}
                       ).status_code == 400
    assert client.post("/api/v2/billing/checkout",
                       headers=headers, json={"tier": "professional", "interval": "daily"}
                       ).status_code == 400


def test_checkout_builds_session_with_correct_params(client, env, fake_stripe):
    headers = _auth_headers(client, env, email="checkout@example.org")
    resp = client.post(
        "/api/v2/billing/checkout",
        headers=headers,
        json={"tier": "professional", "interval": "yearly"},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["url"] == "https://checkout.stripe.test/session"

    assert len(fake_stripe["checkout_create"]) == 1
    params = fake_stripe["checkout_create"][0]
    assert params["mode"] == "subscription"
    assert params["line_items"] == [{"price": "price_professional_yearly", "quantity": 1}]
    assert params["client_reference_id"] == "1"
    assert params["customer_email"] == "checkout@example.org"
    assert params["metadata"]["talaix_tier"] == "professional"
    assert params["success_url"] == "https://talaix.test/account.html?subscribed=1"
    assert params["cancel_url"] == "https://talaix.test/account.html?checkout=cancelled"


def test_checkout_503_when_price_not_configured(client, env, monkeypatch):
    """If the catalog entry has an empty price_id, checkout returns 503."""
    headers = _auth_headers(client, env)
    import src.dashboard.billing as billing_mod

    original_load = billing_mod._load_prices

    def _empty_prices():
        prices = dict(original_load())
        prices["professional_monthly"] = {**prices.get("professional_monthly", {}),
                                          "price_id": ""}
        return prices

    monkeypatch.setattr(billing_mod, "_load_prices", _empty_prices)
    resp = client.post(
        "/api/v2/billing/checkout",
        headers=headers,
        json={"tier": "professional", "interval": "monthly"},
    )
    assert resp.status_code == 503


def test_checkout_report_requires_auth(client):
    assert client.post("/api/v2/billing/checkout/report",
                       json={"kind": "decision"}).status_code == 401


def test_checkout_report_builds_payment_session(client, env, fake_stripe):
    headers = _auth_headers(client, env)
    resp = client.post(
        "/api/v2/billing/checkout/report",
        headers=headers,
        json={"kind": "scientific"},
    )
    assert resp.status_code == 200
    params = fake_stripe["checkout_create"][0]
    assert params["mode"] == "payment"
    assert params["metadata"]["talaix_kind"] == "report_scientific"


# ---------------------------------------------------------------------------
# Webhook
# ---------------------------------------------------------------------------


def test_webhook_rejects_bad_signature(client):
    payload = json.dumps({"id": "evt_bad", "type": "checkout.session.completed", "data": {"object": {}}})
    resp = client.post(
        "/api/v2/billing/webhook",
        data=payload,
        headers={"Stripe-Signature": "bad-sig", "Content-Type": "text/plain"},
    )
    assert resp.status_code == 400
    assert "signature" in resp.get_json()["error"].lower()


def test_webhook_ignores_unknown_event_types(client, env, fake_stripe):
    resp = _webhook(client, "charge.succeeded", {"id": "ch_1"}, event_id="evt_unknown")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "ignored"


def test_webhook_checkout_completed_promotes_and_records_subscription(client, env, fake_stripe):
    headers = _auth_headers(client, env, email="paid@example.org")
    # Seed the Stripe customer id via a portal-like lookup is unnecessary;
    # the webhook stores the customer from the session.
    session_obj = {
        "id": "cs_1",
        "mode": "subscription",
        "customer": "cus_1",
        "client_reference_id": "1",
        "subscription": "sub_1",
        "metadata": {"talaix_user_id": "1", "talaix_tier": "business"},
    }
    resp = _webhook(client, "checkout.session.completed", session_obj, event_id="evt_complete")
    assert resp.status_code == 200

    store = UserStore(str(env["db"]))
    sub = store.get_active_subscription(1)
    assert sub is not None
    assert sub["tier"] == "business"
    assert sub["external_ref"] == "sub_1"

    conn = sqlite3.connect(str(env["db"]))
    customer = conn.execute(
        "SELECT stripe_customer_id FROM billing_customers WHERE user_id = 1"
    ).fetchone()
    conn.close()
    assert customer[0] == "cus_1"

    assert _role(env, "paid@example.org") == "business"

    # Confirmation email sent.
    files = sorted(env["outbox"].glob("*subscription_confirmation*.eml"))
    assert len(files) == 1


def test_webhook_idempotent_event_replay(client, env, fake_stripe):
    headers = _auth_headers(client, env, email="idemp@example.org")
    session_obj = {
        "id": "cs_2",
        "mode": "subscription",
        "customer": "cus_2",
        "client_reference_id": "1",
        "subscription": "sub_2",
        "metadata": {"talaix_user_id": "1", "talaix_tier": "professional"},
    }
    assert _webhook(client, "checkout.session.completed", session_obj,
                    event_id="evt_idemp").status_code == 200
    assert _webhook(client, "checkout.session.completed", session_obj,
                    event_id="evt_idemp").status_code == 200

    # Only one subscription row and one confirmation email.
    conn = sqlite3.connect(str(env["db"]))
    count = conn.execute(
        "SELECT COUNT(*) FROM subscriptions WHERE external_ref = ?", ("sub_2",)
    ).fetchone()[0]
    conn.close()
    assert count == 1
    assert len(sorted(env["outbox"].glob("*subscription_confirmation*.eml"))) == 1


def test_webhook_subscription_deleted_demotes_to_registered(client, env, fake_stripe):
    headers = _auth_headers(client, env, email="cancel@example.org")
    # Activate first.
    session_obj = {
        "id": "cs_3",
        "mode": "subscription",
        "customer": "cus_3",
        "client_reference_id": "1",
        "subscription": "sub_3",
        "metadata": {"talaix_user_id": "1", "talaix_tier": "professional"},
    }
    assert _webhook(client, "checkout.session.completed", session_obj,
                    event_id="evt_activate").status_code == 200
    assert _role(env, "cancel@example.org") == "professional"

    # Delete the subscription.
    resp = _webhook(client, "customer.subscription.deleted",
                    {"id": "sub_3"}, event_id="evt_delete")
    assert resp.status_code == 200
    assert _role(env, "cancel@example.org") == "registered"

    conn = sqlite3.connect(str(env["db"]))
    row = conn.execute(
        "SELECT status, ends_at FROM subscriptions WHERE external_ref = ?", ("sub_3",)
    ).fetchone()
    conn.close()
    assert row[0] == "canceled"
    assert row[1] is not None


def test_webhook_subscription_deleted_leaves_admin_role(client, env, fake_stripe):
    headers = _auth_headers(client, env, email="admin@example.org")
    conn = sqlite3.connect(str(env["db"]))
    conn.execute("UPDATE users SET role = 'admin' WHERE email = ?", ("admin@example.org",))
    conn.commit()
    conn.close()

    session_obj = {
        "id": "cs_4",
        "mode": "subscription",
        "customer": "cus_4",
        "client_reference_id": "1",
        "subscription": "sub_4",
        "metadata": {"talaix_user_id": "1", "talaix_tier": "business"},
    }
    assert _webhook(client, "checkout.session.completed", session_obj,
                    event_id="evt_admin_sub").status_code == 200
    # Operator/admin role is preserved even while the subscription exists.
    assert _role(env, "admin@example.org") == "admin"

    _webhook(client, "customer.subscription.deleted", {"id": "sub_4"},
             event_id="evt_admin_del")
    assert _role(env, "admin@example.org") == "admin"


def test_webhook_invoice_payment_failed_marks_past_due(client, env, fake_stripe):
    headers = _auth_headers(client, env, email="pastdue@example.org")
    session_obj = {
        "id": "cs_5",
        "mode": "subscription",
        "customer": "cus_5",
        "client_reference_id": "1",
        "subscription": "sub_5",
        "metadata": {"talaix_user_id": "1", "talaix_tier": "professional"},
    }
    _webhook(client, "checkout.session.completed", session_obj, event_id="evt_pd_active")

    _webhook(client, "invoice.payment_failed", {"subscription": "sub_5"},
             event_id="evt_pd_fail")
    conn = sqlite3.connect(str(env["db"]))
    status = conn.execute(
        "SELECT status FROM subscriptions WHERE external_ref = ?", ("sub_5",)
    ).fetchone()[0]
    conn.close()
    assert status == "past_due"


# ---------------------------------------------------------------------------
# Customer portal
# ---------------------------------------------------------------------------


def test_portal_requires_auth(client):
    assert client.post("/api/v2/billing/portal").status_code == 401


def test_portal_404_without_customer(client, env, fake_stripe):
    headers = _auth_headers(client, env)
    resp = client.post("/api/v2/billing/portal", headers=headers)
    assert resp.status_code == 404


def test_portal_returns_url_with_customer(client, env, fake_stripe):
    headers = _auth_headers(client, env, email="portal@example.org")
    from src.dashboard.billing import BillingStore

    BillingStore(str(env["db"])).set_customer(1, "cus_portal")
    resp = client.post("/api/v2/billing/portal", headers=headers)
    assert resp.status_code == 200
    assert resp.get_json()["url"] == "https://billing.stripe.test/portal"
    assert fake_stripe["portal_create"][0]["customer"] == "cus_portal"
    assert fake_stripe["portal_create"][0]["return_url"] == "https://talaix.test/account.html"


# ---------------------------------------------------------------------------
# Legacy subscribe endpoint gating
# ---------------------------------------------------------------------------


def test_subscribe_returns_402_when_billing_configured(client, env):
    headers = _auth_headers(client, env)
    resp = client.post("/api/v2/account/subscribe", headers=headers)
    assert resp.status_code == 402
    body = resp.get_json()
    assert body["upgrade"]["checkout_url"] == "/api/v2/billing/checkout"


def test_subscribe_keeps_legacy_behaviour_when_billing_not_configured(client, env, monkeypatch):
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    headers = _auth_headers(client, env, email="legacy@example.org")
    resp = client.post("/api/v2/account/subscribe", headers=headers)
    assert resp.status_code == 201
    assert resp.get_json()["subscription"]["tier"] == "subscriber"


def test_webhook_handler_failure_allows_redelivery(client, env, fake_stripe, monkeypatch):
    """A crashing handler must not swallow Stripe's redelivery as a duplicate:
    the event is forgotten so the retry is actually processed."""
    _auth_headers(client, env, email="retry@example.org")
    session_obj = {
        "id": "cs_retry",
        "mode": "subscription",
        "customer": "cus_retry",
        "subscription": "sub_retry",
        "client_reference_id": "1",
        "metadata": {"talaix_user_id": "1", "talaix_tier": "professional"},
    }
    import src.dashboard.billing as billing_mod

    original = billing_mod._handle_checkout_session_completed
    calls = {"n": 0}

    def flaky(obj):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient handler failure")
        return original(obj)

    monkeypatch.setattr(billing_mod, "_handle_checkout_session_completed", flaky)
    with pytest.raises(RuntimeError):
        _webhook(client, "checkout.session.completed", session_obj, event_id="evt_retry")
    resp = _webhook(client, "checkout.session.completed", session_obj, event_id="evt_retry")
    assert resp.status_code == 200
    assert _role(env, "retry@example.org") == "professional"
