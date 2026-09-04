#!/usr/bin/env python3
"""Content dispatcher — emails the day's due LinkedIn draft to the operator.

Reads ``marketing/content/calendar.json`` for slots due today (or within
``--days``), loads the referenced draft from ``marketing/content/drafts/``,
sends the full paste-ready text to the operator inbox via
``mailer.operator_notify``, then flips the draft's front-matter status to
``queued``. Publishing itself stays human-executed — the operator pastes
the text into LinkedIn and flips the status to ``published``
(docs/LINKEDIN_STRATEGY.md §7).

State lives in ``marketing/content/.dispatch_state.json`` so each slot is
dispatched — or reminded about, when it has no draft — exactly once.

    python scripts/content_dispatcher.py           # dispatch what's due
    python scripts/content_dispatcher.py --check   # dry run, send nothing
    python scripts/content_dispatcher.py --days 2  # also look 2 days ahead
"""

import argparse
import json
import os
import re
import sys
from datetime import date, datetime, time as dtime, timedelta

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python < 3.9
    ZoneInfo = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src.dashboard import mailer  # noqa: E402

MARKETING = os.path.join(ROOT, "marketing")
CALENDAR = os.path.join(MARKETING, "content", "calendar.json")
DRAFTS = os.path.join(MARKETING, "content", "drafts")
STATE_PATH = os.path.join(MARKETING, "content", ".dispatch_state.json")

_FM_RE = re.compile(r"\A---\n(.*?)\n---\n", re.S)
_STATUS_RE = re.compile(r"^status:\s*(\S+)\s*$", re.M)
_DISPATCHABLE = ("draft", "reviewed")
_DEFAULT_TIME = "07:00"
_FALLBACK_TZ_LABEL = "server local"


def _load_json(path: str, default):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _save_json(path: str, data) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


def _parse_draft(path: str):
    """Return (front_matter_dict, body_text) for a draft markdown file."""
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    m = _FM_RE.match(text)
    meta = {}
    body = text
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                key, _, val = line.partition(":")
                meta[key.strip()] = val.strip().strip('"')
        body = text[m.end():].strip()
    return meta, body


def _flip_status(path: str, new_status: str) -> None:
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    updated, n = _STATUS_RE.subn(f"status: {new_status}", text, count=1)
    if n:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(updated)


def _cadence():
    return _load_json(CALENDAR, {}).get("cadence", {})


def _tz(cadence):
    """Dispatch timezone (Europe/Brussels per calendar); falls back to
    server local time when zoneinfo/tzdata is unavailable."""
    name = cadence.get("dispatch_timezone", "")
    if name and ZoneInfo is not None:
        try:
            return ZoneInfo(name), name
        except Exception:
            pass
    return datetime.now().astimezone().tzinfo, _FALLBACK_TZ_LABEL


def _dispatch_dt(slot_date: date, slot: dict, cadence: dict, tz) -> datetime:
    """When this slot's email should go out: per-slot ``dispatch_at``
    override, else the weekday time from cadence, else 07:00."""
    hhmm = (slot.get("dispatch_at")
            or cadence.get("dispatch_times", {}).get(slot_date.strftime("%A"))
            or _DEFAULT_TIME)
    try:
        hour, minute = (int(part) for part in hhmm.split(":")[:2])
    except ValueError:
        hour, minute = 7, 0
    return datetime.combine(slot_date, dtime(hour, minute), tzinfo=tz)


def _due_slots(today: date, lookahead: int):
    calendar = _load_json(CALENDAR, {})
    horizon = today + timedelta(days=max(lookahead, 0))
    out = []
    for slot in calendar.get("queue", []):
        try:
            slot_date = date.fromisoformat(slot.get("date", ""))
        except ValueError:
            continue
        if slot.get("status") in ("published", "retired"):
            continue
        if today <= slot_date <= horizon:
            out.append((slot_date, slot, False))
        elif slot_date < today:
            out.append((slot_date, slot, True))
    out.sort(key=lambda item: item[0])
    return out


