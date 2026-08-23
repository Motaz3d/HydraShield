# Talaix — Products & Partnerships

**Status:** commercial strategy on top of the analytical core.
Rule: every product below is assembled from the SAME real-data engine and
evidence discipline — never a parallel stack. No unsupported market-size
claims; partnership names are classes/candidates, not claimed agreements.

---

## 1. Commercially viable products (same core, new packaging)

| Product | Buyer | What it is (today's engine → product) | Stage |
|---|---|---|---|
| **Property climate risk** | real-estate platforms, property managers | per-address hazard profile + exposure + historical events + evidence pack (`/api/v2/analyze`, `/events`, `/economy`, widget) | foundation exists |
| **Climate due diligence** | investors, M&A, lenders | multi-asset evidence packs: hazard history, scenario-labelled projections, validation status, PDF + API | foundation exists |
| **Insurance intelligence** | insurers, brokers, MGAs | underwriting-relevant evidence: hazard frequency, exposure/resilience profile, uncertainty statement (never premiums) | evidence stage |
| **Financial/climate risk screening** | banks, funds | portfolio-location screening via API keys + bulk analysis jobs; disclosure-aligned labels | evidence stage |
| **Infrastructure monitoring** | utilities, transport, energy | watched assets + event-driven alerts (SMS/email/webhook) + significant-change detection | active (SMS/webhook base live) |
| **Agriculture intelligence** | agri-coops, insurers, agtech | drought/soil-moisture/heat analysis + cropland exposure + seasonal comparison | hazard foundations exist |
| **Supply-chain climate risk** | corporates, logistics | multi-point monitoring of supplier locations; disruption-relevant alerts | framework stage |
| **ESG / CSRD evidence** | corporates, auditors | traceable physical-risk evidence for sustainability reporting (sources, methods, labels; no invented metrics) | framework stage |
| **Government / municipal** | civil protection, cities | monitored areas, alerts, reports, open-data transparency, standard formats | partial (watches, reports live) |

Packaging rule: a "product" = API scope + SDK/widget + report template +
subscription tier on the same engine. No product may introduce its own
numbers.

## 2. Partnership classes (continuous identification — build vs partner)

| Class | What we seek | Candidate examples (classes, not agreements) | Why partner instead of build |
|---|---|---|---|
| Data providers | fill declared gaps: flood extent (Sentinel-1), burned area perimeters, population grids, lightning, hail | Copernicus services (CDSE/CLMS/EFAS/CAMS), NASA/USGS archives, GHSL/WorldPop, national met/hydro agencies | authoritative, licensed, maintained — we consume with provenance |
| SMS/notification delivery | EU/GDPR SMS + push at scale | EU-based SMS aggregators with GDPR terms | delivery infrastructure is a commodity; never build |
| Payment/billing | subscriptions, invoicing, VAT | established EU payment providers | regulated; never build |
| Research partners | validation, model evaluation, method papers | universities, JRC-aligned labs, national met services | independent validation strengthens trust |
| SaaS integrations | where our users already work | GIS platforms, property platforms, insurance cores, banking risk tools | distribution + integration beats a new UI |
| Distribution partnerships | channels to sectors above | industry associations, insurer/utility vendor ecosystems, EU innovation networks | reach without a sales army |
| Government/EU programmes | pilots, procurement, grants | civil-protection agencies, EU innovation programmes | legitimacy + real requirements |

Evaluation criteria for any partner: data/license legality, EU/GDPR
compatibility, scientific quality, coverage/resolution/latency, pricing,
lock-in risk, and whether the partner's evidence can carry Talaix
provenance labels.

## 3. Continuous conversion pipeline

Every new dataset/capability follows the same path:

```
evaluate (source audit → registry candidate)
 → integrate (fetcher + labels + offline tests)
 → engine (analysis block with provenance + confidence)
 → API (additive /api/v2 field or endpoint; contract test)
 → interfaces (SDKs/widget/webhook exposure)
 → product (which product lines consume it)
 → partnership (is an external provider/partner better than building?)
```

The roadmap (`IMPLEMENTATION_ROADMAP.md`) tracks every item through this
pipeline: ALREADY IMPLEMENTED / NEXT / LATER / RESEARCH / CREDENTIAL.

## 4. What we deliberately do NOT do

- No brokerage of upstream raw data; no scraping of copyrighted sources.
- No actuarial pricing, no premium calculation, no regulated advice.
- No marketing automation on user data; no sale of user/alert data.
- No invented partnership claims: this document names classes and
  evaluation criteria, not agreements.
