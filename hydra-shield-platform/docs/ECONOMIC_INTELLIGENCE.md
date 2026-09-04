# Talaix — Economic Intelligence

**Status:** framework + first implementation stage.
Norm: **no invented monetary losses.** Where valuation has no documented
basis, the platform says so.

---

## 1. Purpose

Translate climate extremes into economic meaning: *who and what is
exposed, in which sectors, to which hazards — and what that implies*.

Extreme weather becomes economic intelligence through the chain:

```
HAZARD → EXPOSURE (people/assets/sectors) → SUSCEPTIBILITY →
documented impacts (historical events) → exposure profile →
decision context for business, government, finance
```

## 2. Exposure categories

The framework tracks these categories per location/analysis radius:

| Category | Real-data basis today | Notes |
|---|---|---|
| Population | OSM places/buildings (proxy), WorldCover built-up | labelled proxy until a population grid is integrated |
| Buildings | OSM/ohsome building counts | integrated |
| Critical facilities | OSM hospitals, schools, fire stations, … | integrated |
| Transport | OSM roads, railways, ports, airports where mapped | integrated (counts/features) |
| Agriculture | WorldCover cropland class + OSM farmland | integrated |
| Energy | OSM power infrastructure where mapped | integrated (mapped-only caveat) |
| Industry/business | OSM industrial landuse/POIs where mapped | integrated (mapped-only caveat) |
| Water | OSM water features | integrated |
| Tourism | OSM tourism features where mapped | foundation |
| Ports/logistics | OSM harbour/industrial features | foundation |
| Supply chain | framework only — declared data gap | NEXT (requires sector data) |

Every category reports: **what was counted, from which dataset, at what
completeness caveat** ("OpenStreetMap completeness varies by region"), and
the analysis window (hazard event window or current conditions).

## 3. The no-fake-money rule

- Talaix **does not output euro/dollar loss figures** unless a
  documented valuation dataset with a stated method is integrated.
- Where monetary quantification is unavailable, outputs state:
  *"Economic exposure cannot currently be quantified from available
  data."* — and provide the **structured exposure profile** instead
  (counts, categories, hazard context, historical events).
- Historical event damage figures are shown **only** when carried by an
  authoritative source (e.g. an official event database entry), with
  source + reference period + label `DOCUMENTED`/`REPORTED`.

## 4. Risk frameworks (forward-compatible)

The data model reserves — and labels as framework-stage — the standard
distinctions used by climate-finance practice:

- **Physical risk** — exposure of assets/operations to hazards
  (acute: events; chronic: trends). Foundation: per-hazard historical
  frequency + current exposure. **Implemented as exposure profiles.**
- **Transition risk** — policy/technology/market shifts. *Out of data
  scope today*; documented as a framework slot, never populated with
  invented values.
- **Business interruption** — exposed activity × documented event
  duration (from the event model), qualitative until sector data exists.
- **Asset exposure** — which mapped assets sit in the hazard's
  historical/forecast footprint.
- **Regional economic exposure** — sector composition vs hazard
  behaviour; qualitative, source-bound.

## 5. API surface (v2)

`GET /api/v2/economy?lat=&lon=&radius_km=` returns:

```json
{
  "location": {"lat": …, "lon": …},
  "exposure": { "buildings": {"count": 214, "source": "OSM/ohsome", …}, … },
  "hazard_context": {"wildfire": {"historical_events": 3, "…": "…"}, …},
  "monetary_quantification": {
    "status": "not_quantified",
    "statement": "Economic exposure cannot currently be quantified from available data."
  },
  "framework": {
    "physical_risk": "exposure-profile stage",
    "transition_risk": "framework slot — no data",
    "business_interruption": "qualitative",
    "supply_chain": "framework slot — no data"
  },
  "provenance": { … }
}
```

## 6. What this layer deliberately is not

- Not a damage model. Not a loss database. Not a cat-bond tool.
- Not market-size marketing. Market claims follow the same evidence rules
  (source + reference period + method) as climate claims.

## 7. Analytical models (interpretation layer)

`/api/v2/economy` responses carry `analytical_models` — Talaix's
structured interpretation of the exposure profile, not a data dump.
Each model is a declared screening heuristic over the real inputs with
inputs/methodology/output/confidence/limitations:

- `exposure_concentration` — mapped buildings per km² (declared bands)
- `critical_infrastructure` — critical facilities + power per km²
- `economic_activity` — sector presence flags (declared thresholds)
- `hazard_exposure` — hazard level × exposure band → concern class
  (only when a hazard level is supplied; otherwise `not_computed`)
- `resilience_priority` — declared priority rule (high/moderate/standard)
- `evidence_completeness` — how much of the profile is real (never filled)

No monetary values anywhere; the no-fake-money rule (§3) is unchanged.

## 8. Documented losses in the classic reports (implemented 2026-09-04)

The three classic report types (`/api/report?type=simple|decision|scientific`)
now carry a **"Documented disaster losses"** section. It renders published
loss figures whose geographic scope covers the report location's
country/region, and honestly declares the gap when nothing documented
covers it. The section never estimates: figures are tagged `DOCUMENTED`
with source, reference period, geographic scope, licence note and method,
and the section states verbatim that they are *national or multi-country
aggregates — not a loss estimate for the asset*.

