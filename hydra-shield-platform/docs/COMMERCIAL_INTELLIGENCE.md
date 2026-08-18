# HydraShield — Commercial Intelligence & Marketing Radar

**Status:** implemented (this phase). The architecture that turns
`marketing/` from a static workspace into a persistent commercial
intelligence system: discover → qualify → contact → maintain
relationships. Binding norm: **no fabricated leads, companies, signals,
events, advertising data or interactions.**

## 1. The commercial principle

HydraShield does not market itself broadly. It discovers:

```
WHO has a problem → WHAT problem → WHERE → WHICH hazard
→ WHAT evidence demonstrates it → WHICH capability solves part of it
→ WHO the decision-maker role is → WHY now → WHAT message → WHAT next action
```

i.e. PROBLEM → EVIDENCE → PROSPECT → SOLUTION → CONTACT → RELATIONSHIP →
SUBSCRIPTION → RETENTION.

## 2. Commercial signals

`marketing/signals/<id>.json` (schema: `marketing/signals/schema.json`).

A **CommercialSignal** is recorded evidence that an organization may have
an active need: climate-risk publications, sustainability reports,
resilience programmes, insurance climate activity, infrastructure /
real-estate / coastal / flood / wildfire / drought projects, conferences,
exhibitions, sponsorships, **public procurement**, technology programmes,
relevant job postings, public investment, public announcements, and
advertising activity where a legitimate public source evidences it.

Every signal carries: `id, organization, sector, country, region,
hazards, signal_type, signal_strength (weak/moderate/strong), source,
source_url, date_observed, date_checked, evidence_type, confidence,
notes, recommended_action`.

**Advertising-spend rule:** spend is recorded only when an authoritative
source publishes a figure (then with value/currency/year/source/method).
Where only qualitative evidence exists, use `activity_level`
LOW/MEDIUM/HIGH — an evidence-based activity classification, **never**
measured expenditure. The integrity check rejects spend-like fields.

## 3. Market/advertising activity research framework

Source adapters are *planned integrations*, each requiring its own
legal/terms review before any activation (see
docs/EXTERNAL_INTEGRATIONS.md):

| Source class | Examples | Status |
|---|---|---|
| Public procurement portals | TED (EU Tenders Electronic Daily), national portals | RESEARCH REQUIRED — public, documented APIs exist; terms per portal |
| Company registries | national registries, EU Open Data | RESEARCH REQUIRED |
| Official publications | sustainability reports, annual reports on company sites | AVAILABLE (manual research, URL-checked) |
| Event pages | official conference/exhibition sites | AVAILABLE (manual) |
| Job postings | public careers pages | AVAILABLE (manual); aggregators: LEGAL/TERMS REVIEW |
| Advertising libraries | official ad-transparency libraries (e.g. platform-run public ad libraries) | LEGAL/TERMS REVIEW REQUIRED; API access varies |
| Social platforms | LinkedIn etc. | **NO SCRAPING** — official APIs only, later |

No scraping, no headless automation against platform terms, ever.

## 4. Events radar

`marketing/events/<slug>.json` (schema: `marketing/events/schema.json`):
`event, organizer, location, date, url, source, sectors, hazards,
relevance (+relevance_reason), date_checked, status
(watching/attending/skipped/past)`. Copilot `events` ranks what's most
relevant now.

## 5. Lead qualification (extends the 19-segment model)

`marketing/leads/<org>.json` (schema v2: `marketing/leads/schema.json`):
adds `identified_problem`, `commercial_signals[]`, `event_signals[]`,
`recommended_product`, `recommended_message`, `fit_score` (qualitative
reasoning, not a fabricated metric), `urgency`, `contact_type`,
`last_contact`, `next_action`, `next_followup`, `owner`. Personal contact
data only from legitimate public/business sources where legally
appropriate.

## 6. Relationship history

`interactions[]` on each lead is the persistent record:
`date, type (discovered|researched|contacted|replied|meeting|demo|
report_requested|trial|subscription|lost|follow_up), summary, source,
next_action`. "What happened with this organization?" is answered by
reading one file — auditable in Git.

## 7. The copilot

`scripts/marketing_status.py` subcommands:

| Command | Answers |
|---|---|
| `status` | workspace state + integrity (default) |
| `signals` | which companies have new commercial signals |
| `sectors` | which sectors show the strongest recorded activity |
| `events` | which events to monitor now |
| `priorities` | who to contact today, why, with which product and evidence |
| `followups` | who has not been followed up |
| `content` | what to publish this week (drafts awaiting review) |
| `demand` | aggregate product demand (analytics counts; no individuals) |
| `lessons` | what previous outreach taught us |
| `morning` / `evening` | the daily operator workflow, live |

The copilot drafts nothing on its own and sends nothing; drafts are
prepared for human review in `marketing/outreach/queue.json`.

## 8. Demand signals (product ↔ marketing)

`copilot demand` reads the local first-party analytics DB and prints
aggregate counts only (top hazards, pages, funnel). Privacy constraint:
our analytics deliberately do not track sector or country of users — so
sector/geography-level demand must come from lead records, events and
conversations, never from user surveillance. Where the data cannot say,
the copilot says "unknown, not zero".

## 9. Marketing memory

`marketing/` is institutional memory: what we tried (campaigns, drafts),
who we contacted (leads, interactions), what worked/failed (`lessons`,
`analytics/` notes), which segments converted (analytics funnel),
which events generated leads (event refs on leads). Git history is the
audit trail; the copilot's integrity check enforces the honesty contract.
