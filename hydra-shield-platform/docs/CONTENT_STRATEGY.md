# Talaix — Content Strategy

**Status:** implemented (Phase G). How content is chosen, produced and
improved — driven by real demand signals, not generic SEO volume.

## 1. Principles

- **Evidence-based articles only.** Every article links to the platform's
  live analysis and cites authoritative sources (docs/PRODUCT_STORY.md §8
  claim rules apply to content).
- **Demand-driven backlog.** What we write comes from what users actually
  do (product analytics) and what segments need (marketing workspace) —
  not from keyword-stuffing lists.
- **No SEO spam.** No thin programmatic pages, no auto-generated filler,
  no invented statistics. Fewer, deeper, checkable pages.

## 2. Content clusters (website)

Each cluster = a hub page + supporting pages, all internally linked and
all pointing into the product (analysis, map, events, solutions, account):

1. **Hazard hubs** — one per hazard (wildfire/flood/drought/heat/wind/
   coastal): what it is, how Talaix measures it (sources, methods),
   historical intelligence, solutions.
2. **Exposure** — population, settlements, infrastructure, business
   exposure; who-is-exposed explainers.
3. **Economy & finance** — exposure-before-euros, insurance and investment
   context, honest non-quantification.
4. **Historical events** — event intelligence per region/hazard (from real
   event data; never synthesized events).
5. **Solutions** — solution classes and packages with limitations.
6. **Evidence & methods** — provenance model, validation, registries.
7. **Annual report** — the Annual Climate Extreme Intelligence Report
   (Phase 3 of the strategic plan).

Country/region pages are created only where real analyses and event data
exist to anchor them.

## 3. The learning loop

```
product analytics (what users analyze/view/generate)
  → demand signals (top hazards, pages, locations, referrers)
  → content backlog (marketing/content/, prioritized by demand)
  → published pages/posts
  → new analytics (what converts)
```

Admin aggregates (`/api/v2/admin/analytics/*`) answer: which hazards
attract analyses, which pages precede account creation, which reports are
generated, which campaigns (tagged landings) convert. The backlog is
re-ranked from these signals in `marketing/analytics/` notes.

## 4. Article requirements

- at least one link into a live Talaix surface (map/analysis/events/
  solutions) so the reader can verify
- sources cited inline (institution + dataset + date)
- evidence vocabulary used correctly (observed/historical/modelled/
  projected never mixed)
- a natural, honest CTA (analyze this place / monitor this area)

## 5. Social channels

LinkedIn is the primary B2B channel (docs/LINKEDIN_STRATEGY.md). X,
YouTube and a newsletter are queued channels — their architecture mirrors
LinkedIn (drafts + human-executed publishing queues) and activates only
when a real content cadence justifies them.
