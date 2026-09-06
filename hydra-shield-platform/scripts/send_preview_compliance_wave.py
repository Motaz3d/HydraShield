#!/usr/bin/env python3
"""Talaix - compliance outreach preview test. One sample to the operator inbox before any real outreach."""

from __future__ import annotations

import json
import os
import sys

from pathlib import Path

ROOT = Path(os.path.abspath(__file__)).parent.parent
if str(ROOT) not in sys.path:
  sys.path.insert(0, str(ROOT))

from src.dashboard.mailer import send_mail, render_template, unsubscribe_mailto

# Preview samples go to the official platform inbox — never a personal
# mailbox (repo rule, test-enforced).
DEFAULT_TO = "info@talaix.com"
TEMPLATE = "outreach_sustainability_compliance"
DATA_PATH = ROOT / "marketing" / "outreach" / "compliance_wave1.json"


def build_context():
  entries = json.loads(DATA_PATH.read_text(encoding="utf-8"))
  entry = next(e for e in entries if e.get("to_email"))
  return entry["organization"], {
    "contact_name": entry.get("contact_name") or "there",
    "organization": entry["organization"],
    "country": entry.get("country") or "",
    "identified_problem": entry.get("identified_problem") or "",
    "relevant_capability": entry.get("relevant_capability") or "",
    "recommended_product": entry.get("recommended_product") or "",
    "custom_message": entry.get("custom_message") or "",
    "unsubscribe_url": unsubscribe_mailto(),
  }


def main():
  to_e = os.environ.get("PREVIEW_TO", DEFAULT_TO)
  org, ctx = build_context()
  rendered = render_template(TEMPLATE, ctx)
  result = send_mail(to_e, TEMPLATE, ctx)
  backend = result.get("backend", "unknown")
  print("=" * 60)
  print("PREVIEW sample email to you - NOT part of the wave.")
  print("Sample entry: " + org)
  print("Backend: " + str(backend))
  print("Subject: " + str(rendered["subject"]))
  print("-" * 60)
  print(rendered["text"])
  print("-" * 60)
  if backend == "outbox":
    print("SMTP is not configured here - the message was NOT sent.")
    print("Real delivery requires running this on Vultr where the SMTP")
    print("secrets live. See /opt/hydrashield/.env.")
    print("Preview file: " + str(result.get("path")))
  else:
    print("Delivered to: " + to_e)
    print("Subject again: " + str(result.get("subject")))
  print("After you review this sample, run scripts/send_compliance_wave1.py")
  print("on Vultr (dry run first, then --send). Position Green is submitted")
  print("manually via its official partner form (no published email).")
  return 0


if __name__ == "__main__":
  sys.exit(main())
