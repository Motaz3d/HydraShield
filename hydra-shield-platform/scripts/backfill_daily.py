#!/usr/bin/env python3
"""Backfill scheduled outreach to guarantee a daily target of queued emails.

Reads the lead archive (marketing/leads/*.json) and the marketing store,
then tops up each day's scheduled_outreach rows to the configured daily target.
Already-scheduled/approved waves take their share first; any remaining share
is filled from the archive in strict segment priority.

Priority order (each segment exhausted before the next):
  consultants / environmental_consulting -> outreach_environmental_consulting
  sustainability_compliance              -> outreach_sustainability_compliance
  eudr_operators                         -> outreach_sustainability_compliance
  insurance                              -> outreach_insurance
  banking                                -> outreach_banking
  real_estate                            -> outreach_real_estate
  governments                            -> outreach_governments
  investment                             -> outreach_investment
Segments outside this list (e.g. research_centers) are reported as held.

Workdays only (operator directive 2026-09-12): no rows are scheduled on
Saturday/Sunday (UTC); the processor likewise defers weekend sends to Monday.

Safety rules:
- DRY RUN by default; writing requires --schedule.
- No real email is sent here — rows are queued for the cron processor.
- Idempotent: re-running never double-queues the same lead or campaign tag.
- Only verified (OBSERVED) published mailboxes are used.
- DPO/privacy/abuse mailboxes are rejected; general/role mailboxes are preferred.
- Segments with no current strategy are reported as held, not emailed.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from datetime import datetime, timedelta
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from src.dashboard import mailer  # noqa: E402
from src.dashboard.marketing_store import MarketingStore  # noqa: E402

LEADS_DIR = os.path.join(BASE, "marketing", "leads")
OUTREACH_DIR = os.path.join(BASE, "marketing", "outreach")

_BAD_LOCAL = re.compile(
    r"^(dpo|datenschutz|privacy|protecciondatos|gdpr|contactdpo|legal|ethics|abuse)",
    re.IGNORECASE)
_GENERAL_LOCAL = re.compile(
    r"^(info|contact|hello|office|mail|service|comercial|welcome|post|"
    r"enquiries|general|sekretariat|reception|connect)", re.IGNORECASE)
# Verification states the backfill may schedule: OBSERVED (seen literally on an
# official page) and operator_collected (operator-manual research the operator
# has vouched for as verified — e.g. the Luxembourg archive).
_VERIFIED = {"OBSERVED", "operator_collected"}

_EU_UK = {"AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE",
          "GR", "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT",
          "RO", "SK", "SI", "ES", "SE", "GB", "CH", "NO", "IS", "LI"}

# Current segment templates. Everything not in this priority list is held
# because there is no current outreach strategy for it (e.g. research_centers).
_CONSULTING_TEMPLATE = "outreach_environmental_consulting"
_COMPLIANCE_TEMPLATE = "outreach_sustainability_compliance"
_INSURANCE_TEMPLATE = "outreach_insurance"
_BANKING_TEMPLATE = "outreach_banking"
_REAL_ESTATE_TEMPLATE = "outreach_real_estate"
_GOVERNMENTS_TEMPLATE = "outreach_governments"
_INVESTMENT_TEMPLATE = "outreach_investment"

# Segment priority order. Segments mapping to the same template are grouped
# so they can be exhausted before moving to the next template family.
_PRIORITY: List[Tuple[Tuple[str, ...], str]] = [
    (("sustainability_compliance",), _COMPLIANCE_TEMPLATE),
    (("eudr_operators",), _COMPLIANCE_TEMPLATE),
    (("insurance",), _INSURANCE_TEMPLATE),
    (("banking",), _BANKING_TEMPLATE),
    (("real_estate",), _REAL_ESTATE_TEMPLATE),
    (("governments",), _GOVERNMENTS_TEMPLATE),
    (("investment",), _INVESTMENT_TEMPLATE),
    (("consultants", "environmental_consulting"), _CONSULTING_TEMPLATE),
]

_STAGGER_MIN = 5
_WINDOW_START_H = int(os.environ.get("OUTREACH_WINDOW_START") or 7)
_WINDOW_END_H = int(os.environ.get("OUTREACH_WINDOW_END") or 17)


def _capability(country: str, template: str) -> str:
    """Capability line tailored to the template and region."""
    country = (country or "").upper()
    is_eu_uk = country in _EU_UK

    if template == _INSURANCE_TEMPLATE:
        return ("per-location multi-hazard evidence for underwriting files "
                "and ORSA documentation — hazards, historical events by year, "
                "insured-exposure layers, every value with source and evidence status")

    if template == _BANKING_TEMPLATE:
        base = ("ten-hazard screening of collateral and loan-book locations "
                "from Earth observation and official open data — every value "
                "with source, date and evidence status")
        if is_eu_uk:
            return (base + ", ready for EBA Pillar 3 ESG, EU Taxonomy DNSH "
                    "and CSRD/ESRS E1 evidence files")
        return (base + ", ready for physical-risk credit files and disclosure "
                "workflows; EU collateral also receives CSRD/EU Taxonomy context")

    if template == _INVESTMENT_TEMPLATE:
        base = ("portfolio-level physical-risk screening per asset, anywhere on "
                "Earth, from Earth observation and official open data — every "
                "value with source, date and evidence status")
        if is_eu_uk:
            return (base + ", formatted as defensible input for SFDR and EU "
                    "Taxonomy DNSH due-diligence")
        return (base + ", formatted as defensible input for physical-risk "
                "due-diligence and client reporting")

    if template == _REAL_ESTATE_TEMPLATE:
        base = ("site-coordinate hazard screening for acquisitions and assets "
                "from Earth observation and official open data — every value "
                "with source, date and evidence status")
        if is_eu_uk:
            return (base + ", plus CSRD/ESRS E1 physical-risk evidence blocks "
                    "where disclosure obligations apply")
        return (base + ", ready for acquisition screening, planning support "
                "and asset monitoring")

    if template == _GOVERNMENTS_TEMPLATE:
        return ("multi-hazard exposure screening and event evidence for "
                "municipalities and regions — population, buildings, transport, "
                "energy, water and critical infrastructure — every value with "
                "source, date and evidence status, ready for RRF, LIFE and "
                "adaptation-programme applications")

    if template == _COMPLIANCE_TEMPLATE:
        base = ("site-coordinate hazard screening from Earth observation and "
                "official open data — every value with source, date and evidence status")
        if is_eu_uk:
            return (base + ", plus machine-readable XBRL from our CsrdTX rules "
                    "engine for CSRD/ESRS E1 disclosure")
        return (base + "; EU-reporting sites also receive machine-readable XBRL "
                "from our CsrdTX rules engine for CSRD/ESRS E1 disclosure")

    # _CONSULTING_TEMPLATE
    base = ("site-level multi-hazard evidence — ten hazards, sources, dates "
            "and engine versions — that drops straight into client deliverables")
    if is_eu_uk:
        return (base + ", plus machine-readable XBRL from our CsrdTX rules "
                "engine for clients reporting under CSRD/ESRS E1")
    return (base + "; clients with EU reporting duties (CSRD/ESRS E1) also "
            "get machine-readable XBRL from our CsrdTX rules engine")


def _campaign_tag(day: datetime) -> str:
    return f"auto-backfill-{day.date().isoformat()}"


def _load_leads() -> Dict[str, dict]:
    """Load the whole lead archive into a slug -> lead dict."""
    leads: Dict[str, dict] = {}
    for path in sorted(glob.glob(os.path.join(LEADS_DIR, "*.json"))):
        try:
            with open(path, encoding="utf-8") as fh:
                lead = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        slug = lead.get("slug") or os.path.basename(path)[:-5]
        leads[slug] = lead
    return leads


def _outreach_slugs() -> Set[str]:
    """Slugs that already appear in an approved outreach wave file."""
    slugs: Set[str] = set()
    for path in glob.glob(os.path.join(OUTREACH_DIR, "*.json")):
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, list):
            continue
        for entry in data:
            if isinstance(entry, dict) and entry.get("slug"):
                slugs.add(entry["slug"])
    return slugs


def _contact_sort_key(email: str) -> int:
    local = email.split("@")[0]
    return 0 if _GENERAL_LOCAL.match(local) else 1


def _eligible_email(contacts: Sequence[tuple]) -> Optional[Tuple[str, str, str, str]]:
    """Pick the best OBSERVED, non-DPO contact.

    Returns (email, source, created_at, date_checked) or None.
    """
    usable = [
        (email, source, created_at)
        for email, source, created_at, verification in contacts
        if verification in _VERIFIED and not _BAD_LOCAL.match(email.split("@")[0])
    ]
    if not usable:
        return None
    usable.sort(key=lambda r: _contact_sort_key(r[0]))
    email, source, created_at = usable[0]
    return email, source or "", created_at or "", ""


def _gather_exclusions(store: MarketingStore) -> Tuple[Set[str], Set[str], Set[str], Set[str]]:
    """Return (emailed, excluded/unsubscribed, any_scheduled_status, outreach_file_slugs)."""
    conn = store._connect()
    emailed = {r[0] for r in conn.execute(
        "SELECT DISTINCT lead_slug FROM lead_interactions WHERE type='email'")}
    excluded = {r[0] for r in conn.execute(
        "SELECT lead_slug FROM lead_state WHERE excluded=1 OR unsubscribed=1")}
    # Any row in scheduled_outreach — scheduled or sent — blocks re-use. We
    # extend to every status because a failed/cancelled row is still a known
    # attempt and should not be silently retried against a different template.
    scheduled_any = {r[0] for r in conn.execute(
        "SELECT DISTINCT lead_slug FROM scheduled_outreach")}
    outreach_slugs = _outreach_slugs()
    return emailed, excluded, scheduled_any, outreach_slugs


def _contacts_by_slug(store: MarketingStore) -> Dict[str, List[Tuple[str, str, str, str]]]:
    """Map lead_slug -> list of (email, source, created_at, verification)."""
    by_slug: Dict[str, List[Tuple[str, str, str, str]]] = {}
    for c in store.list_contacts():
        by_slug.setdefault(c["lead_slug"], []).append(
            (c["email"], c.get("source") or "", c.get("created_at") or "",
             c.get("verification") or "")
        )
    return by_slug


def _emailable_pool(leads: Dict[str, dict], contacts_by_slug: Dict[str, List],
                    emailed: Set[str], excluded: Set[str], scheduled_any: Set[str],
                    outreach_slugs: Set[str]) -> Dict[str, Dict]:
    """Pre-compute eligibility per lead and per-segment summaries."""
    pool: Dict[str, Dict] = {}
    for slug, lead in leads.items():
        segment = lead.get("segment") or "None"
        info = pool.setdefault(segment, {
            "total": 0,
            "emailable": 0,
            "reasons": {
                "no_observed_contact": 0,
                "dpo_or_privacy_mailbox": 0,
                "already_emailed": 0,
                "excluded_or_unsubscribed": 0,
                "already_scheduled": 0,
                "in_outreach_wave_file": 0,
            },
        })
        info["total"] += 1
        if slug in emailed:
            info["reasons"]["already_emailed"] += 1
            continue
        if slug in excluded:
            info["reasons"]["excluded_or_unsubscribed"] += 1
            continue
        if slug in scheduled_any:
            info["reasons"]["already_scheduled"] += 1
            continue
        if slug in outreach_slugs:
            info["reasons"]["in_outreach_wave_file"] += 1
            continue
        contacts = contacts_by_slug.get(slug, [])
        observed = [c for c in contacts if c[3] in _VERIFIED]
        if not observed:
            info["reasons"]["no_observed_contact"] += 1
            continue
        if all(_BAD_LOCAL.match(email.split("@")[0]) for email, _, _, _ in observed):
            info["reasons"]["dpo_or_privacy_mailbox"] += 1
            continue
        info["emailable"] += 1
    return pool


def _select_for_segment(leads: Dict[str, dict], contacts_by_slug: Dict[str, List],
                        segments: Tuple[str, ...], template: str,
                        exclude_slugs: Set[str], n: int) -> List[dict]:
    """Return up to n backfill entries for the given segment group."""
    selected: List[dict] = []
    for slug, lead in leads.items():
        if len(selected) >= n:
            break
        if (lead.get("segment") or "") not in segments:
            continue
        if slug in exclude_slugs:
            continue
        contacts = contacts_by_slug.get(slug, [])
        contact = _eligible_email(contacts)
        if contact is None:
            continue
        email, source, created_at, _ = contact
        country = (lead.get("country") or "").upper()
        org = lead.get("organization") or slug
        role = (lead.get("decision_maker_role") or "").strip()
        date_checked = (created_at or lead.get("date_checked") or "")[:10]
        if not date_checked:
            date_checked = datetime.utcnow().date().isoformat()
        source = source if source.startswith("http") else (lead.get("website") or lead.get("source") or "")
        selected.append({
            "slug": slug,
            "segment": segments[0],
            "organization": org,
            "country": country,
            "to_email": email,
            "contact_name": role if role else f"{org} team",
            "claim_status": "OBSERVED",
            "source": source,
            "date_checked": date_checked,
            "identified_problem": lead.get("identified_problem") or "",
            "relevant_capability": _capability(country, template),
            "custom_message": "",
            "template": template,
        })
        exclude_slugs.add(slug)
    return selected


def _slots_for_day(day: datetime, needed: int, store: MarketingStore) -> List[str]:
    """Return ISO send_at strings for the day, after existing scheduled rows."""
    window_start = day.replace(hour=_WINDOW_START_H, minute=0, second=0, microsecond=0)
    window_end = day.replace(hour=_WINDOW_END_H, minute=0, second=0, microsecond=0)
    earliest = window_start + timedelta(minutes=5)  # no earlier than 07:05

    date_prefix = day.date().isoformat()
    conn = store._connect()
    row = conn.execute(
        "SELECT send_at FROM scheduled_outreach"
        " WHERE status = 'scheduled' AND send_at LIKE ?"
        " ORDER BY send_at DESC LIMIT 1",
        (f"{date_prefix}%",),
    ).fetchone()
    if row:
        latest = datetime.fromisoformat(row[0])
        start = max(earliest, latest + timedelta(minutes=_STAGGER_MIN))
    else:
        start = earliest

    slots: List[str] = []
    while len(slots) < needed:
        if start >= window_end:
            break
        slots.append(start.isoformat(timespec="seconds"))
        start += timedelta(minutes=_STAGGER_MIN)
    return slots


def _existing_backfill_count(day: datetime, store: MarketingStore) -> int:
    """Number of backfill rows already scheduled for this day (by campaign tag)."""
    tag = _campaign_tag(day)
    date_prefix = day.date().isoformat()
    rows = store.list_scheduled(status="scheduled")
    return sum(
        1 for r in rows
        if r["send_at"].startswith(date_prefix)
        and (r.get("context") or {}).get("campaign") == tag
    )


def _plan_day(day: datetime, target: int, store: MarketingStore,
              leads: Dict[str, dict], contacts_by_slug: Dict[str, List],
              pool: Dict[str, Dict], now: datetime) -> dict:
    """Plan backfill for one day without writing."""
    result = {
        "day": day.date().isoformat(),
        "target": target,
        "skipped": False,
        "reason": "",
        "existing_scheduled": 0,
        "sent_today": 0,
        "deficit": 0,
        "segments": {},
        "entries": [],
    }

    window_start = day.replace(hour=_WINDOW_START_H, minute=0, second=0, microsecond=0)
    window_end = day.replace(hour=_WINDOW_END_H, minute=0, second=0, microsecond=0)

    if now >= window_end:
        result["skipped"] = True
        result["reason"] = "send window has ended"
        return result

    date_prefix = day.date().isoformat()
    conn = store._connect()
    scheduled = conn.execute(
        "SELECT COUNT(*) FROM scheduled_outreach"
        " WHERE status = 'scheduled' AND send_at LIKE ?",
        (f"{date_prefix}%",),
    ).fetchone()[0] or 0
    result["existing_scheduled"] = scheduled

    sent_today = 0
    if day.date() == now.date():
        sent_today = store.sent_today_count()
    result["sent_today"] = sent_today

    # How much of the daily share is still unfilled? Already-sent emails count
    # toward the cap, just like scheduled rows, so we never overschedule a day
    # that has already hit its send target.
    deficit = max(0, target - (scheduled + sent_today))
    result["deficit"] = deficit

    if deficit <= 0:
        return result

    # Do not add more than the idempotency tag already scheduled; this prevents
    # re-creating rows that were sent earlier in the day.
    existing_backfill = _existing_backfill_count(day, store)
    to_add = max(0, deficit - existing_backfill)
    result["existing_backfill_scheduled"] = existing_backfill
    result["to_add"] = to_add

    if to_add <= 0:
        return result

    emailed, excluded, scheduled_any, outreach_slugs = _gather_exclusions(store)
    exclude_slugs = set()
    exclude_slugs.update(emailed, excluded, scheduled_any, outreach_slugs)

    entries: List[dict] = []
    remaining = to_add
    for segments, template in _PRIORITY:
        if remaining <= 0:
            break
        picks = _select_for_segment(leads, contacts_by_slug, segments, template,
                                    exclude_slugs, remaining)
        seg_name = segments[0] if len(segments) == 1 else "consultants"
        result["segments"][seg_name] = {
            "template": template,
            "wanted": remaining,
            "selected": len(picks),
        }
        entries.extend(picks)
        remaining -= len(picks)

    if remaining > 0:
        result["unmet"] = remaining

    if not entries:
        result["skipped"] = True
        result["reason"] = "no eligible leads found"
        result["entries"] = []
        return result

    slots = _slots_for_day(day, len(entries), store)
    if not slots:
        result["skipped"] = True
        result["reason"] = "no send slots available inside window"
        result["entries"] = []
        return result

    # If the window cannot hold all entries, trim them (rare with a 20/day cap).
    entries = entries[:len(slots)]
    for entry, slot in zip(entries, slots):
        entry["send_at"] = slot

    result["entries"] = entries
    return result


def _write_day(plan: dict, store: MarketingStore, dry: bool) -> dict:
    """Write planned entries and return a summary."""
    tag = _campaign_tag(datetime.fromisoformat(plan["day"]))
    summary = {
        "day": plan["day"],
        "target": plan["target"],
        "existing_scheduled": plan["existing_scheduled"],
        "sent_today": plan["sent_today"],
        "deficit": plan["deficit"],
        "added": 0,
        "by_segment": {},
    }
    for entry in plan["entries"]:
        seg = (entry.get("segment") or
               ("consultants" if entry["template"] == _CONSULTING_TEMPLATE
                else "sustainability_compliance"))
        summary["by_segment"][seg] = summary["by_segment"].get(seg, 0) + 1
        if not dry:
            context = {
                "contact_name": entry["contact_name"],
                "organization": entry["organization"],
                "country": entry.get("country") or "",
                "identified_problem": entry.get("identified_problem") or "",
                "relevant_capability": entry.get("relevant_capability") or "",
                "recommended_product": "",
                "custom_message": entry.get("custom_message") or "",
                "claim_status": entry.get("claim_status") or "OBSERVED",
                "source": entry.get("source") or "",
                "date_checked": entry.get("date_checked") or "",
                "unsubscribe_url": mailer.unsubscribe_mailto(),
                "campaign": tag,
            }
            store.schedule_send(
                entry["slug"], entry["to_email"], entry["contact_name"],
                entry["template"], context, entry["send_at"],
            )
            summary["added"] += 1
    return summary


def _print_pool_report(pool: Dict[str, Dict]) -> None:
    print("\nPool report (lead archive + local DB):")
    print("-" * 70)
    current_segments = set()
    for segments, _ in _PRIORITY:
        current_segments.update(segments)

    held_total = 0
    for segment in sorted(pool):
        info = pool[segment]
        emailable = info["emailable"]
        held = emailable if segment not in current_segments else 0
        held_total += held
        reasons = info["reasons"]
        reason_str = ", ".join(
            f"{k}={v}" for k, v in reasons.items() if v
        ) or "none"
        status = "current" if segment in current_segments else "no current strategy"
        print(f"  {segment:30s} total={info['total']:5d}  emailable={emailable:5d}  "
              f"({status})  reasons: {reason_str}")
    print(f"  {'TOTAL emailable held (no current strategy)':50s} {held_total}")


def _workdays(now: datetime, n: int) -> Tuple[List[datetime], List[datetime]]:
    """Next n workdays (Mon–Fri UTC) from today's date.

    Operator directive 2026-09-12: outreach sends are workday-only — no
    Saturday/Sunday scheduling. Returns (workdays, skipped_weekend_days).
    """
    workdays: List[datetime] = []
    weekends: List[datetime] = []
    for offset in range(n * 2 + 3):
        if len(workdays) >= n:
            break
        day = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=offset)
        if day.weekday() >= 5:
            weekends.append(day)
            continue
        workdays.append(day)
    return workdays, weekends


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--days", type=int, default=2,
                    help="number of days to plan ahead, starting today UTC (default: 2)")
    ap.add_argument("--target", type=int, default=None,
                    help="daily target (default: DAILY_SEND_CAP env or 20)")
    ap.add_argument("--schedule", action="store_true",
                    help="actually write rows (default: dry run)")
    args = ap.parse_args(argv)

    target = args.target if args.target is not None else int(
        os.environ.get("DAILY_SEND_CAP") or 20)
    dry = not args.schedule
    now = datetime.utcnow()

    store = MarketingStore()
    leads = _load_leads()
    contacts_by_slug = _contacts_by_slug(store)
    emailed, excluded, scheduled_any, outreach_slugs = _gather_exclusions(store)
    pool = _emailable_pool(leads, contacts_by_slug, emailed, excluded,
                           scheduled_any, outreach_slugs)

    print("=" * 70)
    print(f"Daily backfill | target={target}/day | days={args.days} | "
          f"mode={'DRY RUN' if dry else 'SCHEDULE'}")
    print(f"Archive leads: {len(leads)} | contacts in store: {sum(len(v) for v in contacts_by_slug.values())}")
    print("=" * 70)

    summaries: List[dict] = []
    workdays, weekends = _workdays(now, args.days)
    for day in weekends:
        print(f"\n{day.date().isoformat()}: skipped — weekend (workday-only sends)")
    for day in workdays:
        plan = _plan_day(day, target, store, leads, contacts_by_slug, pool, now)
        summary = _write_day(plan, store, dry)
        summaries.append(summary)

        print(f"\n{plan['day']}:")
        if plan.get("skipped"):
            print(f"  skipped — {plan['reason']}")
            continue
        print(f"  existing scheduled: {summary['existing_scheduled']}, "
              f"sent today: {summary['sent_today']}, "
              f"deficit: {summary['deficit']}")
        if summary["by_segment"]:
            for seg, count in summary["by_segment"].items():
                print(f"  -> added {count:2d} from segment '{seg}'")
        elif summary["deficit"] > 0:
            print(f"  -> no eligible leads found (unmet deficit {plan.get('unmet', summary['deficit'])})")
        else:
            print("  -> day already at target")

    if dry:
        print("\nDRY RUN — nothing was scheduled. Add --schedule to write rows.")

    _print_pool_report(pool)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
