#!/usr/bin/env python3
"""Build marketing/outreach/consultants_wave1.json — the consultants channel
wave (operator-sequenced 2026-09-07: AFTER the investor and CSRD/insurance
waves finish; sends start 2026-09-14 when DAILY_SEND_CAP rises to 20).

Source data (no new fabrication):
- marketing/leads/*.json segment "consultants" — harvested pre-pivot,
  never emailed (fresh), with lead-file evidence fields.
- lead_contacts rows with verification OBSERVED. DPO/privacy mailboxes are
  excluded; general/role mailboxes are preferred over personal ones.

Pacing: 15/day (moderate, operator guidance) on 2026-09-14/15/16,
15-minute stagger from 07:05 UTC (inside OUTREACH_WINDOW 07:00–17:00 UTC).
"""
from __future__ import annotations

import glob
import json
import os
import re
import sys
from datetime import datetime, timedelta

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from src.dashboard.marketing_store import MarketingStore  # noqa: E402

OUT_PATH = os.path.join(BASE, "marketing", "outreach", "consultants_wave1.json")

_BAD_LOCAL = re.compile(
    r"^(dpo|datenschutz|privacy|protecciondatos|gdpr|contactdpo|legal|ethics)",
    re.IGNORECASE)
_GENERAL_LOCAL = re.compile(
    r"^(info|contact|hello|office|mail|service|comercial|welcome|post|"
    r"enquiries|general|sekretariat|reception|connect)", re.IGNORECASE)
_EU_UK = {"AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE",
          "GR", "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT",
          "RO", "SK", "SI", "ES", "SE", "GB", "CH", "NO", "IS", "LI"}

_FIRST_SEND = datetime(2026, 9, 14, 7, 5)  # UTC — after investor+CSRD waves
_PER_DAY = 15
_STAGGER_MIN = 15

# Leads that must not enter the wave even when data exists.
_DROP = {
    "deloitte-tohmatsu",   # Big-4: competitor/channel, not a cold-pitch target
    "q140677831",          # unresolved Wikidata QID — cannot address honestly
}


def _capability(country: str) -> str:
    base = ("site-level multi-hazard evidence — ten hazards, sources, dates "
            "and engine versions — that drops straight into client "
            "deliverables")
    if (country or "").upper() in _EU_UK:
        return (base + ", plus machine-readable XBRL from our CsrdTX rules "
                "engine for clients reporting under CSRD/ESRS E1")
    return (base + "; clients with EU reporting duties (CSRD/ESRS E1) also "
            "get machine-readable XBRL from our CsrdTX rules engine")


def main() -> int:
    store = MarketingStore()
    conn = store._connect()
    contacted = {r[0] for r in conn.execute(
        "SELECT DISTINCT lead_slug FROM lead_interactions WHERE type='email'")}
    excluded = {r[0] for r in conn.execute(
        "SELECT lead_slug FROM lead_state WHERE excluded=1 OR unsubscribed=1")}

    entries = []
    for path in sorted(glob.glob(os.path.join(BASE, "marketing", "leads", "*.json"))):
        try:
            with open(path, encoding="utf-8") as fh:
                lead = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        if (lead.get("segment") or "") != "consultants":
            continue
        slug = lead.get("slug") or os.path.basename(path)[:-5]
        if slug in contacted or slug in excluded or slug in _DROP:
            continue
        rows = conn.execute(
            "SELECT email, source, created_at FROM lead_contacts"
            " WHERE lead_slug=? AND verification='OBSERVED'", (slug,)).fetchall()
        usable = [r for r in rows if not _BAD_LOCAL.match(r[0].split("@")[0])]
        if not usable:
            continue
        usable.sort(key=lambda r: 0 if _GENERAL_LOCAL.match(r[0].split("@")[0]) else 1)
        email, source, created_at = usable[0]
        if not (source or "").startswith("http"):
            source = lead.get("website") or ""
        country = (lead.get("country") or "").upper()
        org = lead.get("organization") or slug
        role = (lead.get("decision_maker_role") or "").strip()
        entries.append({
            "slug": slug,
            "organization": org,
            "country": country,
            "to_email": email,
            "contact_name": role if role else f"{org} team",
            "claim_status": "OBSERVED",
            "source": source or lead.get("website") or "",
            "date_checked": (created_at or "")[:10] or "2026-09-07",
            "identified_problem": lead.get("identified_problem") or "",
            "relevant_capability": _capability(country),
            "custom_message": ("If the sample earns a place in your toolkit, "
                               "we can discuss partner terms for client "
                               "engagements."),
        })

    for i, entry in enumerate(entries):
        day_offset, slot = divmod(i, _PER_DAY)
        send_at = _FIRST_SEND + timedelta(days=day_offset,
                                          minutes=_STAGGER_MIN * slot)
        entry["send_at"] = send_at.isoformat(timespec="seconds")

    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        json.dump(entries, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    print(f"wrote {len(entries)} entries -> {OUT_PATH}")
    days = {}
    for e in entries:
        days[e["send_at"][:10]] = days.get(e["send_at"][:10], 0) + 1
    print("pacing:", days)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
