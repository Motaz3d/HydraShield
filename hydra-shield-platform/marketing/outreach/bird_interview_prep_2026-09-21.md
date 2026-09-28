# BIRD Incubator — 30-minute interview prep

**Interview window:** Tuesday 22 September → Friday 25 September 2026. Book via the link in Nika Matičić's email (spots limited, book first).
**Format:** 30 minutes with the BIRD team. **The invitation does not say whether it is online or in person in Zagreb** — the programme itself is in person, so do not assume; confirm it when booking, or ask in the reply. If it turns out to be in Zagreb, the "test the video link" item in the checklist below is replaced by travel planning (and the interview week is 22–25 September, so book the trip at the same time as the slot). **Interviewer:** Nika Matičić, Project Manager (BIRD Incubator, Ul. Franje Petračića 4, Zagreb). **Sven** is CC'd on the thread.
**Deck:** `marketing/outreach/talaix_preseed_deck.pdf` (12 slides, generic — no fund-specific mentions). **Regenerate it first**: it still says "8 hazards" in five places; the engine screens 10.
**Timezone:** Zagreb and Luxembourg are both CET/CEST — no offset to compute.
**Programme reality (from the invitation):** in person in Zagreb. Phase 1 to Christmas: every Tuesday and Thursday, 18:00–20:00. Phase 2 after Christmas: one or two sessions a month until Demo Day in April. Pre-incorporation projects accepted; company may be registered anywhere; BIRD facilitates pilot introductions to Croatian universities, research institutions and public-sector organisations.

---

## 1. The 60-second opening (say this first)

Talaix turns satellite and open Earth-observation data into physical climate-risk evidence a third party can trace. You give it coordinates; it returns an evidence pack where every figure carries its source, its method, its reference period and its evidence class — observed, estimated, framework or unknown — and where a hazard that cannot be evidenced at that location is stated as unavailable rather than filled in. The market focus is EU disclosure: CSRD/ESRS E1, EU Taxonomy DNSH and EUDR. Insurance, banking and municipal users run on the same engine. It is live in production today, it takes payments, and the analytical engine is open source under EUPL-1.2, so due diligence can read the code instead of trusting a claim.

Then stop and let them ask. Do not present the whole deck slide by slide.

## 2. Likely questions and honest answers

**What is it, in one sentence?**
Climate-risk evidence from Earth observation, traceable to source, for disclosure, underwriting and siting decisions.

**Who pays, and how much?**
Sustainability and risk teams at companies in CSRD scope first; then insurers, banks, investors and municipalities. Prices are published, not negotiated: €19 for a decision pack, €39 for a scientific pack, €49/month Professional, €249/month Business, €490 for a pilot engagement. Marginal delivery cost per report is approximately zero because there is no consultant in the loop.

**What traction do you have?** — Be exact, do not inflate.
Pre-revenue. No paying customer yet. What is real: the platform is live in production, billing is live, ten hazards are modelled, 25 datasets are integrated out of 167 catalogued, the test suite is roughly 1,700 automated tests, and three anonymised real-decision case studies are published with the customer details removed. I will not claim a customer I do not have.

**Why AI and data — why is this a BIRD fit?**
The engine is a data-fusion and modelling system: satellite and reanalysis ingestion, fire-weather and spread modelling, ML risk scoring, and a compliance layer where the ESRS E1 mapping is versioned rules-as-data rather than hard-coded prose. The interesting AI problem is not prediction alone, it is evidence discipline — classifying every output as observed, estimated, framework or unknown, and refusing to output what the data does not support.

**Why Croatia, and why BIRD?**
The Adriatic coast has live wildfire and coastal-exposure problems, so it is a real market and not a theoretical one. Croatia also gives access to research capacity — the Faculty of Electrical Engineering and Computing in Zagreb is the obvious partner for technical validation — and to public-sector pilot hosts. BIRD's specialisation in AI and data is the specific reason I applied rather than to a generalist programme.

**What do you need from BIRD?**
Three things: pilot introductions (universities, research institutions, public-sector, utility or forestry organisations), AI and ML mentoring from people who do this at depth, and guidance on Croatian and EU funding routes for climate and digital projects.

**Pre-incorporation — where are you?**
Product and billing are live; there is no legal entity yet. The plan is a Luxembourg company in the fourth quarter, because that is where I live and where the banking and accounting would sit. I am open to registering where the programme thinks it makes most sense.

**Who is on the team?** — Answer directly, do not pad it.
Founder-led, one person, working with AI-assisted development. The engineering output is real and inspectable, but I will be honest that the team is one person today and hiring is part of what the programme and the next funding round are for.

**Competition?**
Two groups. ESG and disclosure suites — Workiva, Position Green, SAP, IBM — handle workflow and carbon accounting but not physical-risk evidence. Physical-risk specialists — Climate X, Jupiter, Mitiga, XDI — are credible but sell opaque five- to seven-figure enterprise contracts. The gap we occupy is transparently priced, standalone evidence packs, with an open-source engine.

**Why now?**
The regulatory calendar is fixed and not optional: EUDR has been in force since 30 December 2025, and CSRD Wave 2 companies report on financial year 2027 with publication in 2028. The deadline does the selling; the buyer needs the evidence now.

**Biggest risk?**
Distribution. The product is built and the evidence discipline is in place; the hard part is reaching the right buyer with a verified contact. That is the honest constraint, not the technology.

**Funding stage?**
Pre-seed. The 24-month plan is €850K, calibrated against comparable European climate-risk rounds rather than a round number. I am also in the ESA BIC track (Luxembourg is the geographic fit) — BIRD and an ESA BIC are complementary, not alternatives.

**How do you handle being wrong about a location?**
That is the design: every claim carries its evidence class, unavailable is printed as unavailable, and the model is labelled screening-level until validation completes. An auditor can trace any number back to its source and reference period.

## 3. Three questions to ask them

1. How strict is the in-person requirement for a founder based in Luxembourg — is presence in Zagreb every Tuesday and Thursday a condition of admission?
2. Is a Luxembourg entity compatible with the programme, or is a Croatian company expected?
3. What are the programme terms — participation fee, equity, or both — and what does the programme provide beyond mentoring (pilots, workspace, compute, funding)?

## 4. Practical checklist

- [ ] Book the interview slot via the link in Nika's email (do this first — spots are limited).
- [ ] Regenerate the deck so the hazard count reads 10 (`python scripts/build_deeptechxl_deck.py`), then re-extract the text and confirm no "8 hazards" remains.
- [ ] Test the video link and audio 10 minutes before the call.
- [ ] Have the live site open in a second window: homepage, `sample.html` (the downloadable sample evidence pack is the strongest single artefact), `capabilities.html`.
- [ ] Have the open-source engine URL ready (`github.com/Motaz3d/tore`) — offering live code inspection is the credibility move.
- [ ] Keep one honest number ready for every claim: 10 hazards, 25 of 167 datasets integrated, ~1,700 tests, €19–€249 published prices.
- [ ] Decide the answer to the relocation question **before** the call — it is the one thing that cannot be improvised.

## 5. Watch-outs

- Do not promise a customer that does not exist, and do not let "pilot-ready" drift into "in use".
- Do not overstate the hazard coverage: ten hazards modelled, and dust and volcanic are honestly unavailable without additional data.
- The 24-month plan targets ESA BIC Luxembourg; if BIRD asks about other programmes, present them as complementary, and be clear that the Zagreb in-person schedule is the open question on your side.
