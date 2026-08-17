"""
HydraShield transactional email.

One entry point — :func:`send_mail` — renders a branded plain-text template
(plus a trivial HTML alternative) from ``email_templates/`` and delivers it:

- **SMTP backend** — when ``SMTP_HOST`` is configured the message is sent via
  STARTTLS SMTP. Env: ``SMTP_HOST``, ``SMTP_PORT`` (default 587),
  ``SMTP_USER``, ``SMTP_PASSWORD`` (legacy ``SMTP_PASS`` also accepted),
  ``SMTP_FROM`` (default ``info@hydrashield.earth``). Credentials come from
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
from typing import Dict, Optional

log = logging.getLogger("hydrashield.mailer")

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "email_templates")

DEFAULT_FROM = "info@hydrashield.earth"


def contact_inbox() -> str:
    """Address that receives contact-form submissions (platform inbox).

    ``CONTACT_INBOX`` env; defaults to ``SMTP_FROM`` (itself defaulting to
    info@hydrashield.earth).
    """
    return os.environ.get("CONTACT_INBOX") or os.environ.get("SMTP_FROM") or DEFAULT_FROM

_TEMPLATE_NAMES = {
    "welcome",
    "email_verification",
    "report_ready",
    "report_delivery",
    "alert",
    "contact_acknowledgement",
    "contact_message",
    "subscription_confirmation",
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

    return {
        "subject": _VAR_RE.sub(_sub, subject),
        "text": _VAR_RE.sub(_sub, body).strip() + "\n",
    }


def _minimal_html(text: str) -> str:
    """Trivial branded HTML alternative: the escaped plain text in a shell."""
    paragraphs = "".join(
        f"<p>{html.escape(p).replace(chr(10), '<br/>')}</p>"
        for p in text.strip().split("\n\n")
        if p.strip()
    )
    return (
        "<html><body style=\"font-family:Helvetica,Arial,sans-serif;color:#0f172a;"
        "font-size:14px;line-height:1.5\">"
        "<p style=\"color:#0ea5e9;font-weight:bold\">HydraShield</p>"
        f"{paragraphs}"
        "<hr style=\"border:none;border-top:1px solid #cbd5e1\"/>"
        "<p style=\"color:#64748b;font-size:11px\">HydraShield — real-data "
        "environmental risk intelligence · info@hydrashield.earth</p>"
        "</body></html>"
    )


def _build_message(to: str, subject: str, text: str) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = os.environ.get("SMTP_FROM") or DEFAULT_FROM
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    msg.add_alternative(_minimal_html(text), subtype="html")
    return msg


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
    msg = _build_message(to, subject, rendered["text"])

    if smtp_configured():
        _send_smtp(msg)
        log.info("Sent '%s' email to %s via SMTP", template, to)
        return {"backend": "smtp", "path": None, "to": to, "subject": subject}

    path = _write_outbox(to, template, msg)
    log.info("SMTP not configured — wrote '%s' email for %s to outbox: %s",
             template, to, path)
    return {"backend": "outbox", "path": path, "to": to, "subject": subject}
