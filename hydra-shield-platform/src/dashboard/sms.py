"""
Talaix SMS delivery — replaceable provider abstraction.

One entry point — :func:`send_sms` — delivers a short text message to an
E.164 phone number through one of three honest backends:

- **Outbox (dev) backend** — DEFAULT when ``SMS_PROVIDER`` is unset: the
  message is written to ``data/outbox/<timestamp>_<to-hash>.sms.txt``
  (override with ``HYDRASHIELD_OUTBOX_DIR``) and logged. It is NEVER sent.
  Tests use this backend and assert on the outbox files.
- **Generic HTTP backend** — ``SMS_PROVIDER=http``: POSTs a JSON payload
  ``{"to", "from", "message"}`` to ``SMS_HTTP_URL`` (required) over HTTPS
  via stdlib ``urllib`` with a 15 s timeout. Authentication is a single
  configurable header: ``SMS_HTTP_AUTH_HEADER`` (default
  ``"Authorization: Bearer {key}"``) where ``{key}``/``{secret}`` are
  substituted from ``SMS_API_KEY``/``SMS_API_SECRET``. The provider message
  id is captured defensively from the JSON response (``message_id`` | ``id``
  | ``sid``). No provider-specific capabilities are assumed beyond this
  contract; swapping providers is an env change, not a code change.
- **Twilio backend** — ``SMS_PROVIDER=twilio``: POSTs the form-encoded
  ``To``/``From``/``Body`` to Twilio's Messages endpoint with HTTP Basic
  auth (``TWILIO_ACCOUNT_SID`` : ``TWILIO_AUTH_TOKEN``). Sender is
  ``TWILIO_FROM_NUMBER`` (the Twilio-owned number). All three variables
  are required; a missing one is reported as ``misconfigured``.
- **Disabled** — ``SMS_PROVIDER=disabled``: nothing is sent or written.

``SMS_PROVIDER=http`` without ``SMS_HTTP_URL`` returns
``{"backend": "misconfigured", "error": ...}`` honestly — it never raises.

Credentials come from the environment only; they are never logged, never
stored in the database and never assumed or invented.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from typing import Dict, Optional

log = logging.getLogger("hydrashield.sms")

# E.164: "+" followed by 7-15 digits, first digit non-zero.
_E164_RE = re.compile(r"^\+[1-9]\d{6,14}$")

_HTTP_TIMEOUT_SECONDS = 15


def normalize_e164(phone: str) -> str:
    """Normalise a user-entered phone number towards E.164 form.

    Strips whitespace, dashes, dots and parentheses; converts a leading
    international ``00`` prefix to ``+``. Returns the normalised candidate
    (which may still fail :func:`valid_e164`).
    """
    candidate = re.sub(r"[\s\-().]", "", phone or "")
    if candidate.startswith("00"):
        candidate = "+" + candidate[2:]
    return candidate


def valid_e164(phone: str) -> bool:
    """True when ``phone`` (after normalisation) is a valid E.164 number."""
    return bool(_E164_RE.match(normalize_e164(phone)))


def _outbox_dir() -> str:
    return os.environ.get(
        "HYDRASHIELD_OUTBOX_DIR",
        os.path.join(os.path.dirname(__file__), "..", "..", "data", "outbox"),
    )


def _provider() -> str:
    return (os.environ.get("SMS_PROVIDER") or "").strip().lower()


def sms_configured() -> bool:
    """True when a real delivery backend is configured (HTTP provider with
    URL set, or Twilio with its three credentials). The outbox backend is a
    safe dev default, not real delivery."""
    if _provider() == "http":
        return bool(os.environ.get("SMS_HTTP_URL"))
    if _provider() == "twilio":
        return all(os.environ.get(k) for k in
                   ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER"))
    return False


def _write_outbox(to_e164: str, message: str) -> str:
    outdir = _outbox_dir()
    os.makedirs(outdir, exist_ok=True)
    digest = hashlib.sha256(to_e164.encode("utf-8")).hexdigest()[:10]
    stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime()) + f"{int(time.time() * 1e6) % 1000000:06d}"
    path = os.path.join(outdir, f"{stamp}_{digest}.sms.txt")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(f"To: {to_e164}\n\n{message}\n")
    return path


def _auth_header() -> Optional[tuple]:
    """Build the configured auth header (name, value); None when unusable.

    ``SMS_HTTP_AUTH_HEADER`` format: ``"Header-Name: value with {key} and/or
    {secret}"``. Defaults to ``Authorization: Bearer {key}``.
    """
    template = os.environ.get("SMS_HTTP_AUTH_HEADER") or "Authorization: Bearer {key}"
    key = os.environ.get("SMS_API_KEY", "")
    secret = os.environ.get("SMS_API_SECRET", "")
    # Placeholders without values would produce a broken header — omit it.
    if ("{key}" in template and not key) or ("{secret}" in template and not secret):
        return None
    name, sep, value = template.partition(":")
    if not sep or not name.strip():
        return None
    value = value.replace("{key}", key).replace("{secret}", secret).strip()
    if not value:
        return None
    return name.strip(), value


def _send_http(to_e164: str, message: str) -> Dict:
    import urllib.request

    url = os.environ.get("SMS_HTTP_URL")
    if not url:
        # Honest misconfiguration: http provider selected but no endpoint.
        return {
            "backend": "misconfigured",
            "error": "SMS_PROVIDER=http requires SMS_HTTP_URL to be set",
        }
    payload = json.dumps({
        "to": to_e164,
        "from": os.environ.get("SMS_FROM", ""),
        "message": message,
    }).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    header = _auth_header()
    if header is not None:
        req.add_header(header[0], header[1])
    try:
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT_SECONDS) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except Exception as exc:  # network/HTTP errors reported, never raised
        log.warning("SMS http delivery to %s failed: %s", to_e164, type(exc).__name__)
        return {"backend": "http", "error": f"{type(exc).__name__}: {exc}"}
    provider_id = None
    try:
        data = json.loads(body) if body else {}
        if isinstance(data, dict):
            for key_name in ("message_id", "id", "sid"):
                if data.get(key_name):
                    provider_id = str(data[key_name])
                    break
    except (ValueError, TypeError):
        provider_id = None  # non-JSON response: no id captured, still sent
    log.info("Sent SMS to %s via HTTP provider (message id captured: %s)",
             to_e164, bool(provider_id))
    return {"backend": "http", "provider_message_id": provider_id}


def _send_twilio(to_e164: str, message: str) -> Dict:
    """Deliver via Twilio's Messages endpoint (form-encoded + Basic auth)."""
    import base64
    import urllib.parse
    import urllib.request

    sid = os.environ.get("TWILIO_ACCOUNT_SID", "")
    token = os.environ.get("TWILIO_AUTH_TOKEN", "")
    from_number = os.environ.get("TWILIO_FROM_NUMBER", "")
    if not (sid and token and from_number):
        return {
            "backend": "misconfigured",
            "error": "SMS_PROVIDER=twilio requires TWILIO_ACCOUNT_SID,"
                     " TWILIO_AUTH_TOKEN and TWILIO_FROM_NUMBER",
        }
    url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
    payload = urllib.parse.urlencode(
        {"To": to_e164, "From": from_number, "Body": message}).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "Authorization": "Basic " + base64.b64encode(
                f"{sid}:{token}".encode("utf-8")).decode("ascii"),
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT_SECONDS) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except Exception as exc:  # network/HTTP errors reported, never raised
        detail = ""
        if isinstance(exc, urllib.error.HTTPError):
            try:
                err_data = json.loads(exc.read().decode("utf-8", errors="replace"))
                detail = err_data.get("message") or ""
            except Exception:
                detail = ""
        log.warning("SMS twilio delivery to %s failed: %s %s",
                    to_e164, type(exc).__name__, detail)
        return {"backend": "twilio",
                "error": f"{type(exc).__name__}: {detail or exc}"}
    provider_id = None
    try:
        data = json.loads(body) if body else {}
        if isinstance(data, dict) and data.get("sid"):
            provider_id = str(data["sid"])
    except (ValueError, TypeError):
        provider_id = None
    log.info("Sent SMS to %s via Twilio (sid captured: %s)", to_e164, bool(provider_id))
    return {"backend": "twilio", "provider_message_id": provider_id}


