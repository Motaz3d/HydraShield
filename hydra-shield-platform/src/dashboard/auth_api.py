"""
HydraShield account & auth API (Stage 6) — Flask blueprint ``auth_bp``.

Mounted at ``/api/v2`` alongside the multi-hazard v2 blueprint (registered
from ``src/dashboard/api.py::create_app()``). Implements the endpoints of
docs/USER_AND_SUBSCRIPTION_ARCHITECTURE.md §6:

    POST /api/v2/auth/register · POST /api/v2/auth/login · POST /api/v2/auth/logout
    GET  /api/v2/auth/verify · POST /api/v2/auth/resend-verification

``GET /auth/verify`` answers browsers (Accept: text/html) with a redirect to
``/account.html?verified=1`` (or ``?verify_error=1`` for an invalid/expired
token) and sets the session cookie on the redirect; API clients keep the
JSON contract.
    GET  /api/v2/account · PATCH /api/v2/account
    GET/POST /api/v2/account/locations · DELETE /api/v2/account/locations/<id>
    GET  /api/v2/account/history
    GET/POST /api/v2/account/alerts · DELETE /api/v2/account/alerts/<id>
    POST /api/v2/account/api-keys (subscriber) · GET /api/v2/account/api-keys
    DELETE /api/v2/account/api-keys/<id>
    GET/POST /api/v2/account/webhooks · DELETE /api/v2/account/webhooks/<id>
    GET  /api/v2/account/usage
    POST /api/v2/contact   (public; acknowledgement email; 5/hour/IP)

Authentication: ``Authorization: Bearer <session token>`` (API clients) or
the ``hydrashield_session`` HttpOnly cookie (website); Bearer takes
precedence. When no session is present, the ``X-API-Key`` header
authenticates external consumers (subscriber-issued keys, stored
HMAC-hashed, revocable) — API keys are READ-ONLY: they never authenticate
POST/DELETE/PATCH account mutations (403 "API keys are read-only").
CSRF: cookie-based browser POSTs rely on the SameSite=Lax
cookie attribute; API clients must use Bearer only. Tokens are random
256-bit values, stored HMAC-hashed (see ``accounts.py``).

Rate limiting: per-IP sliding-window limits on the public auth endpoints
(reusing the shared ``_rate_limiter``); authenticated endpoints are limited
per user id with per-tier budgets (``accounts.TIER_RATE_LIMITS``).
"""

from __future__ import annotations

import functools
import os

from flask import Blueprint, g, jsonify, redirect, request

from .accounts import (
    EMAIL_TOKEN_TTL_SECONDS,
    ROLE_RANK,
    SESSION_TTL_SECONDS,
    TIER_RATE_LIMITS,
    UserStore,
)

auth_bp = Blueprint("auth", __name__, url_prefix="/api/v2")

SESSION_COOKIE = "hydrashield_session"

_BASE_URL = lambda: os.environ.get("HYDRASHIELD_BASE_URL", "https://hydrashield.earth").rstrip("/")  # noqa: E731


def _err(message: str, status: int, **extra):
    payload = {"error": message, "status": status}
    payload.update(extra)
    return jsonify(payload), status


def _rate(key: str, max_requests: int, window: float) -> bool:
    from .api import _client_key, _rate_limiter  # lazy: avoid circulars

    return _rate_limiter.allow(f"{key}:{_client_key()}", max_requests, window)


def _tier_rate(user: dict, bucket: str) -> bool:
    """Per-user rate limit with the tier's budget (docs §4)."""
    from .api import _rate_limiter  # lazy: avoid circulars

    max_req, window = TIER_RATE_LIMITS.get(user["role"], TIER_RATE_LIMITS["registered"])
    return _rate_limiter.allow(f"{bucket}:u{user['id']}", max_req, window)


# ---------------------------------------------------------------------------
# Authentication helpers
# ---------------------------------------------------------------------------

def _bearer_token() -> str:
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        return header[len("Bearer "):].strip()
    return ""


def current_token() -> str:
    """Session token from the Bearer header or the session cookie."""
    return _bearer_token() or request.cookies.get(SESSION_COOKIE, "")


_SAFE_METHODS = ("GET", "HEAD", "OPTIONS")