Serving paths for observed figures (`src/climate/losses.py::documented_loss_figures`):

1. **NOAA NCEI (live, integrated)** — US-only national aggregates,
   computed at query time; skipped for non-US locations.
2. **Curated `observed_events` (`config/loss_registry.json`)** — a
   hand-maintained registry of well-documented disaster events. Admission
   rule: every figure must be published by an official/primary source
   (e.g. GDV, Munich Re public reviews, official civil-protection counts)
   and carry the full honesty tag set. Monetary values are written in
   words ("billion EUR") — never currency symbols. Events are matched to a
   location by **country-scope bounding boxes, smallest containing bbox
   wins** (country bboxes overlap; the most specific match labels the
   figure). v1 events: July 2021 Western/Central European floods (Bernd),
   August 2002 Elbe/Danube floods, July 2018 Attica wildfires.
3. **Staged exports (operator-provided)** — EM-DAT
   (`data/emdat_export.csv`, register at https://public.emdat.be) and
   DesInventar (`data/desinventar_exports/*.csv`); parsed when present,
   declared with reason when absent.

`estimated_losses`, `modelled_losses`, `projected_losses` remain
`not_available` — the strict separation (§3) is untouched.

Related operational toggle: `FIRMS_MAP_KEY` (free NASA FIRMS registration)
enables the observed-fire history layer in reports; the deploy workflow
forwards it from GitHub secrets to the server env when present.

## 9. Stage 2 (implemented v1, 2026-09-04): Talaix Loss Screening Estimate — ESTIMATED layer

The platform's first monetary function of its own
(`src/climate/loss_estimate.py`): it **computes** an exposed-value
screening range from real engine inputs — nothing is republished from
someone else's database.

```
exposed_value = mapped_buildings (real OSM count, completeness-caveated)
              × floor_area_per_building (declared assumption)
              × replacement_cost_per_m2 (declared per-country benchmark)
computed independently for the low / central / high declared bands
```

- **Benchmarks** live in `config/loss_estimate_benchmarks.json` — every
  band carries a stated basis (published construction-cost ranges);
  countries are matched by bounding box, smallest containing bbox wins;
  unmatched locations fall back to declared generic defaults.
- **Official price calibration (implemented 2026-09-04)**: the bands
  (declared at `price_basis_year` 2023) are dated at query time by the
  official Eurostat construction-cost index `STS_COPI_A`
  (`src/climate/eurostat_cci.py`, SDMX 2.1 TSV, cached 7 d) —
  `factor = CCI(latest) / CCI(basis)` scales all bands equally; the index
  DATES the benchmarks, it never narrows them. Fetch failure degrades to
  the declared bands with an honest reason.
- **Real cadastral floor areas (implemented 2026-09-04, NL first)**:
  where an official cadastre is integrated, the declared floor-area
  assumption is replaced by the real observed mean
  (`src/climate/cadastre.py` — Netherlands BAG via PDOK WFS, open data
  Kadaster, `oppervlakte_min/max` per building). The declared band shape
  is scaled to the real mean and the basis is printed
  (`area_basis: real_cadastral | declared_assumption`). LU/ES/FR
  cadastres follow the same staged pattern.
- **Output**: `{low, central, high}` exposed-value range tagged
  `ESTIMATED`, with inputs, method and limitations printed. The wide span
  is the honest compound of the declared input uncertainties.
- **Expected-loss plumbing (implemented 2026-09-04)**:
  `expected_loss_from_depth` computes exposed value × damage ratio
  (linear interpolation, end-clamped) — pure and tested. It activates
  only when an operator-staged damage curve exists
  (`config/jrc_damage_curves.json`, transcribed licensed JRC values —
  the platform ships no invented curve values) AND a depth input is
  supplied (`?depth_m=` on the estimate endpoint). Otherwise the slot
  stays `not_available` with the reason stated.
- **Separation**: ESTIMATED is rendered as its own sub-block in the
  reports' "Documented disaster losses" section and served separately at
  `GET /api/v2/losses/estimate?lat&lon` — never merged with DOCUMENTED
  figures (§3).
- **Still out of scope**: AAL/PML/EP pricing curves, premium indications,
  company-level allocation. The insurance profile's loss-not-quantified
  rule stays in force.
- **Validation path**: the curated documented events (§8) are the ground
  truth the estimate will be checked against (does the screening range
  for an affected municipality bracket the documented figure?) — that
  comparison is the engine's honesty loop, not marketing.

## 10. Stage 3 (research): insurer-disclosure mining

Direction under evaluation: deduce "which insurer covers which area and
documented how much" from public, legally-mandated disclosures — Solvency
II SFCR reports (EIOPA register), Swiss Re sigma / Munich Re public
annual reviews, and national associations (GDV, CCS Spain, CatNat
France). Any company × region figure derived via market-share allocation
is tagged `INFERRED` with the allocation method printed — never
`DOCUMENTED`.

**Data acquisition:** purchasable APIs and free upgrades that strengthen
the estimate and the registry are studied in
`docs/LOSS_DATA_ACQUISITION.md` (Eurostat cost indices, national
cadastres with real floor areas, JRC flood damage curves, per-address
valuation APIs, PERILS/sigma/NatCat licence paths) — free upgrades first,
purchases only through the registry with verified licences.
