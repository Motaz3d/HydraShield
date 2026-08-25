# DORA & Environmental Operational Resilience — Reserved Business Line (Roadmap, Not Built)

**Status: reserved for a later phase. Nothing in this document is a product,
an endpoint, or a claim of capability. It registers an angle, the assets it
would reuse, and the conditions that must hold before anything is built.**

## 1. The angle (why this line is adjacent, not foreign)

DORA — the Digital Operational Resilience Act, Regulation (EU) 2022/2554, in
application since 17 January 2025 — obliges EU financial entities to manage
ICT risk: governance, incident classification and reporting, resilience
testing, and third-party (vendor) risk. Separately, supervisors (EBA, ECB,
EIOPA) expect climate stress testing that includes *physical* risk scenarios.

The narrow, honest intersection with the Talaix engine:

> Physical ICT and operational assets — data centres, branches, substations,
> network hubs, critical offices — are physical objects at physical
> coordinates. Their exposure to flood, wildfire, heat, wind, drought and
> coastal hazards is exactly the kind of evidence the platform already
> produces for financed and insured assets.

A bank running a DORA register of critical ICT assets, or a climate stress
test over its operational footprint, needs the same per-asset physical-risk
screen the platform already computes for Green Finance and Insurance
clients. Same banking client, same committee (operational resilience /
risk), same evidence engine.

What this line would NOT be (declared boundaries, per the honesty contract):

- **Not a DORA compliance programme.** Governance, incident reporting,
  threat-led penetration testing (TLPT), and vendor-risk management are a
  crowded GRC/consulting market far from the engine. Talaix would sell the
  *physical-exposure evidence layer*, never "DORA compliance".
- **Not cyber security.** No ICT threat detection, no vulnerability
  assessment, no SOC services. The word "security" here means environmental
  security of physical assets only.
- **Not a stress-testing model.** Scenario design, loss modelling and
  capital impact belong to the bank's own models; Talaix supplies hazard
  inputs, not scenarios and not losses (the `not_quantified` rule of the
  Insurance line applies here unchanged).

## 2. What it would reuse (nothing new to invent)

| Existing asset | Role in this line |
|---|---|
| Verification engine (`/api/v2/verification`) | Per-ICT-asset hazard screen (DNSH hazard vocabulary already covers the right physical perils) |
| Insurance engine (`/api/v2/insurance`) | Per-peril levels + long-term event history for operational sites |
| Portfolio batch + persistence | Registers of critical ICT assets are portfolios of coordinates |
| PDF evidence reports | Audit-traceable annexes for the bank's DORA register / stress-test documentation |
| Alerts & monitoring | Continuous watch over critical sites (already built) |
| Academy + Briefs | DORA × physical-risk explainer content for the same committee audience |

## 3. Why it is deferred (deliberately)

1. **The buyer must be earned first.** Operational-resilience committees buy
   from vendors they already trust. The banking relationship is built
   through the Green Finance / Sustainability / Insurance lines; this line
   is an upsell *into* an existing account, not a cold entry.
2. **Vocabulary debt is real.** DORA's ITS/RTS register (incident
   thresholds, register of information, TLPT) is a specialist corpus.
   Entering before the team speaks it fluently would violate rule 1 (the
   methodology is the product).
3. **Focus.** Six active business lines shipped in one engine; a seventh
   half-built one would dilute the evidence-quality bar that is the brand.

## 4. Activation triggers (build only when these hold)

- At least **3 paying banking/insurance clients** on the existing lines, and
  at least one of them asks about operational-site or ICT-asset exposure.
- A written vocabulary review of DORA (Reg. (EU) 2022/2554) and its
  secondary acts completed and absorbed (Academy module candidate).
- A design partner (one of the existing clients) willing to pilot an
  "operational sites exposure annex" built from the existing portfolio
  batch endpoint — *no new engine*, possibly zero new code beyond a report
  template.

## 5. First concrete step when triggered

Extend the Sustainability/Verification report family with an
**"Operational Sites Physical Exposure"** template (DORA-register-friendly
columns: asset role, criticality tier declared by the client, per-hazard
levels, event history, declared gaps) — a new template on the same engine,
per rule 3. Effort estimate at that point: small (weeks, not months),
because every hard part already exists.
