#!/bin/bash
# Talaix email cron wrapper — loads .env, sends due outreach, then checks replies.
# Installed as:  */5 * * * * .../scripts/email_cron.sh >> .../data/email_cron.log 2>&1
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" || exit 1

# Overlap guard: a previous run still working (slow SMTP/IMAP) must not
# double-send. mkdir is atomic on every POSIX system; the trap releases it.
LOCKDIR="$ROOT/data/.email_cron.lock"
if ! mkdir "$LOCKDIR" 2>/dev/null; then
  echo "=== $(date '+%Y-%m-%d %H:%M:%S') skipped — previous run still active ==="
  exit 0
fi
trap 'rmdir "$LOCKDIR" 2>/dev/null || true' EXIT

# Load operator env (SMTP_*, IMAP_*, DAILY_SEND_CAP) if present.
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

echo "=== $(date '+%Y-%m-%d %H:%M:%S') outreach processor ==="
.venv/bin/python scripts/process_scheduled_outreach.py

# LinkedIn content dispatch: emails today's due draft to the operator
# (idempotent — marketing/content/.dispatch_state.json prevents resends).
echo "=== $(date '+%Y-%m-%d %H:%M:%S') content dispatcher ==="
.venv/bin/python scripts/content_dispatcher.py

if [ -n "${IMAP_HOST:-}" ]; then
  echo "=== $(date '+%Y-%m-%d %H:%M:%S') reply check ==="
  .venv/bin/python scripts/check_replies.py
fi
