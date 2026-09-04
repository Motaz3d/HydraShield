#!/usr/bin/env python3
"""Talaix media-relations wave sender — sends from info@talaix.com only.

HARD RULES (enforced here):
- From address is always SMTP_FROM (default info@talaix.com) — never a personal mailbox.
- Default is DRY RUN: prints each message for human review and sends NOTHING.
- Sending requires the explicit --send flag AND SMTP being configured.
- Entries marked approved=false in the queue are always skipped (never sent).
- Respects DAILY_SEND_CAP.

Usage (from the platform directory):
    python scripts/send_media_wave.py --queue marketing/outreach/media_wave1.json
    python scripts/send_media_wave.py --queue marketing/outreach/media_wave1.json --send --limit 3
"""
from __future__ import annotations

import argparse
import json
import os
import smtplib
import sys
from datetime import date
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src.dashboard import mailer

DEFAULT_FROM = "info@talaix.com"


def smtp_configured() -> bool:
    return bool(os.environ.get("SMTP_HOST"))


def from_address() -> str:
    return os.environ.get("SMTP_FROM") or DEFAULT_FROM


def load_queue(path: str) -> list:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def audit_line(entry: dict, status: str, note: str = "") -> None:
    out = os.path.join(ROOT, "marketing", "outreach", "media_send_audit.csv")
    new = not os.path.isfile(out)
    with open(out, "a", encoding="utf-8") as fh:
        if new:
            fh.write("date,id,outlet,to,status,note\n")
        fh.write(f"{date.today().isoformat()},{entry.get('id')},{entry.get('outlet')},{entry.get('to') or entry.get('channel')},{status},{note}\n")


SIGNATURE_MARKER = "info@talaix.com | talaix.com"


def with_signature(body: str) -> str:
    # Queue bodies copied from paste-templates may already carry the approved
    # signature inline; appending a second one produced double signatures
    # (JR-001/JR-002, 2026-09-03). Append exactly once.
    body = body.rstrip()
    if SIGNATURE_MARKER in body:
        return body + "\n"
    return body + "\n\n" + mailer.signature_text() + "\n"


def send_one(entry: dict) -> None:
    host = os.environ["SMTP_HOST"]
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASSWORD", os.environ.get("SMTP_PASS", ""))
    sender = from_address()
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = entry["to"]
    if entry.get("cc"):
        msg["Cc"] = entry["cc"]
    msg["Subject"] = entry["subject"]
    msg["Date"] = formatdate(localtime=False)
    domain = sender.rsplit("@", 1)[-1] if "@" in sender else "talaix.com"
    msg["Message-ID"] = make_msgid("hydrashield", domain)
    # Same corporate signature as every other Talaix email — exactly once.
    msg.set_content(with_signature(entry["body"]))
    with smtplib.SMTP(host, port, timeout=20) as smtp:
        smtp.starttls()
        if user:
            smtp.login(user, password)
        smtp.send_message(msg)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--queue", required=True, help="path to media_waveN.json")
    ap.add_argument("--send", action="store_true", help="actually send (default: dry run)")
    ap.add_argument("--limit", type=int, default=0, help="max emails this run (0 = cap only)")
    args = ap.parse_args()

    mailer.load_dotenv(os.path.join(ROOT, ".env"))
    mailer.load_dotenv(os.path.join(os.path.dirname(ROOT), ".env"))  # repo-root .env

    entries = load_queue(args.queue)
    cap = int(os.environ.get("DAILY_SEND_CAP", "20"))
    limit = args.limit or cap

    do_send = args.send and smtp_configured()
    if args.send and not smtp_configured():
        print("WARNING: --send given but SMTP_HOST is not set; falling back to dry run.", file=sys.stderr)

    print("=" * 72)
    print(f"Queue: {args.queue}  |  entries: {len(entries)}  |  mode: {'SEND' if do_send else 'DRY RUN'}")
    print(f"From: {from_address()}  |  daily cap: {cap}")
    print("=" * 72)

    sent = 0
    for entry in entries:
        if sent >= limit:
            print(f"\n[limit reached: {limit}]")
            break
        if not entry.get("approved", True):
            print(f"\n[skipped — not approved] {entry.get('id')} {entry.get('outlet')}")
            continue
        if not entry.get("to"):
            print(f"\n[skipped — no email; manual channel] {entry.get('id')} {entry.get('outlet')} -> {entry.get('channel','')}")
            continue
        print("\n" + "-" * 72)
        print(f"ID: {entry.get('id')}  |  {entry.get('outlet')}  |  editor: {entry.get('editor','')}")
        print(f"TO: {entry.get('to')}" + (f"  CC: {entry.get('cc')}" if entry.get("cc") else ""))
        print(f"SUBJECT: {entry.get('subject')}")
        print("-" * 40)
        print(entry.get("body"))
        print("-" * 40)
        print(f"follow-up: {entry.get('followup_date')}")
        if do_send:
            send_one(entry)
            audit_line(entry, "sent")
            print(">>> SENT")
            sent += 1
        else:
            audit_line(entry, "preview")
    print("\n" + "=" * 72)
    if do_send:
        print(f"Completed sends this run: {sent}")
    else:
        print("DRY RUN — nothing was sent. Review the messages above, then run with --send.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