def current_user():
    """
    The authenticated user dict, or None (cached on the request).

    Resolution order: Bearer/cookie session first; when no session is
    present, the ``X-API-Key`` header is tried (external consumers,
    docs/API_FIRST_STRATEGY.md §3). API keys are READ-ONLY credentials:
    on a non-safe method a valid key does not authenticate the request —
    ``g.api_key_mutation_blocked`` is set instead, so the auth decorators
    answer 403 "API keys are read-only" rather than a bare 401.
    """
    if "current_user" not in g:
        store = UserStore()
        user = store.get_session_user(current_token())
        g.auth_via_api_key = False
        if user is None:
            api_key = (request.headers.get("X-API-Key") or "").strip()
            if api_key:
                candidate = store.get_user_by_api_key(api_key)
                if candidate is not None:
                    if request.method in _SAFE_METHODS:
                        user = candidate
                        g.auth_via_api_key = True
                    else:
                        g.api_key_mutation_blocked = True
        g.current_user = user
    return g.current_user


def _unauthorized():
    """401 — or 403 when a valid read-only API key attempted a mutation."""
    if getattr(g, "api_key_mutation_blocked", False):
        return _err("API keys are read-only", 403)
    return _err("Authentication required", 401)


def require_role(role: str):
    """
    Decorator: require an authenticated user whose role ranks >= ``role``
    (progressive gating, docs §2). 401 when unauthenticated; 403 with a
    JSON ``upgrade`` descriptor when the tier is insufficient.
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            user = current_user()
            if user is None:
                return _unauthorized()
            if ROLE_RANK.get(user["role"], 0) < ROLE_RANK.get(role, 0):
                return _err(
                    f"This feature requires the '{role}' tier",
                    403,
                    upgrade={
                        "required_role": role,
                        "your_role": user["role"],
                        "unlocks": f"Upgrading to '{role}' unlocks this feature.",
                    },
                )
            g.current_user = user
            return func(*args, **kwargs)

        return wrapper

    return decorator


def _set_session_cookie(response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=int(SESSION_TTL_SECONDS),
        httponly=True,
        samesite="Lax",
        secure=request.scheme == "https",
        path="/",
    )


def _hello_name(display_name) -> str:
    return f" {display_name}" if display_name else ""


def _prefers_html() -> bool:
    """True when the client asks for HTML over JSON — a browser following
    the email link. API clients (no Accept header, ``*/*``, or an explicit
    ``application/json``) keep the JSON contract."""
    return (request.accept_mimetypes["text/html"]
            > request.accept_mimetypes["application/json"])


def _send_verification_email(user: dict) -> None:
    """Create a fresh verification token and email the link (dev: outbox)."""
    store = UserStore()
    token = store.create_email_token(user["id"], "verify_email")
    from . import mailer

    mailer.send_mail(
        user["email"],
        "email_verification",
        {
            "display_name": _hello_name(user.get("display_name")),
            "verify_url": f"{_BASE_URL()}/api/v2/auth/verify?token={token}",
            "expires_hours": int(EMAIL_TOKEN_TTL_SECONDS // 3600),
        },
    )


# ---------------------------------------------------------------------------
# Auth endpoints
# ---------------------------------------------------------------------------

@auth_bp.post("/auth/register")
def register():
    if not _rate("v2auth_register", 20, 3600.0):
        return _err("Rate limit exceeded (20 registrations/hour)", 429)
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip()
    password = data.get("password") or ""
    store = UserStore()
    user = store.register_user(
        email,
        password,
        display_name=data.get("display_name"),
        # GDPR: record only consent actually given — never assume it.
        consent=bool(data.get("consent", False)),
    )
    if "error" in user:
        status = 409 if "already registered" in user["error"] else 400
        return _err(user["error"], status)
    _send_verification_email(user)
    # Platform/admin notification: the registration is visible to the
    # operator via the platform inbox (dev: safe outbox). Contains only the
    # account email + timestamp — never the password (which is stored only
    # as a hash) or any other secret.
    from . import mailer

    mailer.send_mail(
        mailer.contact_inbox(),
        "admin_notification",
        {
            "email": user["email"],
            "display_name": user.get("display_name") or "(none)",
            "registered_at": user.get("created_at") or "",
        },
    )
    return jsonify({
        "status": "pending_verification",
        "email": user["email"],
        "message": "Check your inbox for the verification link.",
    }), 201


@auth_bp.get("/auth/verify")
def verify():
    token = (request.args.get("token") or "").strip()
    store = UserStore()
    user_id = store.consume_email_token(token, "verify_email")
    if user_id is None:
        # Browsers land back on the account page with an error notice;
        # API clients keep the JSON 400.
        if _prefers_html():
            return redirect("/account.html?verify_error=1")
        return _err("Invalid or expired verification token", 400)
    store.mark_email_verified(user_id)
    user = store.get_user(user_id)
    store.audit(user_id, "verify", target=user["email"])
    session_token = store.create_session(
        user_id,
        ip=request.remote_addr,
        user_agent=request.headers.get("User-Agent"),
    )
    # Product analytics: account_created is recorded server-side — the only
    # place an account id legitimately meets the event stream (docs/
    # PRODUCT_ANALYTICS.md). Analytics failure must never break auth.
    try:
        from .analytics import AnalyticsStore

        AnalyticsStore().record(
            {"event": "account_created", "page": "account.html"},
            user_id=user_id,
        )
    except Exception:  # noqa: BLE001 — analytics must never break auth
        pass
    from . import mailer

    mailer.send_mail(
        user["email"], "welcome",
        {"display_name": _hello_name(user.get("display_name"))})
    if _prefers_html():
        # Browser following the email link: land on the account page,
        # already signed in via the session cookie set below.
        resp = redirect("/account.html?verified=1")
    else:
        resp = jsonify({
            "status": "verified",
            "session_token": session_token,
            "user": user,
        })
    _set_session_cookie(resp, session_token)
    return resp


@auth_bp.post("/auth/resend-verification")
def resend_verification():
    if not _rate("v2auth_resend", 10, 3600.0):
        return _err("Rate limit exceeded (10 requests/hour)", 429)
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip()
    store = UserStore()
    user = store.get_user_by_email(email) if email else None
    if user is not None and user["status"] == "pending":
        _send_verification_email(user)
        store.audit(user["id"], "resend_verification", target=user["email"])
    # Indistinguishable response: do not reveal whether the address exists.
    return jsonify({
        "status": "ok",
        "message": "If the address is registered and unverified, a new "
                   "verification email is on its way.",
    })


@auth_bp.post("/auth/forgot-password")
def forgot_password():
    """Request a password-reset email. Indistinguishable response."""
    if not _rate("v2auth_forgot", 10, 3600.0):
        return _err("Rate limit exceeded (10 requests/hour)", 429)
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip()
    store = UserStore()
    user = store.get_user_by_email(email) if email else None
    if user is not None and user["status"] == "active":
        token = store.create_email_token(user["id"], "reset_password")
        from . import mailer

        mailer.send_mail(
            user["email"],
            "password_reset",
            {
                "display_name": _hello_name(user.get("display_name")),
                "reset_url": f"{_BASE_URL()}/account.html?reset_token={token}",
                "expires_hours": int(EMAIL_TOKEN_TTL_SECONDS // 3600),
            },
        )
        store.audit(user["id"], "password_reset_requested", target=user["email"])
    # Indistinguishable response: do not reveal whether the account exists.
    return jsonify({
        "status": "ok",
        "message": "If the address is registered, a password-reset link "
                   "is on its way.",
    })


@auth_bp.post("/auth/reset-password")
def reset_password():
    """Consume a reset token and set a new password; all sessions die.

    The new password is validated BEFORE the single-use token is consumed,
    so a weak-password attempt does not burn the token.
    """
    if not _rate("v2auth_reset", 10, 3600.0):
        return _err("Rate limit exceeded (10 requests/hour)", 429)
    data = request.get_json(silent=True) or {}
    token = (data.get("token") or "").strip()
    new_password = data.get("password") or ""
    store = UserStore()
    err = UserStore.validate_password(new_password)
    if err:
        return _err(err, 400)
    user_id = store.consume_email_token(token, "reset_password")
    if user_id is None:
        return _err("Invalid or expired reset token", 400)
    err = store.set_password(user_id, new_password)
    if err:  # pragma: no cover — validated above; defensive only
        return _err(err, 400)
    store.delete_user_sessions(user_id)
    store.audit(user_id, "password_reset", target="self")
    return jsonify({
        "status": "password_updated",
        "message": "Your password has been updated. Please log in again.",
    })


@auth_bp.post("/auth/login")
def login():
    if not _rate("v2auth_login", 30, 900.0):
        return _err("Rate limit exceeded (30 attempts/15 minutes)", 429)
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip()
    password = data.get("password") or ""
    store = UserStore()
    user = store.check_password(email, password)
    if user is None:
        # No indication whether the account exists; nothing secret is logged.
        store.audit(None, "login_failed", target=(email or "")[:200])
        return _err("Invalid credentials", 401)
    if user["status"] != "active":
        return _err("Email address not verified", 403)
    store.touch_login(user["id"])
    store.audit(user["id"], "login", target=user["email"])
    store.log_usage(user["id"], "/api/v2/auth/login")
    session_token = store.create_session(
        user["id"],
        ip=request.remote_addr,
        user_agent=request.headers.get("User-Agent"),
    )
    resp = jsonify({"session_token": session_token, "user": user})
    _set_session_cookie(resp, session_token)
    return resp


@auth_bp.post("/auth/logout")
def logout():
    store = UserStore()
    token = current_token()
    user = store.get_session_user(token) if token else None
    if user is not None:
        store.audit(user["id"], "logout", target=user["email"])
    store.delete_session(token)
    resp = jsonify({"status": "logged_out"})
    resp.delete_cookie(SESSION_COOKIE, path="/")
    return resp


# ---------------------------------------------------------------------------
# Account endpoints
# ---------------------------------------------------------------------------

@auth_bp.get("/account")
def account_profile():
    user = current_user()
    if user is None:
        return _unauthorized()
    store = UserStore()
    return jsonify({
        "user": user,
        "locations": len(store.list_locations(user["id"])),
        "alerts": len(store.list_alerts(user["id"])),
    })


@auth_bp.patch("/account")
def account_update():
    user = current_user()
    if user is None:
        return _unauthorized()
    data = request.get_json(silent=True) or {}
    if "display_name" not in data:
        return _err("Nothing to update (supported: display_name)", 400)
    display_name = (data.get("display_name") or "").strip()
    if len(display_name) > 200:
        return _err("display_name is too long (max 200 characters)", 400)
    updated = UserStore().update_user(user["id"], display_name=display_name)
    return jsonify({"user": updated})


@auth_bp.get("/account/locations")
@require_role("registered")
def list_locations():
    return jsonify({"locations": UserStore().list_locations(g.current_user["id"])})


@auth_bp.post("/account/locations")
@require_role("registered")
def add_location():
    user = g.current_user
    if not _tier_rate(user, "v2_locations"):
        return _err("Rate limit exceeded for your tier", 429)
    data = request.get_json(silent=True) or {}
    try:
        lat = float(data.get("lat"))
        lon = float(data.get("lon"))
    except (TypeError, ValueError):
        return _err("lat and lon must be numbers", 400)
    store = UserStore()
    if len(store.list_locations(user["id"])) >= 50:
        return _err("Saved-location limit reached (50)", 403, upgrade={
            "required_role": "subscriber",
            "your_role": user["role"],
            "unlocks": "Higher saved-location limits.",
        })
    result = store.add_location(user["id"], data.get("name"), lat, lon)
    if "error" in result:
        return _err(result["error"], 400)
    return jsonify({"location": result}), 201


@auth_bp.delete("/account/locations/<int:location_id>")
@require_role("registered")
def delete_location(location_id: int):
    if UserStore().delete_location(g.current_user["id"], location_id):
        return jsonify({"deleted": True})
    return _err("Location not found", 404)


@auth_bp.get("/account/history")
@require_role("registered")
def account_history():
    return jsonify(UserStore().get_history(g.current_user["id"]))


@auth_bp.get("/account/alerts")
@require_role("registered")
def list_alerts():
    return jsonify({"alerts": UserStore().list_alerts(g.current_user["id"])})


@auth_bp.post("/account/alerts")
@require_role("registered")
def add_alert():
    user = g.current_user
    if not _tier_rate(user, "v2_alerts"):
        return _err("Rate limit exceeded for your tier", 429)
    data = request.get_json(silent=True) or {}
    try:
        lat = float(data.get("lat"))
        lon = float(data.get("lon"))
    except (TypeError, ValueError):
        return _err("lat and lon must be numbers", 400)
    threshold = data.get("threshold")
    if threshold is not None and not isinstance(threshold, dict):
        return _err("threshold must be an object, e.g. {\"risk_gte\": 65}", 400)
    result = UserStore().add_alert(
        user["id"],
        data.get("hazard") or "wildfire",
        lat,
        lon,
        threshold=threshold,
        channel=data.get("channel") or "email",
    )
    if "error" in result:
        return _err(result["error"], 400)
    return jsonify({"alert": result}), 201


@auth_bp.delete("/account/alerts/<int:alert_id>")
@require_role("registered")
def delete_alert(alert_id: int):
    if UserStore().delete_alert(g.current_user["id"], alert_id):
        return jsonify({"deleted": True})
    return _err("Alert not found", 404)


# ---------------------------------------------------------------------------
# API keys (external consumers; docs/API_FIRST_STRATEGY.md §3)
# ---------------------------------------------------------------------------

@auth_bp.post("/account/api-keys")
@require_role("subscriber")
def create_api_key():
    """Create an API key. The plaintext key is returned ONLY in this
    response (stored HMAC-hashed); keys are read-only credentials."""
    user = g.current_user
    if not _tier_rate(user, "v2_api_keys"):
        return _err("Rate limit exceeded for your tier", 429)
    data = request.get_json(silent=True) or {}
    result = UserStore().create_api_key(user["id"], label=data.get("label"))
    return jsonify({
        "api_key": result,
        "note": "Store the key now — it is shown only once. Send it as the "
                "X-API-Key header on GET requests; API keys are read-only.",
    }), 201


@auth_bp.get("/account/api-keys")
@require_role("registered")
def list_api_keys():
    return jsonify({"api_keys": UserStore().list_api_keys(g.current_user["id"])})


@auth_bp.delete("/account/api-keys/<int:key_id>")
@require_role("registered")
def revoke_api_key(key_id: int):
    if UserStore().revoke_api_key(g.current_user["id"], key_id):
        return jsonify({"revoked": True})
    return _err("API key not found", 404)


# ---------------------------------------------------------------------------
# Webhook subscriptions (outbound, HMAC-signed; docs/API_FIRST_STRATEGY.md §5)
# ---------------------------------------------------------------------------

@auth_bp.get("/account/webhooks")
@require_role("registered")
def list_webhooks():
    from .notify_store import NotifyStore

    return jsonify({"webhooks": NotifyStore().list_webhooks(g.current_user["id"])})


@auth_bp.post("/account/webhooks")
@require_role("registered")
def add_webhook():
    """Create a webhook subscription. The target URL must pass the SSRF
    guard (HTTPS, publicly resolvable IP — checked at creation AND at every
    delivery). The signing secret is returned ONLY in this response."""
    user = g.current_user
    if not _tier_rate(user, "v2_webhooks"):
        return _err("Rate limit exceeded for your tier", 429)
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    events = data.get("events")
    if events is None:
        events = ["alert_fired"]
    elif isinstance(events, str):
        events = [events]
    if not isinstance(events, list):
        return _err('events must be a list, e.g. ["alert_fired", "significant_change"]', 400)
    from .webhooks import target_allowed

    if not target_allowed(url):
        return _err(
            "Webhook URL not allowed (HTTPS URL with a publicly resolvable "
            "host required; private/loopback targets are rejected)", 400)
    from .notify_store import NotifyStore

    result = NotifyStore().add_webhook(user["id"], url, events)
    if "error" in result:
        return _err(result["error"], 400)
    return jsonify({
        "webhook": result["webhook"],
        "secret": result["secret"],
        "note": "Store the secret now — it is shown only once. Deliveries "
                "are POSTs signed with X-HydraShield-Signature: "
                "sha256=<hmac-sha256 of the raw body with this secret>.",
    }), 201


@auth_bp.delete("/account/webhooks/<int:webhook_id>")
@require_role("registered")
def delete_webhook(webhook_id: int):
    from .notify_store import NotifyStore

    if NotifyStore().delete_webhook(g.current_user["id"], webhook_id):
        return jsonify({"deleted": True})
    return _err("Webhook subscription not found", 404)


@auth_bp.get("/account/usage")
@require_role("registered")
def account_usage():
    return jsonify({"usage": UserStore().get_usage(g.current_user["id"])})


# ---------------------------------------------------------------------------
# Contact (public)
# ---------------------------------------------------------------------------

@auth_bp.post("/contact")
def contact():
    if not _rate("v2_contact", 5, 3600.0):
        return _err("Rate limit exceeded (5 messages/hour)", 429)
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip()
    message = (data.get("message") or "").strip()
    name = (data.get("name") or "").strip()[:200]
    organization = (data.get("organization") or "").strip()[:200]
    interest = (data.get("interest") or "").strip()[:100]
    if UserStore.validate_email(email):
        return _err("A valid email address is required", 400)
    if len(message) < 10:
        return _err("message must be at least 10 characters", 400)
    if len(message) > 5000:
        return _err("message is too long (max 5000 characters)", 400)
    from . import mailer

    # The message itself goes to the platform inbox — contact submissions
    # must actually reach HydraShield (previously they did not).
    mailer.send_mail(
        mailer.contact_inbox(),
        "contact_message",
        {"name": name or "(no name given)", "email": email,
         "organization": organization or "(not given)",
         "interest": interest or "(not given)",
         "message": message},
    )
    # The acknowledgement to the submitter intentionally does NOT echo the
    # message: quoting attacker-controlled content to arbitrary addresses
    # would turn the form into a spam/abuse relay.
    mailer.send_mail(
        email,
        "contact_acknowledgement",
        {"name": f" {name}" if name else ""},
    )
    return jsonify({"status": "received",
                    "message": "Thank you — we will reply to your address."}), 201
