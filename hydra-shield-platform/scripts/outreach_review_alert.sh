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

if [ "$MODE" = "final" ]; then
  # End-of-campaigns report: per-wave breakdown + replies, written to a file
  # and opened for the operator review session.
  REPORT="$ROOT/data/campaign_final_review.txt"
  .venv/bin/python - > "$REPORT" <<'PY'
import collections
from src.dashboard.marketing_store import MarketingStore

WAVE_NAMES = {
    "outreach_investor": "Investor wave A/B/C (15)",
    "outreach_sustainability_compliance": "CSRD companies wave (14)",
    "outreach_insurance": "Insurance fresh batch (2)",
    "outreach_environmental_consulting": "Consultants channel wave (41)",
}
s = MarketingStore()
conn = s._connect()
rows = conn.execute(
    "SELECT lead_slug, to_email, template, send_at, status, error, sent_at"
    " FROM scheduled_outreach ORDER BY send_at, id").fetchall()
by_wave = collections.defaultdict(lambda: collections.Counter())
for _slug, _em, tpl, _at, status, _err, _sat in rows:
    by_wave[tpl][status] += 1
print("TALAIX — CAMPAIGN REVIEW (all waves) — generated live")
print("=" * 60)
print("(campaign sends = sent_at since 2026-09-08; earlier sends = pre-pivot)")
CAMPAIGN_START = "2026-09-08"
for tpl, label in WAVE_NAMES.items():
    c = by_wave.get(tpl, collections.Counter())
    old = sum(1 for r in rows if r[2] == tpl and r[4] == "sent"
              and (r[6] or "") < CAMPAIGN_START)
    new = c.get("sent", 0) - old
    print(f"{label:<38} sent={new:<3} scheduled={c.get('scheduled',0):<3} "
          f"failed={c.get('failed',0):<3} blocked={c.get('skipped_undeliverable',0)}"
          f"  (earlier: {old})")
print("-" * 60)
total_new = 0
total_old = 0
total_failed = 0
total_blocked = 0
for tpl, c in by_wave.items():
    old = sum(1 for r in rows if r[2] == tpl and r[4] == "sent"
              and (r[6] or "") < CAMPAIGN_START)
    total_old += old
    total_new += c.get("sent", 0) - old
    total_failed += c.get("failed", 0)
    total_blocked += c.get("skipped_undeliverable", 0)
print(f"{'TOTAL (this campaign)':<38} sent={total_new:<3} "
      f"failed={total_failed:<3} blocked={total_blocked}"
      f"  (pre-pivot sends: {total_old})")
print()
replied = conn.execute(
    "SELECT lead_slug, updated_at FROM lead_state WHERE outreach_status='replied'"
    " ORDER BY updated_at").fetchall()
print(f"REPLIES: {len(replied)}")
for slug, when in replied:
    print(f"  · {slug} ({when})")
print()
problems = [(r[0], r[1], r[4], r[5]) for r in rows if r[4] in ("failed", "skipped_undeliverable")]
print(f"PROBLEMS (failed/blocked): {len(problems)}")
for slug, em, st, err in problems:
    print(f"  · {slug} <{em}> [{st}] {err or ''}")
print()
print("Next decisions: banking/investment fresh (22 verified) · funders wave 1 "
      "(10 drafted) · follow-up wave for pre-pivot contacts (~09-22) · "
      "webform-only manual submissions.")
PY
  REPLIED=$(.venv/bin/python -c "
from src.dashboard.marketing_store import MarketingStore
conn = MarketingStore()._connect()
print(conn.execute(\"SELECT COUNT(*) FROM lead_state WHERE outreach_status='replied'\").fetchone()[0])
")
  TITLE="Talaix — انتهت جميع الحملات (72 رسالة)"
  MSG="أُرسلت: $SENT · فشل: $FAILED · محظور: $BLOCKED · ردود: ${REPLIED:-0} — التقرير الكامل مفتوح أمامك"
  osascript - "$TITLE" "$MSG" <<'OSA'
on run argv
  display notification (item 2 of argv) with title (item 1 of argv) subtitle "تقرير نهاية الحملات + قرارات المرحلة التالية" sound name "Glass"
end run
OSA
  open "$REPORT"
  exit 0
fi

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
