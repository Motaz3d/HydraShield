# Talaix Benchmarks & Model Evaluation

**Status: framework implemented. Benchmark runs are produced only by actually
executing the suite — never by editing a JSON file.**

This document is the contract for the three pieces that make up the
scientific validation core:

| Piece | Where | What it is |
|---|---|---|
| Ground Truth Event Registry | `config/ground_truth_events.json` | REAL, authoritatively documented hazard events used as benchmark anchors |
| Benchmark Suite | `config/benchmark_suite.json` + `src/climate/benchmark.py` | One executable case per ground-truth event |
| Model Evaluation Framework | `src/climate/evaluation.py` + `data/evaluation/runs/` | Immutable evaluation-run records + model lifecycle states |

## The Ground Truth Event Registry

An event enters the registry only with **official sources** (meteorological
and hydrological services, WMO, Copernicus). Each event keeps two things
strictly separate (`signal_basis` field):

- **Occurrence — `DOCUMENTED`**: established by the cited authorities (e.g.
  the UK Met Office verified the 40 °C record of 19 July 2022). Talaix
  does not re-prove the event; the sources stand for it.
- **Expected signal — OBSERVED/MODELLED from our own datasets**: what the
  ERA5 reanalysis or GloFAS modelled discharge *should show* for that event
  at the location's own grid point, defined from the dataset itself (a
  percentile, a spell, a standardized anomaly) — never restated from the
  documentation, never fabricated.

Seeded events: the July 2022 Western-European/UK heatwave, the July 2021 Ahr
valley flood (Copernicus EMS activation EMSR517), Storm Eunice (February
2022), and the Iberian drought of summer 2022.

## What "passed" means — and what it does not mean

A benchmark case executes the model's **own declared detector** (the same
`_series` machinery the hazard modules use) on the case window over real
fetched data (network at execution time, platform-cached).

- **`passed`** = the detector reproduced the expected REAL signal inside the
  declared window. Example: for `bm-eu-heatwave-2022-07`, the heat-spell
  detector (≥3 consecutive days above the location's own day-of-year p90,
  1991–2020 baseline) found a spell overlapping 2022-07-15..2022-07-25.
  The run reports the detection boolean **plus the real values** (spell
  dates, percentiles, z-scores, discharge summaries).
- **`failed`** = the detector ran on real data and did not find the signal.
  That is evidence against the detector's reproduction ability for this
  event — reported, not hidden.
- **`key_required`** = the case cannot run because a prerequisite is
  missing. Never executed, never counted as a failure.
- **`error`** = execution itself failed (fetch error, missing data, bug).
  Reported with the error; the case did not run.

A benchmark pass is **detection reproduction, not a skill score**: it shows
the detector sees the documented real-world signal in our own datasets. It
is not a confusion matrix, not an AUC, and **not a validation claim** —
those require a ground-truth label set and the validation pipeline of
`docs/VALIDATION.md`.

## Why the wildfire case is `key_required`

Wildfire benchmark events must derive from **real NASA FIRMS detections**
via `src/climate/fire_events.py`, which requires `FIRMS_MAP_KEY`. No key ⇒
no events ⇒ nothing to run. The suite ships a declared placeholder case
(`bm-wildfire-firms-placeholder`, model `fwi_system_v1`) with
`execution: key_required`, `expected: null`, and the rule recorded in the
registry: **events are never fabricated** — not dates, not locations, not
signals. Once a key is configured, real FIRMS-derived events become
benchmark cases by the normal "adding a case" path below.

## Adding a benchmark case

1. Add the event to `config/ground_truth_events.json` — only with official
   sources and real URLs, `status: DOCUMENTED` (or `OBSERVED` for
   instrument-anchored entries), `signal_basis` stated, `limitations`
   honest.
2. Add a case to `config/benchmark_suite.json` referencing the event id and
   a `model_id` that exists in `config/model_registry.json`, with a
   `detection.method` pointing at the model's own detector and a declared,
   checkable `pass_criteria` (e.g. "spell detected overlapping window by
   ≥1 day").
3. If the hazard family has no executor yet, add one to
   `src/climate/benchmark.py` (`_EXECUTORS`) reusing the hazard module's
   `_series` machinery — never a parallel implementation.
4. Run the suite and commit nothing about the outcome by hand: the
   immutable run file under `data/evaluation/` is the outcome.

## The lifecycle rule

`config/model_registry.json` carries a `lifecycle` per model along

```
experimental → screening → backtested → validated → operational
               (deprecated from any state)
```

- **`backtested`** requires an executed equation/hindcast-level verification
  on record. Today exactly one model holds it: `fwi_system_v1`, on the
  strength of the equation-level verification against the cffdrs reference
  implementation (`tests/test_fwi.py`, recorded via
  `evaluation.record_fwi_reference_run()` as kind `equation_reference`).
- **`validated`** requires an executed validation-pipeline run on real
  historical data with reported metrics (`docs/VALIDATION.md`).
- **`operational`** requires validated **and** a benchmark-suite run on
  record. **No model goes operational without a benchmark + validation
  run.**
- A lifecycle never advances on intention, documentation, or a single
  event. Promotion is a deliberate, reviewed, manual step; nothing in the
  platform auto-promotes.

## Running the suite

```bash
cd hydra-shield-platform
source .venv/bin/activate
python scripts/run_benchmarks.py        # manual / CI-manual only — not scheduled
```

Output: per-case status lines, an honest summary
(`passed / failed / key_required / errors`), and an immutable run file
`data/evaluation/benchmark_run_<timestamp>.json`. Exit code is 0 unless
`errors > 0`. The same run is available to admins via
`POST /api/v2/benchmarks/run` (compute-intensive: ~10–30-year series per
case, platform-cached).

Read endpoints: `GET /api/v2/ground-truth[?hazard=]`,
`GET /api/v2/ground-truth/<id>`, `GET /api/v2/benchmarks` (definition +
latest run summary), `GET /api/v2/evaluations[?model_id=]`,
`GET /api/v2/evaluations/<run_id>`.

## Relationship to the validation pipeline

Benchmarks and validation answer different questions and are both required
for `operational`:

- **Benchmark** (this document): does the detector reproduce a documented
  real signal in our own datasets? Detection booleans + real values.
- **Validation** (`docs/VALIDATION.md`): does the score discriminate
  observed events from non-events? Confusion matrix, calibration, Brier,
  ROC/PR-AUC on a strict temporal split — needs a real ground-truth label
  set (FIRMS for wildfire).

Neither is quoted as the other. Nothing on the public site claims either
until executed runs exist — the same discipline as `docs/VALIDATION.md`'s
public-vs-scientific layer rule.
