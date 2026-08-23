# Talaix — SEO Strategy

**Status:** implemented (architecture + editorial backlog). Evidence-based
search presence around real search intent — no SEO spam, no thin
programmatic pages.

## 1. Intent clusters

| Cluster | Example intents | Talaix surface |
|---|---|---|
| Hazard analysis | "wildfire risk assessment", "flood risk assessment" | intelligence.html per-hazard |
| Sector risk | "climate risk for infrastructure / real estate / investors / insurance" | for-* landing pages |
| Exposure | "flood exposure analysis", "population exposure" | economy.html, map.html |
| Historical evidence | "historical wildfire analysis", "fire history by year" | events.html |
| Funding | "EU climate funding", "climate adaptation funding" | funding.html |
| EO/methods | "Earth observation climate risk", "FWI explained" | technology.html, story.html |

## 2. Page architecture

- Each cluster maps to a **real product page** (never a doorway page):
  the page must itself deliver the capability the query asks for.
- Hazard/region content pages are created only where real analyses and
  event data anchor them — content follows capability, not keywords.
- Every page carries descriptive title + meta description written for the
  searcher, and links into the live product.

## 3. Editorial backlog rules

- Backlog items are ranked by actual demand signals (first-party
  analytics: hazards analyzed, pages used, reports generated, funding
  searches) + segment needs — see `marketing/content/backlog.json`.
- Every numerical claim in an article requires source + date. No invented
  statistics, no engagement bait, no fabricated rankings.
- Each article links to at least one live Talaix surface so the
  reader can verify.

## 4. Measurement

Search-driven registrations are read from the analytics funnel
(referrer/landing attribution) in the admin aggregates — counts, never
individual tracking.
