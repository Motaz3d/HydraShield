# GRC Compliance Direction — Phase Tracker

Operator decision 2026-09-06 (advisory outcome): add **GRC (Governance, Risk,
Compliance) as a product direction**. Do **not** add information security as a
service line — it stays an internal trust enabler only.

**The full market study, the eight strategic decisions and the executive plan
live in `docs/COMPLIANCE_STRATEGY.md` (2026-09-06).** This file remains the
living phase tracker.

## Positioning

- Talaix = the specialized **physical climate-risk evidence layer** that plugs
  into GRC/ESG suites — not a general GRC platform.
- Same TX engine, new packaging: from "risk analysis" to **audit-ready
  compliance evidence**.

## Rationale

- Compliance spend is mandatory with fixed deadlines (CSRD waves 2025–2028,
  ISSB S2 jurisdictions) — the budget exists before outreach; an easier sale
  than discretionary analytics.
- Existing assets: CSRD rules registry in `config/`, `docs/CSRD_TX_ENGINE.md`,
  ESRS E1 evidence brief + published case study, `licensing.html`, evidence
  classes (Observed … Unknown) and screening-level labels — exactly what
  auditors want.
- Competition (Workiva, Sphera, Watershed, …) is mitigated by being the
  evidence layer that **integrates with** the suites, not a replacement.

## Boundaries

- **Information security is not a service offering.** Different buyer (CISO),
  different expertise, and it dilutes the brand. It is an internal trust
  requirement for enterprise procurement only: GDPR posture, security page,
  ISO 27001 / SOC 2 gap list as a future internal roadmap.
- Honesty rules stay binding: screening-level labels until model validation
  completes (`docs/VALIDATION.md`); no fabricated compliance claims or metrics.

## Roadmap

| Phase | Item | Status |
|---|---|---|
| 0 — foundation | CSRD rules registry, ESRS E1 brief + case study, licensing page, evidence classes | ✅ done |
| 1 — compliance evidence pack | CsrdTX rules-as-data engine + XBRL + `/api/v2/csrd` shipped 2026-09-05. Remaining: ESRS E1 datapoint-coverage map per report, E1-9 financial-effects context from loss registries, scenario/time-horizon fields | 🔶 |
| 2 — commercial wiring | Pricing page live 2026-09-04 + free CSRD-check row added 2026-09-06; identity pivot + sustainability.html funnel (scope check → sample pack → €490 pilot → subscribe) shipped 2026-09-06; outreach wave 1 drafted (`marketing/outreach/compliance_wave1.md`, human-gated). **Pricing decision: tiers unchanged** — transparent published prices are the wedge. Remaining: wave build script + sends after operator review | 🔶 |
| 3 — integrations | export formats consumable by GRC/ESG suites; partner API; outreach to 2–3 suite vendors | ⬜ |
| 4 — trust enablers (internal) | security/GDPR page for procurement; ISO 27001 / SOC 2 gap list | ⬜ |

## Sales motion

- Trigger = regulatory deadlines (CSRD wave calendar).
- Buyer = sustainability / risk / CFO office — not the CISO.
- Wedge message: "the physical-risk evidence annex for your CSRD report —
  auditable, sourced, and honest about uncertainty."
