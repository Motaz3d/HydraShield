#!/usr/bin/env python3
"""Read the outreach reply inbox (IMAP) and update the CRM.

For each unseen message, match the sender address to a stored lead contact.
On match:
  - log a 'reply' interaction,
  - set the lead outreach_status to 'replied',
  - cancel pending scheduled outreach and campaign waves (auto-stop).

Unsubscribe heuristic: if the subject or plain-text body contains
"unsubscribe" or "إلغاء الاشتراك", also mark the lead unsubscribed and log
an 'unsubscribe' interaction. The heuristic is labelled for operator review.

Never sends anything; matched messages are marked Seen. Unmatched messages
are left untouched.

Usage:
    python scripts/check_replies.py

Cron (e.g. every 15 minutes):
    */15 * * * * cd <repo>/hydra-shield-platform && .venv/bin/python scripts/check_replies.py
"""

from __future__ import annotations

import email
import email.policy
import imaplib
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dashboard.marketing_store import MarketingStore  # noqa: E402

_UNSUBSCRIBE_KEYWORDS = ("unsubscribe", "إلغاء الاشتراك")

# Lines that mark the start of quoted history in a reply. Everything at or
# below the first marker is the original message echoed back — our own
# footer contains the word "unsubscribe", so scanning quoted text would
# mark every replying lead as unsubscribed.
_QUOTE_STARTERS = (
    "-----original message-----",
    "from:",  # quoted header block of the original
    "________________________________",  # Outlook divider
)
_QUOTE_WROTE_RE = re.compile(r"^on .+wrote:.*$", re.IGNORECASE)


def _top_reply_text(body: str) -> str:
    """Keep only the freshly written part of a reply: drop ">"-quoted lines
    and everything below the first quote separator. The unsubscribe heuristic
    must judge the sender's own words, never our echoed footer."""
    kept = []
    for line in (body or "").splitlines():
        stripped = line.strip()
        low = stripped.lower()
        if stripped.startswith(">"):
            continue
        if _QUOTE_WROTE_RE.match(stripped):
            break
        if any(low.startswith(marker) for marker in _QUOTE_STARTERS):
            break
        kept.append(line)
    return "\n".join(kept)


def _env() -> Dict[str, Optional[str]]:
    return {
        "host": os.environ.get("IMAP_HOST"),
        "port": os.environ.get("IMAP_PORT", "993"),
        "user": os.environ.get("IMAP_USER"),
        "password": os.environ.get("IMAP_PASS") or os.environ.get("IMAP_PASSWORD"),
        "folder": os.environ.get("IMAP_FOLDER", "INBOX"),
    }


def _extract_address(from_header: str) -> Optional[str]:
    """Return the raw email address from a From header."""
    if not from_header:
        return None
    match = re.search(r"<([^>]+)>", from_header)
    if match:
        return match.group(1).lower().strip()
    if "@" in from_header and " " not in from_header:
        return from_header.lower().strip()
    return None


def _body_text(msg: email.message.EmailMessage) -> str:
    """Extract a plain-text body snippet for heuristic checks."""
    parts: List[str] = []
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type() or ""
            if ctype == "text/plain":
                try:
                    payload = part.get_payload(decode=True)
                    if payload:
                        parts.append(payload.decode("utf-8", errors="ignore"))
                except Exception:
                    pass
    else:
        try:
            payload = msg.get_payload(decode=True)
            if payload:
                parts.append(payload.decode("utf-8", errors="ignore"))
        except Exception:
            pass
    return "\n".join(parts)[:2000]


def _has_unsubscribe_keyword(subject: str, body: str) -> bool:
    # Subject in full + only the freshly written top of the body (quoted
    # history is stripped — it contains our own unsubscribe footer).
    combined = f"{subject or ''}\n{_top_reply_text(body)}".lower()
    return any(kw.lower() in combined for kw in _UNSUBSCRIBE_KEYWORDS)


