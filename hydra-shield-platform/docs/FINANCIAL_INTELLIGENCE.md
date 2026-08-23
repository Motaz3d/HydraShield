# Talaix — Financial & Insurance Intelligence

**Status:** framework + disclaimers. **Talaix provides evidence and
exposure intelligence — never regulated financial or insurance advice.**

---

## 1. Disclaimer (shown wherever this layer appears)

> Talaix financial/insurance intelligence is an evidence and exposure
> summary built from open data. It is **not** financial advice, **not** an
> insurance quotation, **not** an actuarial product, and **not** a
> substitute for professional assessment. No premium, price, or expected
> loss is calculated unless a documented actuarial/valuation basis is
> integrated and declared.

## 2. Audiences and their questions

| Actor | Questions Talaix helps answer (evidence stage) |
|---|---|
| Investor | How exposed is this asset/region? Which hazards, how frequent historically? What adaptation investment might reduce exposure? What evidence supports the assessment? |
| Insurer | Historical hazard profile at the location; asset exposure; resilience measures present; evidence quality; uncertainty. |
| Bank | Portfolio-location exposure screening; documentation pack per asset. |
| Municipality | Which facilities/areas are exposed; which hazards historically; which solutions fit; evidence for grant applications. |
| Corporate | Site exposure, business-interruption context, supply-chain screening (framework). |
| Infrastructure owner | Asset vs historical hazard behaviour; adaptation options. |
| Real estate | Location hazard history + exposure profile (evidence, not pricing). |
| Energy company | Asset exposure to fire/flood/wind/heat with event history. |

## 3. Intelligence products (evidence stage — implemented)

For a location, the layer assembles **only from real data**:

- **Climate risk score context** — the platform's per-hazard screening
  levels, each with its own validation status and provenance. Scores are
  screening indicators, not validated predictors (see
  `EVIDENCE_ARCHITECTURE.md` §7).
- **Asset exposure profile** — mapped assets in the analysis window
  (from `ECONOMIC_INTELLIGENCE.md` categories).
- **Historical hazard frequency** — counts of documented/observed events
  per hazard per year range from the event store (real datasets only),
  e.g. "ERA5 extreme-heat spells at this grid point: 2019 ×2, 2022 ×3 …".
- **Resilience profile** — mapped protective features (water features,
  fire stations, shelters) + declared data gaps.
- **Evidence pack** — the full evidence list behind the above, exportable
  (report), for an underwriter/investor's own assessment.

## 4. Framework slots (NEXT — never faked)

These exist in the data model as declared, empty-until-real slots:

- **Scenario exposure** — asset exposure under labelled climate scenarios
  (requires the projected-data stage; CMIP6 via Open-Meteo Climate API is
  the leading key-free candidate).
- **Adaptation cost placeholder** — order-of-magnitude cost ranges for
  solutions, only from published sourced figures per solution entry in
  `config/solutions_knowledge.json`; otherwise "not quantified".
- **Avoided-loss analysis** — requires both a documented valuation basis
  and scenario modelling; stated as unavailable until then.
- **Risk pricing context** — hazard behaviour summaries an actuary can
  consume; Talaix never outputs a price.

## 5. Insurance intelligence (implemented scope)

- Hazard frequency + historical events per location (from event store).
- Exposure profile + resilience profile (from OSM/mapped data).
- Uncertainty + evidence quality statement per location (sensor coverage,
  dataset completeness, OSM completeness caveat).
- **Explicitly not done:** premium calculation, loss-cost estimation,
  eligibility decisions. Statement shown: *"Premium calculation requires
  actuarial data that Talaix does not provide."*

## 6. Luxembourg / EU finance relevance (market context)

The framework is shaped for sustainable-finance and climate-risk
workflows common in Luxembourg/EU (disclosure-oriented evidence packs,
traceable sources, scenario labels aligned with projection/scenario
discipline). This is positioning context — it implies **no** regulatory
certification, and no market-size claim is made without a source.
