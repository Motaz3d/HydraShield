# HydraShield — Annual Climate Extreme Intelligence Report

**Status:** architecture only. **No edition has been generated** — a real
edition requires a dedicated research pass over authoritative annual
datasets with dated source capture. This document defines the structure,
the sourcing rules and the generation pipeline so that future editions
are produced consistently and honestly.

## 1. Concept

The *HydraShield Annual Climate Extreme Intelligence Report* documents a
year of environmental extremes from authoritative datasets — major
wildfire events, floods, droughts, heat extremes, extreme wind and
coastal events — with population and infrastructure exposure, documented
economic consequences, historical comparison, and the solutions and
investment implications that follow. It is simultaneously a scientific
artifact and the platform's annual commercial anchor (campaigns, media,
partnerships).

## 2. Non-negotiable sourcing rules

1. **Primary institutional sources only**: WMO, IPCC, Copernicus
   (C3S/EMS/Marine), EC/JRC (incl. EFFIS/GWIS), NASA, NOAA, ESA, UNDRR,
   UNEP, FAO, World Bank, official national agencies. Media may be used
   only as a secondary REPORTED layer, clearly labelled.
2. **Every number carries**: value, unit, reference period, source
   (institution + dataset + URL), acquisition date, method/context, and
   uncertainty where published.
3. **Monetary figures**: only when an authoritative institution published
   the estimate — shown with currency, year, source, method/context and
   stated uncertainty. Otherwise the section says **"Not quantified from
   available authoritative data."** Global loss totals are never
   fabricated or extrapolated.
4. **Temporal discipline**: OBSERVED / HISTORICAL / MODELLED / PROJECTED
   are never mixed within a figure; year-over-year claims require
   consistent datasets across the compared years.
5. **Causes are DOCUMENTED or UNKNOWN.** No invented attributions.

## 3. Report structure

1. **Executive summary** — the year's documented extremes, with evidence
   counts and explicit uncertainty notes
2. **Per-hazard chapters** (wildfire, flood, drought, heat, wind,
   coastal): major documented events, each with location, period,
   severity evidence, population exposure, source records
3. **Exposure** — population, settlements, infrastructure, business
   exposure for the major events (from the platform's exposure pipeline
   where computable, else cited institutional figures)
4. **Economic consequences** — documented estimates only (rule §2.3)
5. **Sustainability response** — documented adaptation/resilience
   responses to the year's major events; the funding landscape from the
   curated programme records (config/funding_knowledge.json, with
   date_checked); solutions evidence from Solutions Intelligence; lessons
   learned — all under the same sourcing rules, no fabricated rankings
6. **Historical comparison** — trends only where a consistent dataset
   supports them, with the dataset named
7. **Geographic concentration** — where the year clustered
8. **Solutions & resilience investment** — what the evidence supports,
   linked to Solutions Intelligence classes
9. **Method & source appendix** — every dataset with version and access
   date; the platform's evidence vocabulary

## 4. Generation pipeline (target)

```
source capture (dated, archived) → event selection (documented criteria)
→ per-event platform analysis where computable (recorded analysis-runs)
→ exposure computation (real pipelines) → editorial layer (human +
copilot) → evidence audit (every claim → source record) → publication
(PDF + web edition + LinkedIn/annual-report campaign content)
```

Selection criteria are declared per edition (e.g. documented severity
thresholds, exposure magnitude, data availability) — never cherry-picked
silently.

## 5. Roles

- **Platform**: per-event analysis, exposure, evidence records,
  reproducible analysis-run references.
- **Copilot**: source capture tracking, draft sections, claim→source
  audit checklist.
- **Operator**: final editorial authority and publication decision.

## 6. First-edition prerequisites (research required)

- Dated capture of the authoritative annual datasets for the target year
  (WMO statements, Copernicus annual summaries, EFFIS annual fire report,
  national agencies).
- A decision on the reference year and the publication window.
- Legal check on reuse terms of each cited figure (most institutional
  figures are citable with attribution; the appendix records the license
  per source).
