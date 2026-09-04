# Talaix — Loss-Data Acquisition Study (purchasable APIs & free upgrades)

**Status:** study for an operator purchase decision (requested 2026-09-04).
Scope: data sources that strengthen the Talaix loss-screening estimate
(`src/climate/loss_estimate.py`, docs/ECONOMIC_INTELLIGENCE.md §9) and the
documented-loss registry (§8).

**Rule (absolute):** every purchased figure enters the platform only
through the loss registry with a stated licence note; redistribution terms
are verified *before* any figure is served. The ESTIMATED layer stays a
computed Talaix function — a purchased dataset narrows its declared
benchmarks, it never replaces the function with a black box.

## 1. What the engine actually needs (in priority order)

| Need | Why | Current state |
|---|---|---|
| Real building floor areas per country | replaces the declared `floor_area_per_building_m2` assumption (the widest uncertainty driver) | declared assumption 80–200 m2 |
| Per-country replacement-cost calibration | narrows the declared cost bands with an official index | declared screening ranges |
| Damage ratios per hazard | unlocks the `expected_loss` slot (currently `not_available`) | none integrated |
| Documented insured losses per event × country | ground truth for validation + the insurer question | 3 curated events (v1) |

## 2. Free upgrades first (integrate before buying anything)

| Source | What it gives | Access | Classification |
|---|---|---|---|
| **Eurostat API** (`sts_copi` construction-cost indices) | official per-country construction-cost indexation → calibrate benchmark bands per country, keep them dated | free REST API, CC-BY-4.0 | INTEGRATE (free) |
| **Luxembourg cadastre** (data.public.lu) | official parcels/buildings for our home market | open data | INTEGRATE (free) |
| **Netherlands BAG via PDOK** | *real floor area per building* (pand oppervlakte) — removes the area assumption for NL | free API (PDOK locatieserver/OGC) | INTEGRATE (free) |
| **Spain Catastro API** | built area, use, year per cadastral unit — real areas for ES | free public API (rate-limited) | INTEGRATE (free) |
| **France BDNB / data.gouv** | national building database (areas, use) | open licence (Licence Ouverte) | INTEGRATE (free) |
| **JRC global flood depth–damage functions** (Huizinga et al., JRC Technical Reports) | peer-reviewed European flood damage ratios → the `expected_loss` computation for flood | published, free | INTEGRATE (free) — with method printed |
| **EM-DAT staged export** | documented deaths/losses per event × country | free after registration | already staged path (operator file) |

Honest note: cadastral coverage is per-country; the engine keeps the
declared assumption as the documented fallback wherever no real-area
source is integrated, and says which basis was used per estimate.

## 3. Commercial candidates to study (cheapest-first)

| Provider | What it would add | Pricing position | Classification |
|---|---|---|---|
| **PriceHubble** (Zurich) | per-address property valuation/characteristics API (EU coverage incl. CH/DE/AT/FR/BE/NL/LU) → per-asset exposed value instead of an aggregate screening range | per-call tiered; startup-friendly tiers advertised historically — verify current pricing | STUDY → trial (low commitment) |
| **RealAdvisor** (Geneva) | smaller alternative to PriceHubble for property estimates | per-call; lower volume tiers | STUDY (compare in the same trial) |
| **CATDAT / Risklayer** (Karlsruhe) | event-loss database + cat-model components; EU research DNA; cheaper than the big two | not public — on request | STUDY → quote |
| **PERILS AG** (Zurich) | the European industry insured-loss index per event × country (windstorm/flood/…) — the direct answer to "who documented how much where" | subscription; **redistribution restricted** — figures could feed internal validation, not republication, unless the licence allows | LEGAL/TERMS REVIEW REQUIRED |
| **Swiss Re sigma / Munich Re NatCatSERVICE** | the reference loss databases | enterprise pricing; already `planned` in the registry after first revenue (operator decision 2026-09-02) | DEFERRED (planned) |
| **JBA Risk / Fathom / KatRisk** | flood hazard depth maps (damage-ratio inputs), not losses | not public — on request | RESEARCH REQUIRED |
| **Verisk (AIR) / Moody's RMS** | full cat models | enterprise; out of "cheap" scope | DEFERRED |

## 4. Recommended sequence

1. **Now (free):** Eurostat cost indices → calibrate `loss_estimate_benchmarks.json`
   per country with dated official indices; JRC flood curves → the first
   real `expected_loss` computation (flood only, method printed, still
   ESTIMATED); cadastres (LU first, then NL/ES/FR) → real floor areas
   where covered, declared assumption elsewhere.
2. **Trial (cheap):** a PriceHubble-class per-address valuation API for the
   subscriber tier — per-asset exposed value as a paid feature; measure
   cost per report before committing.
3. **Study (licence-bound):** PERILS for insured-loss validation *if* the
   licence permits our use; sigma reports (free PDFs) already feed the
   curated registry manually.
4. **Later (post-revenue):** NatCatSERVICE / sigma database licences as
   already planned.

## 5. What we will NOT do

- No scraping of insurer PDFs or sigma reports into served figures —
  manual curation with citation only (the §8 curated events pattern).
- No black-box purchased score served as a Talaix figure — purchased data
  calibrates declared benchmarks; the function and its method stay ours.
- No republication of licence-restricted figures (PERILS/NatCat/sigma
  databases) — internal validation only unless the licence says otherwise.
