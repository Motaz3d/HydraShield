# Daily operator workflow

The copilot (`scripts/marketing_status.py`) drives the day. Nothing
auto-sends; the operator decides and executes.

## Morning

```
python scripts/marketing_status.py morning
```

1. **New commercial signals** — who showed climate-relevant activity
2. **Events to monitor** — ranked by relevance and date
3. **High-priority prospects** — who to contact today, why, with which
   Talaix service and which evidence
4. **Follow-ups due** — leads past their `next_followup` date
5. **Product demand signals** — what users actually analyzed/viewed
   (aggregate counts only)
6. **Content this week** — drafts awaiting human review
7. **Recommended outreach** — pick from the above; draft per the segment's
   style; queue in `marketing/outreach/queue.json`

## Evening

```
python scripts/marketing_status.py evening
```

1. **Record interactions** — append to each lead's `interactions[]`
   (date, type, summary, source, next_action)
2. **Update lead status** — `outreach_status`, `status`, `last_contact`,
   `next_followup`
3. **Record responses** — what was actually said/decided
4. **Capture lessons** — persuasive evidence, dead ends →
   `marketing/analytics/` notes
5. **Generate next actions** — tomorrow's priorities emerge from the
   records, not from memory

## Rules

- A record without `source` + `date_checked` does not exist.
- Unknown stays "unknown" — never pad a lead.
- The integrity check runs inside every copilot call; fix problems before
  acting on the data.

## Marketing CRM tabs

The Marketing CRM lives in `/admin.html` as two tabs — **Targets** and
**Site statistics** — next to the Commercial Center tab. `/marketing.html`
is a legacy alias: operator-gated like `/admin.html`, it redirects to
`/admin.html#targets`.

**Targets** is a lazy drill-down: **sector → country → all targets in the
intersection**. `GET /api/v2/admin/marketing/tree` returns every segment
present in the lead base (we target all sectors) with counts; adding
`?segment=` returns countries; `?segment=&country=` returns the status
counts plus the full lead list (each lead carries its `outreach_status`);
adding `&status=` filters that list. The intersection opens as a modal
listing every targeted organisation with Auto-send / Follow-up buttons.
Lead detail (`/api/v2/admin/marketing/lead/<slug>`) shows the merged
record, score, interaction log, follow-up file and scheduled outreach.

**Site statistics** (`/api/v2/admin/marketing/stats`) shows visitor cards
(today / 7d / 30d unique sessions, page views), subscribers and accounts,
then collapsible detail sections: most visited pages, daily visitors,
traffic sources, devices & languages and risk interests. Aggregate counts
only — analytics sessions are pseudonymous hashes.

**Auto-send.** The operator clicks send; nothing self-sends. The message is
rendered from the sector templates in
`src/dashboard/email_templates/outreach_*.txt` (falling back to
`outreach_generic.txt`), merged with the lead's country, identified problem,
capability and any custom note. Without `SMTP_HOST` configured, email goes to
the dev outbox (`HYDRASHIELD_OUTBOX_DIR`) and the UI says so; with SMTP env
set, delivery uses STARTTLS.

**Scheduled sending.** Queue future emails with `send_at` (ISO, must be
future). A cron job sends due rows, logs an `email` interaction, and advances
`outreach_status` to `contacted` when it was `researched`, `qualified` or
`draft_prepared`:

```
*/5 * * * * cd <repo>/hydra-shield-platform && .venv/bin/python scripts/process_scheduled_outreach.py
```
