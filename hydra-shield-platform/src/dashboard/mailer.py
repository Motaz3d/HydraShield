"""
Talaix transactional email.

One entry point — :func:`send_mail` — renders a branded plain-text template
(plus a branded HTML alternative carrying the email lockup) from ``email_templates/`` and delivers it:

- **SMTP backend** — when ``SMTP_HOST`` is configured the message is sent via
  STARTTLS SMTP. Env: ``SMTP_HOST``, ``SMTP_PORT`` (default 587),
  ``SMTP_USER``, ``SMTP_PASSWORD`` (legacy ``SMTP_PASS`` also accepted),
  ``SMTP_FROM`` (default ``info@talaix.com``). Credentials come from
  the environment only; none are ever assumed or invented.
- **Outbox (dev) backend** — when ``SMTP_HOST`` is unset the message is
  written to ``data/outbox/<timestamp>_<template>_<hash>.eml`` (created on
  demand; override with ``HYDRASHIELD_OUTBOX_DIR``) and logged. It is NEVER
  sent. Tests use this backend and assert on the outbox files.

Templates are plain ``.txt`` files whose first line is ``Subject: …``; both
subject and body support ``{{variable}}`` substitution from the context dict
(stdlib only — no new dependencies).
"""

from __future__ import annotations

import hashlib
import html
import logging
import os
import re
import time
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from typing import Dict, Optional

log = logging.getLogger("hydrashield.mailer")

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "email_templates")

DEFAULT_FROM = "info@talaix.com"


def contact_inbox() -> str:
    """Address that receives contact-form submissions (platform inbox).

    ``CONTACT_INBOX`` env; defaults to ``SMTP_FROM`` (itself defaulting to
    info@talaix.com).
    """
    return os.environ.get("CONTACT_INBOX") or os.environ.get("SMTP_FROM") or DEFAULT_FROM

_TEMPLATE_NAMES = {
    "welcome",
    "email_verification",
    "password_reset",
    "report_ready",
    "report_delivery",
    "alert",
    "contact_acknowledgement",
    "contact_message",
    "admin_notification",
    "operator_notification",
    "subscription_confirmation",
    "subscription_confirmation_paid",
    "subscription_cancellation",
    "subscription_ended",
    "outreach_generic",
    "outreach_banking",
    "outreach_insurance",
    "outreach_investment",
    "outreach_real_estate",
    "outreach_environmental_consulting",
    "outreach_governments",
    "outreach_funders",
    "outreach_journals",
    "followup_1",
    "followup_2",
}

_VAR_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")


def _outbox_dir() -> str:
    return os.environ.get(
        "HYDRASHIELD_OUTBOX_DIR",
        os.path.join(os.path.dirname(__file__), "..", "..", "data", "outbox"),
    )


def smtp_configured() -> bool:
    """Return True when an SMTP host is configured (real delivery possible)."""
    return bool(os.environ.get("SMTP_HOST"))