def send_sms(to_e164: str, message: str) -> Dict:
    """
    Deliver an SMS. Returns a delivery descriptor::

        {"backend": "outbox", "path": "<sms.txt path>"}   — dev, never sent
        {"backend": "http", "provider_message_id": …}     — sent via provider
        {"backend": "twilio", "provider_message_id": …}   — sent via Twilio
        {"backend": "disabled"}                           — SMS_PROVIDER=disabled
        {"backend": "misconfigured", "error": …}          — http without URL
                                                          — or twilio missing
                                                          — credentials

    Delivery errors are reported in the descriptor (``error`` key), never
    raised. Credentials are read from the environment only and are never
    logged or stored.
    """
    to_e164 = normalize_e164(to_e164)
    if not valid_e164(to_e164):
        return {"backend": "misconfigured", "error": f"Invalid E.164 number: {to_e164!r}"}
    provider = _provider()
    if provider == "disabled":
        log.info("SMS disabled — message for %s not delivered", to_e164)
        return {"backend": "disabled"}
    if provider == "http":
        return _send_http(to_e164, message)
    if provider == "twilio":
        return _send_twilio(to_e164, message)
    # Unknown provider values fall through to the safe outbox (never sent).
    if provider and provider != "outbox":
        log.warning("Unknown SMS_PROVIDER %r — falling back to safe outbox", provider)
    path = _write_outbox(to_e164, message)
    log.info("SMS outbox backend — wrote message for %s to %s", to_e164, path)
    return {"backend": "outbox", "path": path}
