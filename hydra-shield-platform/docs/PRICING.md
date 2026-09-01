# Talaix — Pricing

**Status:** decided 2026-08-31 (operator decision). Not yet published on the
site; `website/account.html` still states "no public pricing yet" until the
pricing page ships. When published, this document remains the source of
record — the site must match it.

Norms (binding, from `docs/USER_AND_SUBSCRIPTION_ARCHITECTURE.md` and the
operating rules in `PLAN.md`):

- **Conversion through value, not obstruction.** The free tier stays
  genuinely useful; payment appears at the moment of added value.
- **No invented numbers.** Figures below are an explicit operator decision,
  not market data. They are reviewed against real costs and real sales
  conversations, not competitor folklore or unsourced market-size claims.
- **Honest scope.** Every tier sells *screening-level climate-risk
  intelligence and evidence*. Talaix does not sell actuarial pricing,
  premium calculation, regulated advice, or guaranteed loss prevention —
  at any price.
- **Wedge first.** The pricing is shaped for the segment that decides
  fastest: consultants, researchers and small engineering/real-estate
  offices (per `docs/CUSTOMER_SEGMENTATION.md`). Slow, high-value segments
  (insurance, banks, government) enter through the pilot programme (§4),
  not through list prices they would never accept pre-case-studies.

---

## 1. Tiers

| Tier | Price | Audience | Maps to role |
|---|---|---|---|
| **Free** | €0 | anyone — citizens, researchers, first contact | `anonymous` / `visitor` / `registered` |
| **Professional** | €49 / month · €490 / year | consultants, analysts, individual practitioners | `subscriber` / `professional` |
| **Business** | €249 / month · €2,490 / year | companies: insurance, real estate, energy, agriculture, logistics, tourism, manufacturing | `business` |
| **Government** | from €4,900 / year (annual only) | municipalities, civil protection, public agencies | `municipality` / `government` |
| **Enterprise** | custom, from €12,000 / year | insurers, banks, investors, portfolio-scale users | organization contract |

Annual billing = 10 × monthly (two months free). All prices exclude VAT.

**Launch pricing:** Professional at €49/month is a deliberate wedge price —
an easy individual yes that converts the free funnel into the first paying
customers. It is reviewed (likely raised) after the first 20 paying
customers; existing customers keep their price under §7 grandfathering.

Academic programme: universities, research centres and NGOs receive
**Professional free of charge** on application (aligned with
`docs/CUSTOMER_SEGMENTATION.md` — these segments start from the free tier
and build the evidence base).

## 2. What each tier gets

### Free — €0

Public site + free account:

- Multi-hazard analysis for any location (7 hazards: wildfire, flood,
  drought, extreme heat, extreme wind, coastal, tropical cyclones)
- Interactive risk map: danger grids, active fires (FIRMS), active storms,
  ports/trade infrastructure
- Public risk snapshot of monitored areas
- Historical analysis: ERA5 fire-danger history, "Lessons from the Past"
- Simple PDF report
- 3 saved locations · 5 email alert rules
- Rate limits as implemented (`anonymous` 30/min → `registered` 120/min)

### Professional — €49 / month · €490 / year

Everything in Free, plus:

- All three report types: simple, **decision** and **scientific**, with
  full provenance and limitations
- Full historical depth, including historical wildfire event records
- Economic exposure, Solutions Intelligence and sustainability-evidence
  sections (CSRD/ESRS E1 / TCFD-ISSB positioning, screening-level)
- API key: programmatic access to `/api/v2`, Python & JavaScript SDKs,
  QGIS plugin, embeddable `<hydrashield-risk>` web component, webhooks as
  they ship
- 25 saved locations · 25 alert rules · portfolios
- Per-user rate limit 600 requests/min (as implemented)
- Email support

### Business — €249 / month · €2,490 / year

Everything in Professional, plus:

