# Insurance & Environmental Risk

Talaix Insurance Environmental Risk Profiles combine current per-peril hazard
levels with long-term historical event records for insured assets, plus an
actuarial layer (`src/climate/actuarial.py`) that quantifies event frequencies,
exceedance probabilities, return periods and severity statistics from the real
observed data. The product is aimed at underwriters and reinsurers as an
evidence-based screening layer.

## Purpose

- Provide a pre-catastrophe-model evidence view of an insured asset or
  portfolio.
- Combine (a) current hazard levels from the Green Finance Verification
  engine with (b) historical events from each hazard module's `events()` API.
- Quantify the actuarial screening quantities an underwriter actually uses —
  annual event frequency with an exact confidence interval, annual exceedance
  probability, return period, multi-year horizon probabilities, severity
  statistics and collective-risk moments — strictly from observed data.
- Ship a bilingual (EN/AR) actuarial reference: the formulas and insurance
  terminology (underwriting, pricing, reserving, reinsurance, solvency,
  catastrophe modelling, policy, market) needed to read the profile.
- Support regulatory and prudential contexts (EIOPA stress tests, Solvency II)
  with explicit boundaries on what is not covered.

## Inputs

- **Asset location**: `lat`, `lon`, optional `name`.
- **Search radius**: default 50 km, valid range 1–500 km. Event searches are
  executed within this radius.
- **Portfolio**: list of `{name, lat, lon}` assets, optional shared radius.

## Peril mapping

| Hazard id | Insurance peril label |
|-----------|----------------------|
| flood | Flood (riverine / pluvial) |
| wildfire | Wildfire |
| wind | Windstorm |
| heat | Heatwave |
| drought | Drought |
| coastal | Coastal / storm surge |

Only perils registered in `src.climate.registry` are checked. Missing or
unavailable perils are declared as gaps.

## Events / time dimension

For each peril, the engine calls `module.events(lat, lon, radius_km=...)`. The
result is mapped to:

- `events_status`: `ok`, `unavailable` or `key_required`.
- `events_count`: number of events returned.
- `events_summary`: first 5 events trimmed to safe scalar fields
  (id, date/year, name/title, severity).
- `events_reason`: honest reason when events are unavailable.
- `temporal_coverage`: declared dataset coverage from the module when
  available.

Unavailable event datasets are recorded as declared gaps, never invented.

## Actuarial layer

Each peril carries an `actuarial` block computed by
`src/climate/actuarial.py` (dependency-free; engine version
`ACTUARIAL_VERSION`). Every number is derived from the real event records and
the declared dataset `temporal_coverage()` — where a quantity cannot be
supported, it is `unavailable` with a stated reason.

Per peril (`perils[].actuarial`):

- **Frequency** (`frequency`): annual event rate λ̂ = n/T with an exact
  Poisson (Pearson–Klugman / Garwood chi-square) confidence interval
  (default 90%), a declared screening tier
  (`very_low < 0.02 ≤ low < 0.1 ≤ moderate < 0.5 ≤ high < 1 ≤ very_high`
  events/yr), and a `low_count` flag below 5 observed events
  (limited-fluctuation credibility is weak for tiny samples).
- **Annual exceedance probability**: P(N ≥ 1) = 1 − e^(−λ̂) under the
  explicitly declared homogeneous-Poisson assumption, plus the interval's
  upper-bound AEP.
- **Return period**: 1/AEP in years (`null` when AEP is zero).
- **Horizon probabilities**: P(N ≥ 1) over 5/10/25-year horizons
  (1 − e^(−λ̂·T)) — the policy/mortgage horizon view.
- **Severity** (`severity`): per-metric statistics (n, mean, min, max, std,
  cv) from the numeric fields of the raw event records (e.g. FRP MW for
  wildfire, alert scores) and categorical label counts — dataset-native
  units, never converted to money.
- **Severity distribution fit** (`severity_fit`): lognormal and Pareto fitted
  by MLE on the richest numeric severity metric, with disclosed
  log-likelihood, AIC (selection: lowest) and KS statistic — only at ≥8
  numeric observations, always with the small-sample caveat. Screened against
  degenerate samples (constant values decline the Pareto fit honestly).
- **Frequency trend** (`trend`): non-homogeneous Poisson GLM
  (log λ(t) = a + b·(t − t̄), IRLS) over per-year event counts — the direct
  answer to the stationarity trap. Reports the slope, annual multiplier
  e^b, Wald z/p-value, direction (`increasing` / `decreasing` /
  `no_significant_trend` at p<0.05), and λ at the latest record year vs the
  record average. Requires ≥10 dated events, ≥10 record years and ≥5 active
  years; the detection/reporting-bias caveat (an apparent trend can be a
  completeness artefact) travels with every estimate.
- **Collective risk** (`collective_risk`): compound-Poisson aggregate moments
  E[S] = λ̂·E[X], Var(S) = λ̂·E[X²] in severity-index units per year, using
  the richest numeric severity metric.

Honesty rules of the layer:

- Zero observed events never claims zero risk: the upper confidence bound
  still admits ~3 events per record (rule of three) and a note says so.
- A missing/unparseable temporal coverage yields `partial` when severity
  statistics exist (frequency unavailable, real observations still reported),
  otherwise `unavailable`.
- The Poisson homogeneity assumption and the detection-based catalogue caveat
  travel with every block (`assumptions`).

The profile also carries:

- `actuarial_summary` — cross-peril account view: perils quantified,
  expected annual events across perils, any-peril AEP and return period,
  dominant peril, elevated current levels, significant frequency trends
  (perils whose GLM slope is significant at p<0.05), and the independence
  caveat (perils treated as independent for screening; compound correlation
  is not modelled).
