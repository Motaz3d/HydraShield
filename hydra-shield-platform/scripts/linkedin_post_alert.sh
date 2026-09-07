#!/bin/bash
# LinkedIn post-time alert — fires a macOS notification and opens today's
# due draft so posting is one paste away. Matches the fixed cadence in
# marketing/content/calendar.json (Europe/Brussels == server local time):
#
#   0 7  * * 2,3,4  .../scripts/linkedin_post_alert.sh   (Tue/Wed/Thu slots)
#   0 16 * * 0      .../scripts/linkedin_post_alert.sh   (Sunday slot)
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" || exit 1

INFO=$(.venv/bin/python - <<'PY'
import datetime
import json
import os

with open("marketing/content/calendar.json", encoding="utf-8") as fh:
    cal = json.load(fh)
today = datetime.date.today().isoformat()
for slot in cal.get("queue", []):
    if slot.get("date") == today and slot.get("status") not in ("published", "retired"):
        print(slot.get("topic") or "LinkedIn post")
        draft = slot.get("draft") or ""
        print(os.path.join("marketing", "content", "drafts", draft) if draft else "")
        break
PY
) || exit 0
[ -z "$INFO" ] && exit 0

TOPIC=$(printf '%s\n' "$INFO" | sed -n '1p')
DRAFT=$(printf '%s\n' "$INFO" | sed -n '2p')

osascript - "$TOPIC" <<'OSA'
on run argv
  display notification (item 1 of argv) with title "Talaix — وقت بوست لينكدإن" subtitle "افتح المسودة والصقها في لينكدإن الآن" sound name "Glass"
end run
OSA

if [ -n "$DRAFT" ] && [ -f "$DRAFT" ]; then
  open "$DRAFT"
fi