- Organization workspace with **5 seats** (extra seats €25 / seat / month)
- Multi-location monitoring: up to **100 locations** under one organization
- Team dashboards; scheduled and custom reports (report builder)
- Sustainability-evidence pack for reporting annexes
- Per-user rate limit 1,200 requests/min (as implemented)
- Priority support

### Government — from €4,900 / year

Business-scope capabilities packaged for the public sector:

- Jurisdiction-wide multi-location monitoring
- Civil-protection standard formats (GeoJSON / GML / CSV) for
  interoperability with existing systems
- Procurement-friendly annual invoicing; onboarding session included
- Pilot terms available for small municipalities (§4)
- Final price set per contract (population covered, locations, seats)

### Enterprise — custom, from €12,000 / year

- Portfolio-scale screening via API (thousands of assets)
- Insurance, forensics, supply-chain (EUDR) and green-finance
  verification modules at contract scope
- Custom integrations, SLA, dedicated support
- Optional validation-support engagement (model validation status is
  always stated honestly — see `docs/VALIDATION.md`)

## 3. Pay-per-use (no subscription)

For occasional users — a one-off property check, a single due-diligence
report — without a subscription:

- **Decision report**, one location: **€19**
- **Scientific report**, one location: **€39**
- A pay-per-use purchase is credited once against the first month of a
  Professional subscription started within 30 days.

This is the cheapest way to experience the paid product and the natural
entry point for real-estate due diligence; the simple report stays free.

## 4. Pilot programme (the case-study engine)

The binding constraint on selling to insurers, banks and governments is
not price — it is the absence of documented case studies. The pilot
programme buys those case studies:

- **Scope:** up to 3 months, Business-tier capabilities, up to 25
  monitored locations, one onboarding call and one review call.
- **Price:** nominal — typically **€490 flat** for the period, or free by
  operator decision (e.g. a small municipality or a humanitarian
  organization with no budget).
- **Exchange:** structured feedback, and — with the customer's written
  approval — a publishable, evidence-backed case study
  (`PLAN.md` go-to-market table; only real, checkable studies are ever
  published).
- **Conversion:** at the end of a pilot, the customer moves to a list
  tier or a negotiated annual contract; there is no automatic renewal and
  no charge without an explicit order.

## 5. Add-ons and usage notes

- **SMS alerts** are listed in no tier until a provider is configured in
  production (`PLAN.md` platform table); when live, they join Professional
  and above at no extra charge.
- Extra monitored locations beyond a tier's allowance: quoted per
  contract, never silently throttled.
- Prices are per organization/workspace, not per hazard — all 7 hazards
  are included in every tier, including Free.

## 6. Activation mechanics (until billing ships)

Payments are not yet integrated: subscriptions are **recorded, not
charged** (`docs/USER_AND_SUBSCRIPTION_ARCHITECTURE.md` §7,
`subscriptions.external_ref` awaits a provider). Until then:

- The pricing page shows these prices with a "Contact to activate" call
  to action (info@talaix.com); the operator activates the tier
  server-side and sends an invoice. Publishing real prices matters:
  an honest number beats "contact us for pricing" even before checkout
  exists.
- Self-service card payment is added when a provider is integrated;
  card data never touches Talaix.

## 7. Change rules

- Existing paying customers keep their price for 12 months after any
  change (grandfathering).
- The Free tier never loses a capability it already has; capabilities may
  only be added to it.
- A price change is a commit to this file plus a matching site update in
  the same deploy.

## 8. Publishing checklist

When the pricing page ships it must:

- Present all four tiers, pay-per-use (§3) and the pilot programme (§4)
  with the exact figures above.
- Order the page around the wedge: Professional highlighted as the
  entry point, Enterprise visible as the anchor.
- Keep the screening-level disclaimer and the "no actuarial pricing / no
  regulated advice" line visible on the page itself.
- Update `website/account.html` ("no public pricing yet") in the same
  deploy.
