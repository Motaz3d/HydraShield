#!/usr/bin/env python3
"""Talaix - funder outreach preview test. One sample to the operator inbox before any real outreach."""

from __future__ import annotations

import os
import sys
from datetime import date, timedelta

from pathlib import Path

ROOT = Path(os.path.abspath(__file__)).parent.parent
if str(ROOT) not in sys.path:
  sys.path.insert(0, str(ROOT))

from src.dashboard.mailer import send_mail, render_template

# Preview samples go to the official platform inbox — never a personal
# mailbox (repo rule, test-enforced).
DEFAULT_TO = "info@talaix.com"
TEMPLATE = "outreach_funders"


def build_context():
  followup = (date.today() + timedelta(days=7)).isoformat()
  programme_context = (
    "Why we are writing: the EIC Deep-Tech-for-Climate-Adaptation "
    "challenge funds tools that help communities and financial actors act "
    "on climate risk-and Talaix is the evidence layer underneath that: "
    "multi-hazard screening, exposure counting and monitoring - built "
    "open, traceable to sources, honestly labelled. "
  )
  ask = (
    "Our ask: guidance on how an open-source initiative qualifies for "
    "the EIC SME/start-up route,and how to frame the evidence of market "
    "traction in the short application, plus a possible pilot aligned "
    "with regions under the Adaptation Mission. "
  )
  return {
    "organization": "EIC Accelerator",
    "programme": "EIC Accelerator - Deep Tech for Climate Adaptation",
    "contact_name": "EIC application support team",
    "programme_context": programme_context,
    "ask": ask,
    "followup_date": followup,
    "signer": "Motaz OMARIEN - initiator, Talaix",
  }


def main():
  to_e = os.environ.get("PREVIEW_TO", DEFAULT_TO)
  ctx = build_context()
  rendered = render_template(TEMPLATE, ctx)
  result = send_mail(to_e, TEMPLATE, ctx)
  backend = result.get("backend", "unknown")
  print("=" * 60)
  print("PREVIEW sample email to you - NOT part of the wave.")
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
  print("After you review this sample, we queue the Wave-1 letters")
  print("in marketing/outreach/queue.json for human approval, then send")
  print("in small daily batches. Funding/tender changes verified first.")
  return 0


if __name__ == "__main__":
  sys.exit(main())
