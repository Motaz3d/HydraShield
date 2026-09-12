# Talaix — Business Plan

Prepared for the Luxembourg Space Agency · September 2026
Motaz Omarien, Founder · info@talaix.com · +352 661 811 680 · talaix.com

## 1. Executive summary

Talaix turns Earth-observation data into audit-ready climate-risk compliance evidence for EU disclosure (CSRD/ESRS E1, EU Taxonomy DNSH, EUDR). A user enters site coordinates and receives, in minutes, a multi-hazard evidence pack in which every value carries its source, reference date and evidence status — with machine-readable XBRL from our CsrdTX rules engine. The platform is live (talaix.com), the analytical engine is open source (tore, EUPL-1.2), and prices are published. We are pre-company and pre-seed: the plan is to incorporate a Luxembourg S.à r.l. in Q4 2026 and raise €850K, complemented by Luxembourg/ESA programme co-funding, to reach ~90 paying customers and a validated product within 24 months.

## 2. The problem

EU disclosure law now requires site-level physical climate-risk evidence. CSRD wave-2 companies must report on financial year 2027 (reports published 2028); EUDR has applied since 30 December 2025. Today a company that needs this evidence has two options, both bad: climate-risk specialists selling opaque five-to-seven-figure enterprise contracts, or GRC/CSRD workflow suites that manage the reporting process but generate no physical-risk evidence at all. Thousands of companies — and the consultants and auditors who serve them — need evidence that is specific, traceable and affordable.

## 3. The solution

Self-serve evidence packs from site coordinates: ten natural hazards (wildfire, flood, drought, extreme heat, extreme wind, coastal, tropical cyclone, earthquake, plus event-driven volcanic and dust screening), economic-exposure context, and mapping to ESRS E1 datapoints with XBRL output. Audit-grade honesty is the architecture, not a slogan: every datapoint carries source, method, reference period and evidence class (OBSERVED, ESTIMATED, FRAMEWORK or UNKNOWN), and "unavailable" is stated, never filled in. The engine is open source, so any auditor can read the code instead of trusting a black box.

## 4. Market and regulatory calendar

- CSRD wave-2 companies report on FY2027 — 2027 is the buying season; simplified ESRS adopted July 2026 keeps physical-risk disclosure in force.
- EU Taxonomy DNSH assessments and EUDR geolocation obligations add recurring demand, including non-EU exporters selling into the EU.
- Buyers: the companies themselves, plus sustainability consultants and auditors who need evidence their workflow tools do not produce — consultants are a deliberate channel segment.
- 33 vendors were profiled for this plan (17 GRC/CSRD suites, 16 physical-risk specialists); none offers transparently priced, standalone physical-risk evidence packs. This is the gap Talaix occupies.

## 5. Business model and pricing

| Tier | Price | Audience |
|---|---|---|
| Free | €0 | first contact, citizens, researchers |
| Professional | €49/month · €490/year | consultants, analysts, practitioners |
| Business | €249/month · €2,490/year | companies (insurance, real estate, energy, agriculture, logistics, manufacturing) |
| Government | from €4,900/year | municipalities, civil protection, public agencies |
| Enterprise | from €12,000/year | insurers, banks, investors, portfolio-scale users |
| Pay-per-report | €19–39 per report | occasional users, real-estate due diligence |
| Pilot programme | €490 flat, up to 3 months | slow, high-value segments — converts to publishable case studies |

All tiers include all hazards. Prices are published on talaix.com — transparency is the wedge against opaque enterprise vendors. Payments are currently recorded-not-charged until billing integration ships (Stripe backend complete).

## 6. Go-to-market

1. Self-serve wedge: free tier converts to €19 reports and €49/month Professional — the easy individual yes.
2. Pilot programme: €490 pilots in insurance, banking and government produce written-approval case studies, which unlock those segments at list prices.
3. Consultant channel: sustainability consultants and auditors carry the evidence packs into their client base.
4. Outbound waves: targeted email waves to CSRD-reporting companies, insurers and consultants are scheduled and sending this month; investor outreach runs in parallel.
5. Timing: the sales push peaks with the FY2027 CSRD reporting season.

## 7. Competition

| Category | Examples (profiled) | Their model | Talaix difference |
|---|---|---|---|
| GRC/CSRD workflow suites | Workiva, Position Green, SAP, osapiens (17 profiled) | workflow subscriptions | they generate no physical-risk evidence — we supply their missing layer |
| Physical-risk specialists | Jupiter, Climate X, Mitiga, XDI (16 profiled) | opaque 5–7-figure enterprise contracts | we publish prices and sell self-serve from €19 |
| Talaix | — | transparent evidence packs, €19–249/month | open-source engine; evidence classes on every value |

