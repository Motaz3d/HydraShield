# Talaix — Marketing Intelligence

**Status:** implemented (Phase C), extended by the Commercial Intelligence
& Marketing Radar (docs/COMMERCIAL_INTELLIGENCE.md — signals, events,
lead qualification, relationship history, copilot subcommands). The
persistent, repository-based marketing system. Normative rules live here;
data lives in `marketing/`.

## 1. Purpose and loop

Talaix's marketing is a continuous intelligence loop, not one-off
campaigns:

```
MARKET RESEARCH → TARGET SEGMENT → LEAD DISCOVERY → PAIN DISCOVERY
→ CONTENT → CAMPAIGN → OUTREACH → RESPONSE → FOLLOW-UP → CONVERSION
→ LEARNING → NEXT CAMPAIGN
```

The loop's memory is the repository: `marketing/` holds segments, leads,
campaigns, content, outreach queues and learning notes, all under version
control. The product-analytics event stream (docs/PRODUCT_ANALYTICS.md)
feeds LEARNING with real demand signals; marketing outcomes (responses,
conversions) are recorded back as records.

## 2. Data structures

- **Segments** — `marketing/segments/segments.json`: 19 segments, each
  with pain points, relevant hazards, capabilities, decision-maker roles,
  content topics, offer, CTA, outreach style, evidence requirements.
  Segment copy is curated strategy, grounded in real platform capabilities.
- **Leads** — `marketing/leads/<org>.json` per `leads/schema.json`:
  organization, segment, country/region, website, decision-maker *role*
  (never an invented person), climate exposure, potential pain, relevant
  hazards/capability/product, evidence to show, priority, estimated fit,
  outreach status, source, date_checked, interactions.
- **Campaigns** — `marketing/campaigns/`: objective, audience, pain,
  evidence, content, CTA, landing page, follow-up, conversion goal,
  metrics (see docs/LINKEDIN_STRATEGY.md for the LinkedIn set).
- **Outreach queue** — `marketing/outreach/queue.json`: drafted →
  human-reviewed → human-executed → outcome. **Nothing auto-sends.**
- **Content** — `marketing/content/`: calendar + drafts, authored to the
  same evidence rules as the product.
- **Learning** — `marketing/analytics/`: periodic notes connecting product
  analytics (what users do) with campaign outcomes (what marketing did).

## 3. Segmentation discipline

Never one generic message. Each outreach draft names its segment and
follows that segment's pain points, tone and evidence bar from
`segments.json`. Cross-segment reuse of a message is a defect.

## 4. Customer Need Intelligence

For each prospect the copilot fills the lead schema from public sources:
what climate exposure matters to them, what assets, what problem
Talaix could solve, which capability and product fits, what evidence
to show, and an honest fit assessment. Unknowns stay unknown — a lead with
thin public information is marked low-confidence, not padded.

## 5. Compliance

- GDPR: leads are organizations + roles, not scraped personal data; any
  named contact comes only from a public professional source, and outreach
  is individual, reviewable and stoppable.
- Channel rules: no scraping or automation that violates platform terms
  (LinkedIn specifics in docs/LINKEDIN_STRATEGY.md §7).
- Anti-spam: no bulk unsolicited sending, ever. The queue is
  human-executed by design.

## 6. Activation boundary

This system prepares; it does not send. Flipping any channel to
"sending" is a separate, explicit operator decision with its own audit
trail. Until then every artifact is a draft or a queue entry.