def _dispatch_slot(slot_date: date, slot: dict, state: dict, check: bool,
                   stale: bool = False, now: datetime = None,
                   due_dt: datetime = None, tz_label: str = "") -> str:
    key = slot_date.isoformat()
    dispatched = state.setdefault("dispatched", {})
    reminded = state.setdefault("reminded", {})
    draft_name = slot.get("draft")

    if stale:
        return (f"· {key}: STALE slot ({slot.get('topic', '?')}) — publish "
                "manually or retire; never auto-dispatched")

    if key in dispatched:
        return f"· {key}: {draft_name or 'slot'} already dispatched"

    if due_dt is not None and now is not None and now < due_dt:
        note = "draft ready" if draft_name else "NO DRAFT yet"
        return (f"· {key}: scheduled {due_dt.strftime('%H:%M')} {tz_label} "
                f"({note}) — waiting")

    if not draft_name:
        if key in reminded:
            return f"· {key}: no draft (already reminded)"
        if not check:
            mailer.operator_notify(
                f"LinkedIn slot {key} has no draft yet",
                "The content calendar has a slot due with no prepared draft.\n\n"
                f"Date:    {key}\n"
                f"Pillar:  {slot.get('pillar', '?')}\n"
                f"Topic:   {slot.get('topic', '?')}\n"
                f"Campaign: {slot.get('campaign', '?')}\n\n"
                "Write a draft in marketing/content/drafts/ and reference it "
                "in marketing/content/calendar.json, or retire the slot.\n"
                "Plan: marketing/strategy/social_media_plan.md",
                kind="content",
            )
            reminded[key] = datetime.now().isoformat(timespec="seconds")
        return f"· {key}: NO DRAFT — reminder {'would be' if check else ''} sent"

    path = os.path.join(DRAFTS, draft_name)
    if not os.path.exists(path):
        return f"· {key}: draft file missing: {draft_name}"

    meta, body = _parse_draft(path)
    status = meta.get("status", "draft")
    if status not in _DISPATCHABLE:
        return f"· {key}: {draft_name} [{status}] — not dispatchable"

    message = (
        f"LinkedIn post due {key} — ready to paste.\n"
        f"Pillar:   {slot.get('pillar', meta.get('pillar', '?'))}\n"
        f"Segment:  {meta.get('segment', '?')}\n"
        f"Campaign: {meta.get('campaign', '?')}\n"
        f"Draft:    marketing/content/drafts/{draft_name}\n\n"
        "----- POST TEXT (paste as-is into LinkedIn) -----\n\n"
        f"{body}\n\n"
        "----- AFTER PUBLISHING -----\n"
        f"Flip the draft's front-matter status to \"published\" in {draft_name}.\n"
        "Engagement playbook: marketing/strategy/social_media_plan.md §7"
    )
    if not check:
        mailer.operator_notify(
            f"LinkedIn post due {key}: {slot.get('topic', draft_name)}",
            message,
            kind="content",
        )
        _flip_status(path, "queued")
        dispatched[key] = {
            "draft": draft_name,
            "sent_at": datetime.now().isoformat(timespec="seconds"),
        }
    return f"· {key}: {draft_name} [{status}] — {'would dispatch' if check else 'dispatched → queued'}"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true",
                        help="dry run: report what would be dispatched, send nothing")
    parser.add_argument("--days", type=int, default=0,
                        help="also dispatch slots due within the next N days")
    args = parser.parse_args(argv)

    mailer.load_dotenv(os.path.join(ROOT, ".env"))
    cadence = _cadence()
    tz, tz_label = _tz(cadence)
    now = datetime.now(tz)
    today = now.date()
    slots = _due_slots(today, args.days)

    print(f"CONTENT DISPATCHER — {today.isoformat()} "
          f"{now.strftime('%H:%M')} {tz_label}"
          + (" (dry run)" if args.check else ""))
    print("=" * 60)
    if not slots:
        print("No slots due. Calendar: marketing/content/calendar.json")
        return 0

    state = _load_json(STATE_PATH, {})
    for slot_date, slot, stale in slots:
        due_dt = None if stale else _dispatch_dt(slot_date, slot, cadence, tz)
        print(_dispatch_slot(slot_date, slot, state, args.check, stale,
                             now, due_dt, tz_label))
    if not args.check:
        _save_json(STATE_PATH, state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
