# Talaix — Solutions Intelligence

**Status:** engine design + knowledge-base schema + technology discovery
framework. Norms: **no invented products, no invented benefits, no
guarantee claims.**

---

## 1. Purpose

Talaix must not merely identify problems — it recommends solutions
**fitted to the exact place**. The Solutions Intelligence engine answers:

> "Given this location, its hazards, climate, terrain, land cover, water,
> people, economy and history — which solutions fit, why, with what
> evidence, benefits, limitations and maturity?"

## 2. Engine inputs

| Input | Source |
|---|---|
| Location + terrain | geocoding, DEM (existing fetchers) |
| Active hazards + severity | hazard plugins (wildfire/flood/drought/heat/wind/coastal) |
| Climate signal | ERA5 climatology via Open-Meteo archive |
| Soil/moisture regime | ERA5-Land soil moisture, NDMI |
| Elevation | EU-DEM/SRTM |
| Vegetation / land cover | ESA WorldCover + Sentinel-2 indices |
| Water | OSM water features, precipitation regime |
| Population / infrastructure | OSM exposure layer |
| Economic activity | exposure categories (see ECONOMIC_INTELLIGENCE.md) |
| Historical events | event store (what actually happened here) |

## 3. Output contract

Each recommended solution carries:

```json
{
  "solution_id": "wetland_restoration",
  "name": "Wetland restoration & flood retention",
  "classes": ["nature_based", "water_management"],
  "hazards_addressed": ["flood", "drought"],
  "why_it_fits": "Flood: 2 high-discharge events since 2015; cropland 38% of window; …",
  "evidence": [ {EvidenceRecord…} ],
  "expected_benefit": {
    "mechanism": "temporarily stores peak flows; declared qualitative",
    "quantified": false,
    "quantification_note": "site-specific hydraulic study required"
  },
  "limitations": ["requires land availability", "multi-year establishment"],
  "implementation_complexity": "medium",
  "maintenance": "low-medium; periodic vegetation management",
  "environmental_considerations": ["habitat gain", "water-table effects to assess"],
  "technology_maturity": "established practice",
  "economic_sectors": ["population_municipal", "agriculture", "insurance_finance"],
  "fit_score": 1.0,
  "fit_band": "high",
  "knowledge_confidence": "high",
  "quantification_status": "not_quantified",
  "data_confidence": "medium",
  "sources": [{"name": "…", "url": "…", "class": "SCIENTIFIC|OPEN_DATA_OFFICIAL", "accessed": "YYYY-MM-DD"}],
  "guarantee_disclaimer": "No solution guarantees prevention of an event."
}
```

Rules:

- `why_it_fits` must quote **real site values** (like the existing
  `ecology.py` species matching) — never generic filler.
- `expected_benefit.quantified` is `true` only when a documented,
  source-bound quantification exists; otherwise the mechanism is
  qualitative and says so.
- `fit_band` is a declared label over the explainable `fit_score`
  (conditions matched / conditions relevant): `high` ≥ 0.99, `moderate`
  ≥ 0.5, `low` below, and `hazard_match_only` when the entry declares no
  site conditions (nothing was verified beyond the hazard gate).
- `economic_sectors` names the sectors the solution class serves
  (population/municipal, agriculture, energy, transport/logistics,
  ports/maritime, real estate/construction, insurance/finance, critical
  facilities, water utilities, forestry, tourism, industry/manufacturing).
- Every solution states limitations. Every output repeats the no-guarantee
  disclaimer.
- Where site data is insufficient → explicit `insufficient_data` path with
  what is missing (existing ecology pattern).

## 3a. Solution packages

The KB declares per-hazard **solution packages** (`solution_packages`) —
combinations whose components address different stages or scales of the
same problem (e.g. flood: early warning + retention + wetland restoration
+ urban drainage + hazard-aware siting). The engine offers a package only
when **at least two components actually fit the site**; unfitted
components are listed with the honest reason. Every package carries
`why_together` (why the combination is useful) and the no-guarantee
disclaimer. Packages never claim prevention.

## 3b. Resilience economics (architecture, all not-quantified today)

The response carries a `resilience_economics` block with the declared
future monetary fields — `adaptation_cost`, `avoided_loss`,
`resilience_investment`, `maintenance_cost`,
`business_interruption_reduction` — all `not_quantified`. The binding
rule: any future monetary value must carry a documented source, method,
assumptions, currency, year and uncertainty; otherwise the field stays
`not_quantified`. ROI is never fabricated.

## 3c. Inferred site sectors

The response carries `site_sectors`: sectors *inferred* from real site
signals (e.g. `Cropland` in the ESA WorldCover window → agriculture; ≥ 20
mapped buildings → municipal/real-estate context). Each entry states its
basis and is labelled `inferred` — context, never measured exposure.

## 4. Knowledge base

`config/solutions_knowledge.json` — curated, sourced entries. Solution
classes: nature-based (forest/wetland/coastal restoration, green
infrastructure, fire-resistant landscape design), engineering (retention,
barriers, drainage, resilient infrastructure), technology (sensors,
remote monitoring, early warning, automation), land management (fuel
management, drought-resistant species, water conservation, smart
irrigation), and emergency capability (detection, logistics).

The existing `config/species_knowledge.json` (16 sourced species) is the
seed of the nature-based/vegetation class and remains the species
authority; the solutions KB references it rather than duplicating it.

Each entry carries applicability conditions (hazards, climate zones,
elevation/water/land-cover constraints), evidence sources, maturity,
complexity, and maintenance — matching the output contract above.

## 5. Technology discovery engine (framework stage)

Purpose: answer *"what technology is most suitable for this place and this
problem?"* — using real sources only.

**Source classes (in trust order):**
1. Scientific publications (methods, field-validated performance)
2. EU/European innovation programmes & project databases (e.g. CORDIS)
3. Government technology programmes
4. Open technology repositories/datasets
5. Patents (where appropriate, metadata only)
6. Commercial providers — **only** where claims are verifiable from an
   independent source; otherwise listed as "provider-stated, unverified"

**Evaluation dimensions** (per technology entry):
fit to hazard + site conditions · evidence level (field-validated /
demonstrated / prototype / provider-stated) · maturity (TRL-style,
declared) · deployment complexity · maintenance · cost basis
("not quantified" unless sourced) · limitations · sources.

**Norms:** no invented products or vendors; no scraped marketing claims
presented as evidence; technologies with no verifiable source are excluded.

## 6. Hazard → solution mapping (initial, curated)

| Hazard | Example solution classes (curated KB entries) |
|---|---|
| Wildfire | fuel management, fire-resistant landscape design, early-warning detection, water-point resilience, species selection (existing), community preparedness |
| Flood | wetland restoration/retention, drainage & SUDS, early warning (discharge-based), resilient siting, green infrastructure |
| Drought | water conservation, smart irrigation, drought-tolerant species, soil-moisture monitoring, water reuse |
| Heat | urban cooling (green/blue), shading, cool materials, heat-health alerting |
| Wind | resilient infrastructure, shelterbelts, grid hardening context |
| Coastal | coastal wetland restoration, dune systems, resilient siting, monitoring/early warning |

Each mapping row is itself sourced in the KB. The engine filters by site
conditions; the KB supplies the candidate space.

## 7. API surface (v2)

`GET /api/v2/solutions?lat=&lon=` → site-fitted solutions across the
location's active hazards, grouped by hazard, each entry per §3, plus an
`insufficient_data` block listing what would sharpen the fit.