- `actuarial_summary.insurability` — the composite underwriting-attention
  screen: `0.6 × worst frequency-tier pressure + 0.4 × worst current-level
  pressure` on a declared 0–100 rubric, banded (`low_attention` /
  `standard_review` / `enhanced_review` / `senior_referral`). Data adequacy
  is reported separately as confidence (high/medium/low): sparse data lowers
  confidence, never raises the risk score. Screening indicator, not
  validated, not a rating.
- `actuarial_reference` — the reference embedded in every
  profile: 23 formulas (pure premium, collective risk model, Poisson
  frequency, AEP, return period, expected-value and standard-deviation
  premium principles, vulnerability/damage function, loss/combined ratio,
  burning cost, credibility, XL recovery, rate on line, VaR/TVaR,
  chain-ladder, EP curve, stochastic event set, climate conditioning) and 65
  glossary terms across underwriting, pricing, reserving, reinsurance,
  solvency, catastrophe modelling, policy and market categories.

## Presentation

- **Web UI** (`website/js/insurance.js`): an "Actuarial screening" panel on
  the profile (account summary, insurability chip, per-peril λ̂/AEP/return
  period/trend/severity/E[S] table, assumptions & caveats, collapsible EN/AR
  formulas-and-terminology reference), per-peril actuarial blocks inside the
  detail expanders, and actuarial columns (any-peril AEP, dominant peril) in
  the portfolio table.
- **PDF report** (`src/dashboard/insurance_report.py`, v1.1.0): the same
  actuarial screening section — account summary, insurability line, per-peril
  actuarial table, significant trends and caveats — plus per-peril actuarial
  detail lines.

Portfolio results (`_trim_profile`) carry a light `actuarial` trim per asset
(perils quantified, expected annual events, any-peril AEP/return period,
dominant peril), and `portfolio_summary.actuarial` aggregates the sites with
quantified perils and the any-site/any-peril AEP.

## Loss quantification rule

Monetary loss quantification is **not provided**. The profile explicitly
states:

- No ground-up loss estimate.
- No exceedance-probability curve in currency.
- No monetary AAL/PML or scenario loss number.

What the actuarial layer **does** quantify is non-monetary and fully traceable
to observed data: event frequencies with exact intervals, exceedance
probabilities, return periods, horizon probabilities, and severity statistics
in dataset-native units. Everything monetary remains a declared gap.

## Frameworks

- **EIOPA climate and natural-catastrophe stress tests** — regulatory context.
  The profile's per-peril levels and event history provide the physical-
  evidence layer; it is not a scenario or loss model.
- **Solvency II** — prudential context. Can inform underwriting risk
  identification; does not replace internal model or standard-formula
  calculations.
- **Protection gap / EIOPA nat-cat dashboard** — market context. Evidence-
  based screening can help close data gaps on exposed assets.

## Disclaimer

Talaix Insurance Environmental Risk Profiles are screening-level data products
for underwriters and reinsurers. This is **NOT** a vendor catastrophe model,
**NOT** a rate-making or pricing tool, and **NOT** actuarial advice. Levels
are screening indicators unless explicitly labelled validated. Event records
are limited to the declared dataset coverage per peril.

## Relation to Green Finance Verification

Both features use the same `src.climate.verification` engine for current
hazard levels. Insurance & Environmental Risk adds the time dimension via
`module.events()` and uses an insurance peril vocabulary.

## API reference

All endpoints are mounted under `/api/v2/insurance`.

### `GET /api/v2/insurance/profile`

Single-asset risk profile.

Query parameters:

- `lat` — latitude (`-90` to `90`).
- `lon` — longitude (`-180` to `180`).
- `name` — optional asset name.
- `radius_km` — event search radius, default `50`, valid `1`–`500`.

Rate limit: 20/minute.

Response: the full `build_risk_profile` JSON.

### `GET /api/v2/insurance/profile/report`

PDF version of the single-asset profile. Same query parameters. Rate limit:
10/minute. Returns `503` if `reportlab` is not installed.

### `POST /api/v2/insurance/portfolio`

Batch portfolio check. Requires the `registered` role.

Request body:

```json
{
  "name": "optional portfolio name",
  "assets": [
    {"name": "Trier plant", "lat": 49.75, "lon": 6.64},
    {"name": "A Coruña terminal", "lat": 43.3, "lon": -8.4}
  ],
  "radius_km": 50
}
```

Limits: 25 assets for `registered`, 100 for `subscriber` and above.

Response:

```json
{
  "portfolio_id": "…",
  "count": 2,
  "ok_count": 2,
  "portfolio_summary": {
    "site_count": 2,
    "ok_count": 2,
    "level_distribution": {"flood": {"High": 2}},
    "total_declared_gaps": 0
  },
  "results": […]
}
```

### `GET /api/v2/insurance/portfolio/<portfolio_id>`

Return the full stored portfolio record. Owner or admin only. `404` for
unknown IDs, `403` for other users' portfolios.

## Roadmap

- Accumulation indicators across a portfolio.
- Exposure-weighted portfolio metrics.
- ERA5-based long-term danger series per peril.
- Climate conditioning of frequencies (λ_scenario = λ_historical × CF) from
  validated SSP scenario factors — the formula is already in the actuarial
  reference; conditioning factors themselves are applied only once a
  documented, licensed source is integrated (never invented).
- Vulnerability-curve application to exposed values once asset values and
  documented damage functions exist — the engine currently stops at
  non-monetary severity indices by design.
