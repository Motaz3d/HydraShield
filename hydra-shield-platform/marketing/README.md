# HydraShield Marketing Workspace

This directory is HydraShield's **persistent marketing knowledge base** —
the shared memory between the operator and the AI copilot. It exists so
marketing does not depend on conversation memory: every decision, campaign,
lead and outcome is a file in this repository with history.

## Honesty rules (binding, same as the product)

- **No fabricated leads, companies, people, or interactions.** A record
  enters `leads/` only from a real, checkable source, with `source` and
  `date_checked` set. Publicly available professional information only.
- **No unsupported claims** in any content — marketing follows the same
  evidence discipline as the product (`docs/PRODUCT_STORY.md` §8).
- **No external sending from this workspace.** Drafts and queues are
  prepared here; every send is a human-executed or explicitly-activated
  step (`docs/MARKETING_INTELLIGENCE.md` §6).

## Layout

| Directory | Holds | Record format |
|---|---|---|
| `strategy/` | Links to the normative docs in `docs/` | md |
| `segments/` | `segments.json` — the 19 segment definitions | json |
| `leads/` | One JSON per organization (schema: `leads/schema.json`) — starts empty | json |
| `signals/` | Commercial signals (schema: `signals/schema.json`) — starts empty | json |
| `events/` | Event radar records (schema: `events/schema.json`) — starts empty | json |
| `campaigns/` | Campaign definitions (LinkedIn campaigns A–G etc.) | json/md |
| `content/` | `calendar.json` + `drafts/` — authored content drafts | json/md |
| `outreach/` | `queue.json` — prepared, human-executed outreach queue | json |
| `followups/` | Follow-up plans per open opportunity | md/json |
| `analytics/` | Periodic snapshots/notes interpreting product + campaign analytics | md |
| `research/` | Market research notes (sources + date checked) | md |
| `reports/` | Periodic marketing reports | md |

## Copilot protocol (how the AI uses this workspace)

1. **Read before writing.** Start from `segments/segments.json`, open
   `leads/`, active `campaigns/`, and the latest `analytics/` note.
2. **Append, don't rewrite history.** New interactions get new records;
   existing records are updated in place only for status changes (with
   `updated` bumped).
3. **Every record is self-describing** — schema in each directory's README
   or `schema.json`; unknown fields are not allowed in lead records.
4. **End every engagement by writing state**: what was researched, decided,
   drafted, or is blocked — so the next session starts from the repo, not
   from memory.

## Record statuses

Leads: `researched → qualified → draft_prepared → (human) contacted →
responded → opportunity | closed_lost`. Campaigns: `draft → ready →
(human) active → paused | completed`. Nothing may skip the human gate.
