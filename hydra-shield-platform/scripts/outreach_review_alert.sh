#!/bin/bash
# Outreach pipeline review alert — macOS notification + opens the consultants
# wave preview (the approval pending) with live queue stats in the message.
# Installed as one-shot pinned dates (local time, Europe/Brussels):
#   30 17 11 9 *  .../scripts/outreach_review_alert.sh week   (Fri 11.9 17:30 — end of first send week)
#   30 10 12 9 *  .../scripts/outreach_review_alert.sh review (Sat 12.9 10:30 — main review session)
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" || exit 1
MODE="${1:-review}"

STATS=$(.venv/bin/python - <<'PY'
from src.dashboard.marketing_store import MarketingStore
s = MarketingStore()
conn = s._connect()
sent = conn.execute(
    "SELECT COUNT(*) FROM scheduled_outreach WHERE status='sent'"
).fetchone()[0]
pending = len(s.list_scheduled(status='scheduled'))
failed = conn.execute(
    "SELECT COUNT(*) FROM scheduled_outreach WHERE status='failed'"
).fetchone()[0]
blocked = conn.execute(
    "SELECT COUNT(*) FROM scheduled_outreach"
    " WHERE status='skipped_undeliverable'").fetchone()[0]
print(f"sent={sent} pending={pending} failed={failed} blocked={blocked}")
PY
) || STATS="stats unavailable"

for kv in $STATS; do eval "$kv"; done
SENT=${sent:-?}; PENDING=${pending:-?}; FAILED=${failed:-0}; BLOCKED=${blocked:-0}

if [ "$MODE" = "week" ]; then
  TITLE="Talaix — نهاية أسبوع الإرسال الأول"
  MSG="أُرسلت: $SENT · متبقٍ: $PENDING · فشل: $FAILED · محظور: $BLOCKED — راجع قبل عطلة الأسبوع"
else
  TITLE="Talaix — جلسة مراجعة خط الإرسال"
  MSG="أُرسلت: $SENT · متبقٍ: $PENDING · فشل: $FAILED — اعتماد الاستشاريين ينطلق الاثنين 07:05 UTC إن قلت «معتمد»"
fi

osascript - "$TITLE" "$MSG" <<'OSA'
on run argv
  display notification (item 2 of argv) with title (item 1 of argv) subtitle "معاينة الاستشاريين + نتائج الأسبوع" sound name "Glass"
end run
OSA

PREVIEW="$ROOT/marketing/outreach/consultants_wave1_preview.html"
[ -f "$PREVIEW" ] && open "$PREVIEW"
exit 0