def load_dotenv(path: str) -> None:
    """Load KEY=VALUE pairs from a .env file into ``os.environ`` without
    overwriting variables that are already set. Shared by the operator wave
    scripts so they behave identically on the server (where ``.env`` holds
    the SMTP secrets) and locally."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


def render_template(template: str, context: Optional[Dict] = None) -> Dict[str, str]:
    """
    Render ``email_templates/<template>.txt`` with ``context``.

    Returns ``{"subject": …, "text": …}``. Unknown ``{{variables}}`` render
    as empty strings; missing templates raise ``FileNotFoundError``.
    """
    if template not in _TEMPLATE_NAMES:
        raise ValueError(f"Unknown email template: {template!r}")
    path = os.path.join(TEMPLATES_DIR, f"{template}.txt")
    with open(path, "r", encoding="utf-8") as fh:
        raw = fh.read()
    first, _, body = raw.partition("\n")
    subject = first[len("Subject:"):].strip() if first.startswith("Subject:") else template
    context = context or {}

    def _sub(match: "re.Match") -> str:
        return str(context.get(match.group(1), ""))

    text = _VAR_RE.sub(_sub, body).strip()
    # Optional variables (e.g. custom_message) often render empty and would
    # leave a visible double blank gap — collapse 3+ newlines into one
    # paragraph break.
    text = re.sub(r"\n{3,}", "\n\n", text)
    return {
        "subject": _VAR_RE.sub(_sub, subject),
        "text": text + "\n",
    }


_BRAND_NAVY = "#1E2C4A"
_BRAND_TEAL = "#47B3A8"

# Corporate signature — appended to EVERY outgoing message (plain text and
# HTML alternative). In the HTML part the signature logo (logS100.png) leads
# the block; keep in sync with website/assets/brand/.
_SIGNATURE_LINES = (
    "Talaix",
    "Earth Observation & Environmental Risk",
    "Financial Decision Intelligence",
    "Luxembourg-based technology initiative",
    "info@talaix.com | talaix.com",
)
_SIGNATURE_TEXT = "--\n" + "\n".join(_SIGNATURE_LINES)

# Signature logo is EMBEDDED as a CID attachment so it renders even before
# the asset is deployed on the public site (hosted URL is the fallback).
_SIGNATURE_LOGO_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "website", "assets", "brand", "logS100.png")
_SIGNATURE_CID = "logS100@talaix"


def _signature_logo_url() -> str:
    """Hosted signature logo (``logS100.png`` — T mark + teal dot).
    Follows ``HYDRASHIELD_BASE_URL`` like the header lockup."""
    base = os.environ.get("HYDRASHIELD_BASE_URL", "https://talaix.com").rstrip("/")
    return f"{base}/assets/brand/logS100.png"


def signature_text() -> str:
    """The corporate plain-text signature block (``--`` separator included).
    Public so operator wave scripts can append the exact same signature the
    mailer uses — one signature, one source."""
    return _SIGNATURE_TEXT


def unsubscribe_mailto() -> str:
    """mailto: link that opts a recipient out of outreach.

    A reply to this address with subject "unsubscribe" is picked up by
    ``scripts/check_replies.py`` and stops every pending send to the lead.
    """
    inbox = (os.environ.get("SMTP_FROM") or DEFAULT_FROM).replace(" ", "")
    return f"mailto:{inbox}?subject=unsubscribe"


# Cold-outreach template families carry a List-Unsubscribe header (RFC 2369)
# in addition to the human-readable footer line.
_UNSUBSCRIBE_HEADER_PREFIXES = ("outreach_", "followup_")


def _signature_logo_src() -> str:
    """CID reference when the logo file is available locally (embedded on
    send), otherwise the hosted URL."""
    if os.path.isfile(_SIGNATURE_LOGO_PATH):
        return f"cid:{_SIGNATURE_CID}"
    return _signature_logo_url()


def _signature_html() -> str:
    """Signature block for the HTML alternative: logo first, then the
    Talaix descriptor lines (brand navy; links in brand teal)."""
    name, tag1, tag2, tag3, _contact = _SIGNATURE_LINES
    return (
        '<div style="margin-top:28px">'
        f'<img src="{_signature_logo_src()}" width="64" alt="Talaix" '
        'style="display:block;margin:0 0 8px"/>'
        f'<p style="margin:0;font-weight:bold;color:{_BRAND_NAVY}">'
        f"{html.escape(name)}</p>"
        f'<p style="margin:0;color:{_BRAND_NAVY};font-size:12px;line-height:1.5">'
        f"{html.escape(tag1)}<br/>{html.escape(tag2)}<br/>{html.escape(tag3)}<br/>"
        f'<a href="mailto:info@talaix.com" style="color:{_BRAND_TEAL};'
        'text-decoration:none">info@talaix.com</a> | '
        f'<a href="https://talaix.com" style="color:{_BRAND_TEAL};'
        'text-decoration:none">talaix.com</a></p>'
        "</div>"
    )


def _minimal_html(text: str) -> str:
    """Branded HTML alternative: the escaped plain text in the Talaix
    shell (corporate signature with embedded logo, brand navy/teal).
    No header image — the signature block is the only branding."""
    paragraphs = "".join(
        f"<p>{html.escape(p).replace(chr(10), '<br/>')}</p>"
        for p in text.strip().split("\n\n")
        if p.strip()
    )
    return (
        "<!DOCTYPE html>"
        '<html lang="en"><head><meta charset="utf-8"/>'
        '<meta name="viewport" content="width=device-width,initial-scale=1"/>'
        "</head>"
        '<body style="margin:0;padding:0;background:#f1f5f9">'
        '<div style="max-width:560px;margin:0 auto;padding:24px;'
        f'font-family:Helvetica,Arial,sans-serif;color:{_BRAND_NAVY};'
        'font-size:14px;line-height:1.6">'
        f"{paragraphs}"
        f"{_signature_html()}"
        "</div></body></html>"
    )


def _build_message(to: str, subject: str, text: str, template: str = "") -> EmailMessage:
    msg = EmailMessage()
    sender = from_for_template(template)
    msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = subject
    # Standards headers every professional sender sets explicitly rather
    # than leaving them to the relay: RFC 5322 Date and Message-ID.
    msg["Date"] = formatdate(time.time(), localtime=False)
    domain = sender.rsplit("@", 1)[-1] if "@" in sender else "talaix.com"
    msg["Message-ID"] = make_msgid("hydrashield", domain)
    # Cold outreach carries a machine-readable opt-out (RFC 2369) — the same
    # mailto the human-readable footer asks for.
    if template.startswith(_UNSUBSCRIBE_HEADER_PREFIXES):
        msg["List-Unsubscribe"] = f"<{unsubscribe_mailto()}>"
    msg.set_content(text.rstrip() + "\n\n" + _SIGNATURE_TEXT + "\n")
    msg.add_alternative(_minimal_html(text), subtype="html")
    # Embed the signature logo (CID) so it renders without any public asset.
    try:
        with open(_SIGNATURE_LOGO_PATH, "rb") as fh:
            logo = fh.read()
    except OSError:
        logo = None
    if logo is not None:
        html_part = msg.get_payload()[-1]
        html_part.add_related(
            logo, maintype="image", subtype="png",
            cid=f"<{_SIGNATURE_CID}>", filename="logS100.png")
    return msg


def from_for_template(template: str) -> str:
    """From address for a template: per-template alias override via
    ``SMTP_FROM_<TEMPLATE>`` (e.g. ``SMTP_FROM_ALERT=alerts@talaix.com``),
    falling back to ``SMTP_FROM`` then the default info@ address.

    Alias send-as must be configured in Google Workspace by the operator —
    the platform never invents sender identities.
    """
    override = os.environ.get(f"SMTP_FROM_{(template or '').upper()}")
    return override or os.environ.get("SMTP_FROM") or DEFAULT_FROM


def _send_smtp(msg: EmailMessage) -> None:
    import smtplib

    host = os.environ["SMTP_HOST"]
    port = int(os.environ.get("SMTP_PORT", "587"))
    with smtplib.SMTP(host, port, timeout=20) as smtp:
        smtp.starttls()
        user = os.environ.get("SMTP_USER")
        if user:
            # SMTP_PASSWORD is the canonical name; legacy SMTP_PASS accepted.
            smtp.login(user, os.environ.get("SMTP_PASSWORD", os.environ.get("SMTP_PASS", "")))
        smtp.send_message(msg)


def _write_outbox(to: str, template: str, msg: EmailMessage) -> str:
    outdir = _outbox_dir()
    os.makedirs(outdir, exist_ok=True)
    digest = hashlib.sha256(
        f"{to}|{msg['Subject']}|{msg.get_body(('plain',)).get_content()}".encode("utf-8")
    ).hexdigest()[:10]
    stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime()) + f"{int(time.time() * 1e6) % 1000000:06d}"
    path = os.path.join(outdir, f"{stamp}_{template}_{digest}.eml")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(msg.as_string())
    return path


def send_mail(
    to: str,
    template: str,
    context: Optional[Dict] = None,
    subject_override: Optional[str] = None,
) -> Dict:
    """
    Render and deliver an email. Returns a delivery descriptor::

        {"backend": "smtp",   "path": None}          — sent via STARTTLS SMTP
        {"backend": "outbox", "path": "<eml path>"}  — dev backend, never sent

    Raises on template/render errors; SMTP errors propagate to the caller
    (callers record/log failures honestly).
    """
    rendered = render_template(template, context)
    subject = subject_override or rendered["subject"]
    msg = _build_message(to, subject, rendered["text"], template=template)

    if smtp_configured():
        _send_smtp(msg)
        log.info("Sent '%s' email to %s via SMTP", template, to)
        return {"backend": "smtp", "path": None, "to": to, "subject": subject}

    path = _write_outbox(to, template, msg)
    log.info("SMTP not configured — wrote '%s' email for %s to outbox: %s",
             template, to, path)
    return {"backend": "outbox", "path": path, "to": to, "subject": subject}


# ---------------------------------------------------------------------------
# Operator notifications (platform → info@talaix.com)
# ---------------------------------------------------------------------------

# Anti-flood bucket: at most this many operator emails per kind per hour
# (in-memory, per-process — deliberately simple; the outbox/SMTP path stays
# the single delivery channel).
_OPERATOR_BUCKET_LIMIT = 20
_operator_bucket: Dict[str, list] = {}


def operator_notify(subject: str, message: str, kind: str = "general") -> Dict:
    """
    Notify the platform operator (info@talaix.com via
    :func:`contact_inbox`) of a platform event: registration, contact
    message, report generated, alert condition, subscription, material
    change at a monitored location.

    Content rules: ``subject``/``message`` must carry operational facts
    only (location, type, IDs, timestamps) — NEVER passwords, tokens,
    SMTP credentials, or user secrets. Delivery uses the same mailer
    backend as everything else (safe outbox until SMTP env is set).
    """
    now = time.time()
    bucket = _operator_bucket.setdefault(kind, [])
    bucket[:] = [t for t in bucket if t > now - 3600.0]
    if len(bucket) >= _OPERATOR_BUCKET_LIMIT:
        log.warning("Operator notification suppressed (bucket full) kind=%s", kind)
        return {"backend": "suppressed", "path": None, "to": None, "subject": subject}
    bucket.append(now)
    return send_mail(
        contact_inbox(),
        "operator_notification",
        {"subject": subject, "message": message},
    )
