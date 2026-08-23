# Talaix — Product Vision

**Status:** foundational product document. Defines *what* Talaix is becoming and *why*.
Companion documents: `PLATFORM_ARCHITECTURE.md` (how), `IMPLEMENTATION_ROADMAP.md` (when).

---

## 1. From wildfire app to Climate Extreme Intelligence

Talaix began as a wildfire-risk application: real-time fire danger, fuel
moisture, spread modelling and hydration-barrier decision support. That
capability remains — and remains fully operational — but it becomes **one
hazard module** inside a broader platform:

> **Talaix — Climate Extreme Intelligence + Economic Decision Support.**

The central philosophy:

```
SCIENCE + EARTH OBSERVATION + OPEN DATA + HISTORICAL EVIDENCE
+ CLIMATE EXTREME ANALYSIS + ECONOMIC IMPACT
+ FINANCE + INSURANCE + GOVERNMENT + BUSINESS
+ SUSTAINABLE SOLUTIONS
```

The platform exists to answer, for any place on Earth where real data supports it:

- What happened?
- Why did it happen?
- What is happening?
- What could happen?
- Who and what is exposed?
- What does it mean economically?
- What does it mean financially?
- What does it mean for insurance?
- What does it mean for government?
- What should businesses do?
- What sustainable solutions fit *this exact place*?
- What technologies are available?
- What evidence supports the conclusion?
- What happened in previous years?
- What can we learn from those events?

## 2. Conceptual structure

```
HYDRASHIELD — Climate Extreme Intelligence
                │
   Climate & Environmental Intelligence
                │
   ┌────────┬───┴────┬────────┬─────┬──────────┐
 Wildfire  Flood  Drought  Wind  Heat  Coastal …   (hazards — only where real data supports them)
                │
        Exposure Intelligence
   people · cities · infrastructure · business · industry
   agriculture · energy · transport · critical facilities
                │
        Economic Intelligence
   damage · business interruption · supply chain
   asset exposure · regional economic exposure
                │
        Financial Intelligence
   investment · insurance · risk pricing context
   climate finance · resilience investment · ESG
                │
        Solutions Intelligence
   nature-based · engineering · technology · automation
   early warning · adaptation · restoration
                │
             Evidence
   scientific · satellite/EO · open data · historical events · media
```

Every layer below hazards reuses the same map, provenance, reports,
historical analysis, accounts, alerts and API machinery — hazards are
plugins, not products.

## 3. The central promise

The promise is **not** "we predict the future perfectly".

> **"We bring together the best available evidence to understand
> environmental extremes, their consequences, their economic meaning,
> and the actions that can reduce exposure."**

Consequences that follow from this promise:

1. **Real data only.** No fabricated numbers, no fake probabilities, no
   invented historical events, no invented technologies, no fake monetary
   losses or insurance premiums.
2. **Honest labels everywhere.** Every statement is classified
   `OBSERVED / DOCUMENTED / REPORTED / MODELLED / INFERRED / UNKNOWN`, and
   temporally as `OBSERVED / HISTORICAL / FORECAST / PROJECTED / SCENARIO`.
3. **Show me the evidence.** Every important claim is traceable to a
   source record: source, dataset, date, method, confidence, license, link.
4. **Never overclaim causation.** "Cause = X" is stated only when an
   authoritative source establishes it; otherwise the cause is `UNKNOWN`.
5. **No regulated advice.** Financial and insurance layers provide
   *evidence and exposure intelligence*, never regulated financial,
   insurance, or scientific-professional decision replacement.
6. **Solutions, not just problems.** The platform recommends
   place-fitted sustainable solutions — with limitations, never guarantees.

## 4. Audiences

Citizens · Researchers · Businesses · Investors · Insurers ·
Municipalities · Governments.

Each audience gets its own depth of report (the existing
simple / decision-support / scientific split is the seed of this), its own
gating tier (see `USER_AND_SUBSCRIPTION_ARCHITECTURE.md`), and its own
questions answered — on top of one shared evidence base.

## 5. Positioning statement

> Talaix helps society understand extreme environmental events and
> convert scientific evidence into practical decisions.
>
> Science + Technology + Finance + Government + Business + Sustainable solutions.

Talaix does **not** replace professional scientific, financial,
insurance, or governmental decision-making. It makes the underlying
evidence accessible, traceable, and decision-ready.

## 6. Market foundation

Talaix is not built for a single country. **Luxembourg** is
investigated as an initial strategic market because of its concentration
of: sustainable-finance institutions, investment funds, insurance and
reinsurance activity, EU institutions, climate-policy activity, data
infrastructure, and the European research ecosystem (see existing
`docs/Luxembourg_Support_Programs.md` and `Digital_Feasibility_Company_Formation.md`).

The market-intelligence foundation must be reusable for later targets:
EU-wide, wider Europe, Gulf region, North America, and others.

**Rule:** no unsupported market-size claims. Any market figure published by
the platform must carry source, reference period and method — the same
evidence discipline as the climate data.

## 7. Data-infrastructure evolution (strategic direction, not current build)

Talaix may evolve from an application into **climate data
infrastructure**:

```
DATA → PROCESSING → KNOWLEDGE → INTELLIGENCE → API
        → BUSINESS / GOVERNMENT / FINANCE
```

Possible future forms: Climate Intelligence API · Climate
Data-as-a-Service · Earth-observation processing platform · Climate-risk
API · Evidence API.

This is documented here as *strategic architecture only*. We do **not**
build data-center infrastructure now. The current platform is designed
(plugin hazards, typed evidence, versioned API) so that this evolution
remains possible without a rewrite.

## 8. What Talaix must never do

- Invent data where none exists — say "unavailable" instead.
- Present modelled output as observation.
- Present projections or scenarios as current conditions.
- Claim a wildfire cause without an authoritative documented source.
- Fabricate monetary losses, premiums, or market sizes.
- Claim a solution guarantees prevention of an event.
- Let media evidence override scientific or official observations.
- Provide regulated financial, insurance or scientific advice.
