"""
HydraShield outbound webhooks (event-driven intelligence).

Implements the webhook contract of docs/API_FIRST_STRATEGY.md §3/§5:

- **Subscriptions** live in ``webhook_subscriptions`` (see
  ``notify_store.py``): a target HTTPS URL, a signing secret and a
  comma-separated event list (``alert_fired`` [, ``significant_change``]).
- **Signing secret** — generated at creation as
  ``accounts.hash_token(<one-time internal entropy>)``: the stored
  ``secret_hash`` column therefore genuinely holds an HMAC-SHA256 (server
  -keyed) derivative, and the derived value is returned to the subscriber
  exactly once (like a token). Because HMAC signing needs the key material
  at delivery time, that derived value IS the signing key — this is the
  only self-consistent reading of "stored HMAC-hashed + returned once +
  verifiable signature". The internal pre-image entropy is never stored,
  logged or returned. The secret must never appear in logs or audit rows.
- **Signature** — every delivery POSTs JSON
  ``{"event", "data", "sent_at"}`` with header
  ``X-HydraShield-Signature: sha256=<hmac-sha256 hex of the raw body with
  the subscription secret>``.
- **SSRF guard** — :func:`target_allowed` allows HTTPS targets only whose
  hostname resolves to a public IP (loopback / private / link-local /
  reserved / multicast / unspecified rejected; resolution failure
  rejected). It is enforced BOTH at subscription creation and again at
  every delivery (DNS answers can change between the two).
- **Delivery statuses** — recorded honestly as ``sent`` | ``failed`` |
  ``disabled`` (disabled = target no longer passes the SSRF guard at
  delivery time). Delivery errors are reported in the descriptor, never
  raised, so webhooks can never break the other alert channels.

Stdlib only (``urllib``); a 10 s timeout caps every delivery attempt.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import logging
import secrets
import socket
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Dict, List, Optional

from .accounts import hash_token

log = logging.getLogger("hydrashield.webhooks")

HTTP_TIMEOUT_SECONDS = 10

WEBHOOK_EVENTS = ("alert_fired", "significant_change")


def _utcnow() -> str:
    return datetime.utcnow().isoformat() + "Z"


def generate_secret() -> str:
    """
    New webhook signing secret: ``accounts.hash_token`` of one-time
    internal entropy. The derived value is stored in ``secret_hash``,
    returned to the subscriber exactly once at creation, and used as the
    HMAC key for ``X-HydraShield-Signature``. Never logged.
    """
    return hash_token("whsec_" + secrets.token_urlsafe(24))


def signature_header(secret: str, body: bytes) -> str:
    """``sha256=<hmac-sha256 hex of the raw body with the secret>``."""
    digest = hmac.new(
        (secret or "").encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


# ---------------------------------------------------------------------------
# SSRF guard
# ---------------------------------------------------------------------------

def target_allowed(url: str) -> bool:
    """
    True when ``url`` is an allowed webhook target:

    - scheme is exactly ``https`` (HTTP is never acceptable);
    - a hostname is present and resolves (``socket.gethostbyname``);
    - the resolved IP is public — loopback, private, link-local, reserved,
      multicast and unspecified addresses are rejected.

    Resolution failure rejects the target (fail-closed). Applied at
    subscription creation AND at every delivery (DNS rebinding mitigation).
    """
    try:
        parsed = urllib.parse.urlparse(url or "")
    except (ValueError, TypeError):
        return False
    if parsed.scheme != "https":
        return False
    host = parsed.hostname
    if not host:
        return False
    try:
        resolved = socket.gethostbyname(host)
    except Exception:  # DNS failure / unresolvable → fail closed
        return False
    try:
        ip = ipaddress.ip_address(resolved)
    except ValueError:
        return False
    if (ip.is_loopback or ip.is_private or ip.is_link_local
            or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
        return False
    return True


# ---------------------------------------------------------------------------
# Delivery
# ---------------------------------------------------------------------------

def deliver_webhook(
    url: str,
    secret: str,
    event_type: str,
    payload: Dict,
) -> Dict:
    """
    POST one signed event to ``url``. Returns a delivery descriptor::

        {"status": "sent"}                    — 2xx response
        {"status": "failed",  "error": …}     — network/HTTP error
        {"status": "disabled"}                — target fails the SSRF guard

    The body is ``{"event", "data", "sent_at"}`` (compact JSON) and carries
    ``X-HydraShield-Signature`` (see :func:`signature_header`). Errors are
    reported, never raised. The error string is the exception TYPE only —
    URLs and secrets are never echoed into logs.
    """
    if event_type not in WEBHOOK_EVENTS:
        return {"status": "failed", "error": f"unknown event {event_type!r}"}
    if not target_allowed(url):
        log.warning("Webhook delivery suppressed: target not allowed (event=%s)",
                    event_type)
        return {"status": "disabled"}
    body = json.dumps(
        {"event": event_type, "data": payload, "sent_at": _utcnow()},
        separators=(",", ":"), default=str,
    ).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "HydraShield-Webhook/1.0",
            "X-HydraShield-Signature": signature_header(secret, body),
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
            resp.read()
    except Exception as exc:  # network/HTTP errors reported, never raised
        log.warning("Webhook delivery failed (event=%s): %s",
                    event_type, type(exc).__name__)
        return {"status": "failed", "error": type(exc).__name__}
    return {"status": "sent"}


def dispatch_webhooks(
    store,
    user_id: int,
    event_type: str,
    payload: Dict,
    alert_id: Optional[str] = None,
) -> List[Dict]:
    """
    Deliver ``event_type`` to every active subscription of ``user_id`` that
    lists the event; record each outcome in ``alert_deliveries`` with
    ``channel="webhook"`` when ``alert_id`` is given. Delivery failures
    never propagate — webhooks can never break email/SMS dispatch. The
    recorded delivery target is the subscription URL (operational fact);
    the secret is never recorded.
    """
    results: List[Dict] = []
    try:
        subscriptions = store.list_active_webhooks_for_event(user_id, event_type)
    except Exception as exc:
        log.warning("Webhook subscription lookup failed for user %s: %s",
                    user_id, type(exc).__name__)
        return results
    for sub in subscriptions:
        try:
            outcome = deliver_webhook(
                sub["url"], sub["secret_hash"], event_type, payload)
        except Exception as exc:  # defensive: deliver_webhook never raises
            outcome = {"status": "failed", "error": type(exc).__name__}
        status = outcome.get("status", "failed")
        if alert_id is not None:
            try:
                store.record_delivery(alert_id, "webhook", sub["url"], status)
            except Exception as exc:
                log.warning("Webhook delivery record failed for user %s: %s",
                            user_id, type(exc).__name__)
        results.append({"webhook_id": sub["id"], "status": status})
    return results
