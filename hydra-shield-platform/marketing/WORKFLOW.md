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
   HydraShield service and which evidence
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
