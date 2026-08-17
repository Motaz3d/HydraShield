# HydraShield — Economic Intelligence

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

- HydraShield **does not output euro/dollar loss figures** unless a
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