## 8. Technology and data

The engine is EO-native: satellite data is not an input we buy, it is what we are built on. ~25 integrated datasets (Sentinel-2, Landsat, NASA FIRMS VIIRS/MODIS, ESA WorldCover, Copernicus DEM family, ERA5/ERA5-Land, GloFAS, GEOGLOWS, CAMS and official non-satellite sources), selected from a 168-source audited observatory. 1,670 automated tests. The next data steps — Sentinel-1 SAR flood mapping, Copernicus DEM GLO-30, thermal and VHR validation data — are specified item by item in the accompanying document "Talaix — Earth-Observation Data Requirements". Assessments are screening-level today; the validation roadmap with a research partner (LIST/SnT target) raises the flood and wildfire layers to a validated tier in 2027.

## 9. Status and traction

- Platform live: accounts, interactive hazard map, API v2 with Python/JS SDKs, QGIS plugin, reports portal, Academy.
- Pricing published; billing backend complete (awaiting live keys); case-study engine (pilot programme) defined.
- Three anonymized decision case studies published on the reports portal (operator-attested, no invented metrics).
- Outreach running: CSRD companies, insurers, consultants scheduled this month; 15 investor funds contacted; first replies arriving (incubation discussions opened).
- Open-source engine (tore, EUPL-1.2) published for technical diligence.
- Pre-revenue by design: funnel, pricing and compliance positioning were finished first, this month.

## 10. Roadmap summary

Detailed in the accompanying "Talaix — 24-Month Roadmap": Luxembourg S.à r.l. and ESA BIC application Q4 2026; Sentinel-1 flood module Q1 2027; ESA Business Applications feasibility study Q2 2027; validation published Q3 2027; CSRD buying-season push Q4 2027 (45 customers, ~€150K ARR run-rate); ~90 customers and ~€400K ARR run-rate by Q3 2028; seed round prepared on those metrics. All figures are quarterly-reviewed targets.

## 11. Financial plan

- 2026: €0 revenue (pre-revenue by design; subscriptions recorded-not-charged until billing ships).
- 2027 (target): ~€80K recognized revenue — pilots, self-serve subscriptions, first Government/Enterprise contracts in Q4.
- 2028 (target): ~€300K recognized revenue; exit ARR run-rate ~€400K.
- 24-month budget: €850K — team 61%, data & cloud 14%, sales & marketing 9%, validation & audits 8%, legal/admin 7%.
- Break-even is not claimed within 24 months; the seed round in 2028 is financed by validated metrics, not projections.

## 12. Funding ask and use of funds

€850K pre-seed (equity or convertible) into a Luxembourg S.à r.l. incorporated Q4 2026 — lead or co-lead, syndication welcome. Complemented by programme co-funding: ESA BIC Luxembourg, LuxIMPULSE, ESA Business Applications feasibility study, later Horizon Europe via the national contact points. Programme support also covers what money alone does not: data access, a validation partner and the space-community network.

## 13. Team

Motaz Omarien, founder — designed and built the entire platform since August 2026: the ten-hazard engine, web platform, CsrdTX compliance rules engine, data observatory and 1,670 automated tests. Based in Luxembourg; incorporating in Luxembourg. Planned hires per the roadmap: an EO engineer (Q1 2027, LIST/SnT pool) and sales/customer success (Q3 2027). Scientific validation and advisory support targeted from LIST and the University of Luxembourg (SnT).

## 14. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Solo founder | two hires in the funded plan; LSA/Luxinnovation network for advisors |
| Validation pending | screening-level status is stated everywhere; validation partner and published validation roadmap in 2027 |
| Regulatory scope shifts | engine serves multiple frameworks and hazards; physical-risk disclosure direction is settled law |
| Long enterprise sales cycles | self-serve wedge and consultant channel carry early revenue; pilots convert slow segments |
| Data-access costs | open Copernicus/NASA data first; commercial VHR only for paid validation cases, via ESA access schemes |

---

Links — Website: https://talaix.com · Reports portal: https://talaix.com/reports.html · Open-source engine: https://github.com/Motaz3d/tore · Founder LinkedIn: https://www.linkedin.com/in/motaz-omarien-8394359/ · Deck (public link): https://drive.google.com/file/d/1Mbs4PxKYbz_uxmaHFtm8nKbyXVH6ynrK/view?usp=drive_link
