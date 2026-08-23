# Talaix — LinkedIn Strategy

**Status:** implemented (Phase D) — architecture, campaigns and draft
queues. **Nothing is published or sent automatically.** Posting is
human-executed from the queue, or a later explicit activation using only
officially supported APIs and permissions.

## 1. Role of the channel

LinkedIn is the primary B2B distribution channel: the segments
(docs/CUSTOMER_SEGMENTATION.md) — insurers, investors, municipalities,
infrastructure operators, researchers — are addressable there with
evidence-dense professional content. The goal is not virality; it is
qualified discovery of Talaix by people with a climate-exposure
problem.

## 2. Content pillars

1. **Current climate extremes** — what the live data shows now (linked to
   the real analysis/map)
2. **Historical event intelligence** — documented past events, evidence
   classes visible
3. **Satellite observations** — what Earth observation actually saw
4. **Map discoveries** — interesting, real findings from the map layers
5. **Climate risk for business** — exposure, economy, sector implications
6. **Insurance intelligence** — underwriting context, evidence needs
7. **Investment intelligence** — due-diligence context
8. **Sustainable solutions** — solution classes with limitations stated
9. **Technology discoveries** — how the pipeline works, honestly
10. **Annual reports** — the Annual Climate Extreme Intelligence Report
11. **Research** — methods, validation, registries
12. **Product developments** — what shipped, what it does, what it doesn't

Every post follows docs/PRODUCT_STORY.md §8: no "predicts disasters", no
"prevents", no invented numbers. Posts cite the underlying source or the
live Talaix page where the claim can be checked.

## 3. Cadence and calendar

`marketing/content/calendar.json` holds the rolling calendar: 2–3 posts
per week, rotating pillars, anchored to real platform content (a new
analysis capability, a historical event page, the annual report). Drafts
live in `marketing/content/drafts/` as markdown with front-matter
(segment, pillar, CTA, landing page, status).

## 4. Campaigns

`marketing/campaigns/linkedin_campaigns.json` defines campaigns A–G
(insurance, real estate, investors, municipalities, researchers,
infrastructure, solutions). Each carries objective, audience, pain,
evidence, content, CTA, landing page, follow-up, conversion goal and
metrics. Campaign performance is read from product analytics
(`report_generated`, `account_created`, `contact_started` with referrer
attribution) plus manually recorded outcomes — no LinkedIn scraping.

## 5. Drafts and queue

Drafts are markdown files in `marketing/content/drafts/` with this
front-matter:

```
---
segment: insurance
pillar: insurance_intelligence
campaign: A
cta: "Analyze a portfolio location free"
landing: https://talaix.com/intelligence.html
status: draft | reviewed | queued | published | retired
---
```

Publishing = a human copies the reviewed draft to LinkedIn and flips
`status` (+ records the date). That is the entire automation boundary.

## 6. Lead attribution

Campaign posts link to tagged landing URLs (e.g.
`?utm_source=linkedin&utm_campaign=A`). When the first-party analytics
records a `referrer`/landing from those tags, attribution is countable in
the admin aggregates — without tracking individuals across the web.

## 7. Compliance (binding)

- No scraping of LinkedIn data; no headless browsing of LinkedIn.
- No fake accounts, no engagement pods, no bought followers.
- No automated connection requests or DMs unless an official LinkedIn API
  and granted permissions explicitly allow the operation — evaluated only
  as a later, separately-approved integration.
- Organic posting is human-executed; the workspace prepares drafts,
  calendars and queues only.
- If LinkedIn's official Marketing/Community Management APIs are adopted
  later, the integration must be OAuth-based, documented here, and remain
  per-action auditable.