def _load_contacts(store: MarketingStore) -> Dict[str, str]:
    """Map lower-cased email -> lead_slug for all stored contacts."""
    mapping: Dict[str, str] = {}
    for contact in store.list_contacts():
        email_addr = (contact.get("email") or "").lower().strip()
        if email_addr:
            mapping[email_addr] = contact.get("lead_slug")
    return mapping


def _process_message(
    store: MarketingStore,
    email_msg: email.message.EmailMessage,
    contacts: Dict[str, str],
) -> Optional[Tuple[str, bool, bool]]:
    """Process one parsed message. Returns (lead_slug, is_reply, is_unsub) or None."""
    from_addr = _extract_address(email_msg.get("From", ""))
    if not from_addr:
        return None
    lead_slug = contacts.get(from_addr)
    if not lead_slug:
        return None

    subject = email_msg.get("Subject", "")
    date = email_msg.get("Date", "")
    body = _body_text(email_msg)
    unsub = _has_unsubscribe_keyword(subject, body)

    summary = f"Reply from {from_addr}: {subject} ({date})"
    if unsub:
        summary += " — unsubscribe keyword detected (heuristic; review)"

    store.add_interaction(
        lead_slug,
        summary=summary,
        type="reply",
    )
    store.update_state(lead_slug, outreach_status="replied")
    cancelled_scheduled = store.cancel_scheduled_for_lead(lead_slug)
    cancelled_waves = store.cancel_waves_for_lead(lead_slug)
    store.add_interaction(
        lead_slug,
        summary=(
            f"Auto-stopped outreach on reply: {cancelled_scheduled} scheduled row(s) "
            f"and {cancelled_waves} campaign wave(s) cancelled."
        ),
        type="note",
    )

    if unsub:
        store.unsubscribe(lead_slug, reason="reply keyword heuristic")
        store.add_interaction(
            lead_slug,
            summary=f"Unsubscribed via reply heuristic: {from_addr}",
            type="unsubscribe",
        )

    return lead_slug, True, unsub


def main() -> int:
    cfg = _env()
    if not cfg["host"] or not cfg["user"] or not cfg["password"]:
        print("reply check unavailable: IMAP_* not configured")
        return 0

    store = MarketingStore()
    contacts = _load_contacts(store)
    if not contacts:
        print("reply check skipped: no stored contacts to match against")
        return 0

    scanned = matched = replies = unsubscribed = 0
    try:
        port = int(cfg["port"])
        mail = imaplib.IMAP4_SSL(str(cfg["host"]), port)
        mail.login(str(cfg["user"]), str(cfg["password"]))
        mail.select(cfg["folder"])

        status, data = mail.search(None, "UNSEEN")
        if status != "OK" or not data or not data[0]:
            print("0 unseen messages")
            mail.close()
            mail.logout()
            return 0

        msg_ids = data[0].split()
        for msg_id in msg_ids:
            scanned += 1
            # BODY.PEEK[] — never sets \Seen implicitly. A plain (RFC822)
            # fetch marks every scanned message as read on the server
            # (RFC 3501), which made inbox mail look "opened by itself".
            # Only a matched reply earns the explicit \Seen below.
            status, msg_data = mail.fetch(msg_id, "(BODY.PEEK[])")
            if status != "OK" or not msg_data:
                continue
            raw = msg_data[0][1] if isinstance(msg_data[0], tuple) else None
            if raw is None:
                continue
            # policy.default is required: the legacy compat32 parser returns
            # a plain Message, which the isinstance gate below rejects —
            # with it, no message was ever processed at all.
            parsed = email.message_from_bytes(raw, policy=email.policy.default)
            if not isinstance(parsed, email.message.EmailMessage):
                continue
            result = _process_message(store, parsed, contacts)
            if result:
                matched += 1
                replies += 1
                if result[2]:
                    unsubscribed += 1
                mail.store(msg_id, "+FLAGS", "\\Seen")

        mail.close()
        mail.logout()
    except Exception as exc:
        print(f"reply check failed: {exc}")
        return 1

    print(
        f"Replies checked: {scanned} scanned, {matched} matched, "
        f"{replies} replies logged, {unsubscribed} unsubscribed"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
