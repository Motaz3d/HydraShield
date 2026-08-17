# HydraShield Validation Architecture

**Status: foundation implemented — the model is NOT yet validated.**
No HydraShield product may be described as validated until the pipeline below
has been executed on real historical data and the resulting report has been
reviewed.

## Goal

Quantify how well the HydraShield screening risk score discriminates days and
places where fires were actually observed from those where they were not,
using only real data and with no temporal leakage.

## Pipeline

```
Sentinel-2 / ERA5 (Open-Meteo archive) / FWI / Terrain / WorldCover
        +
NASA FIRMS historical fire detections   (observed labels)
        ↓
HydraShield risk model (FWI-anchored screening score)
        ↓
Temporal split: train partition (tuning) | evaluation partition (metrics)
        ↓
Confusion matrix → precision / recall / F1 / accuracy / CSI / false-alarm ratio
Calibration (reliability bins) + Brier score
        ↓
Validation report (JSON): period, coverage, sources, model version,
assumptions, limitations, metrics
```

## Components

- `src/prediction/validation.py` — metric machinery: `ConfusionMatrix`
  (TP/FP/TN/FN, precision, recall, F1, accuracy, critical success index,
  false-alarm ratio), `compute_calibration` (reliability bins),
  `brier_score`, `roc_auc` (rank-based Mann-Whitney, tie-corrected, None
  when a class is absent), `pr_auc` (precision-recall area — the
  imbalance-appropriate ranking metric; the no-skill baseline equals the
  positive prevalence), `temporal_train_test_split` (strict date-based
  split — tuning never sees evaluation dates), `select_threshold`,
  `ValidationReport` (self-describing JSON), `evaluate_scores` (driver).
  Learning layer: `analyze_errors` (per-sample error explanations citing the
  real feature values + patterns by month / FWI bin / geography),
  `fit_score_calibration` / `apply_calibration` / `calibration_improvement`
  (empirical score→frequency calibration learned on the train partition
  only, measured on the held-out evaluation partition), and `ModelRegistry`
  (versioned evidence store — candidate status by default, never
  auto-promoted to production).
- `src/prediction/training.py::firms_fire_points_in_range` — real FIRMS
  detections for a bbox over an explicit date range (10-day API windows,
  cached 7 days per window).
- `scripts/run_validation.py` — orchestration on real data (see below).
  Each run also writes an entry into `data/models/registry.json`.
- `src/dashboard/learning.py` — prediction-vs-observation record store
  (SQLite, same database as the cache): model version, prediction time,
  observation time, predicted condition, observed outcome, error, lesson,
  confidence, data sources. Records are evidence only — a model is never
  promoted from them automatically, and never from a single event.

## Ignition-likelihood indicator evaluation

The **Relative Ignition-Likelihood Indicator** (`src/dashboard/ignition.py`)
is evaluated separately from the risk score — ignition likelihood and fire
danger are different concepts and are validated against different questions:

```bash
FIRMS_MAP_KEY=<your key> python scripts/evaluate_ignition.py \
    --bbox -10,36,3,44 --start 2026-07-01 --end 2026-08-10
```

Same anti-leakage discipline (temporal split by day, metrics on the
evaluation partition only), plus ROC-AUC and PR-AUC with the prevalence
baseline because fire positives are rare. The indicator's weather component
(FFMC) is reconstructed per sample date from the ERA5 archive with a 21-day
FWI spin-up; the human-presence component uses present-day WorldPop/OSM
data as a declared vintage approximation. Output:
`data/validation/ignition_evaluation_<start>_<end>.json`, plus one summary
record in the learning store. **Until such a run has been executed and
reviewed, the indicator reports `validation_status.validated = false`
everywhere and must never be quoted as a probability of ignition.**

## Error analysis (learning from errors)

Every validation run identifies, on the evaluation partition only:

- per-sample outcomes (TP/FP/TN/FN) with a generated explanation citing the
  sample's real conditions (FWI, wind, rain, humidity),
- patterns by month (seasonality), by FWI bin (weather conditions) and by
  geographic quadrant (median split),
- the explicit distinction between **fire-danger prediction** and **fire-
  occurrence prediction**: a false positive on a genuinely high-danger day
  is not automatically a model failure — high danger does not guarantee
  ignition, and the report says so.

## Calibration learning

`calibration_improvement` learns an empirical score-bin → observed-fire-
frequency mapping **on the train partition** and reports the Brier score
before/after **on the held-out evaluation partition**. A learned calibration
is recorded as a *candidate* in the model registry; promoting any calibrated
mapping or retrained model into production is a deliberate, reviewed,
manual step — never automatic.


## Running a validation

```bash
cd hydra-shield-platform
source .venv/bin/activate
FIRMS_MAP_KEY=<your key> python scripts/run_validation.py \
    --bbox -10,36,3,44 \
    --start 2026-07-01 --end 2026-08-10 \
    --threshold 65            # or --auto-threshold (tuned on train partition)
```

Output: `data/validation/validation_report_<start>_<end>.json`.

### What is required for FIRMS

1. Register a free NASA FIRMS API key ("MAP_KEY") at
   https://firms.modaps.eosdis.nasa.gov/api/area/
2. Export it as `FIRMS_MAP_KEY` (locally) or add it to `.env` next to
   `docker-compose.yml` (production — already wired into the `api` and
   `watch_checker` services).
3. Archive depth depends on the FIRMS collection; windows that return no
   data contribute nothing — detections are never synthesised.

**Without the key** the script writes a report with `status: "unavailable"`
stating exactly what is missing, and exits non-zero. The public platform
keeps the FIRMS layer marked unavailable in provenance.

## Anti-leakage rules

- Samples are split by **calendar day**: all train-partition dates are
  strictly earlier than all evaluation-partition dates.
- When `--auto-threshold` is used, the threshold is selected by max F1 on
  the train partition only; every reported metric is computed on the
  evaluation partition.
- The operational threshold (65, the High/Extreme boundary) can be evaluated
  directly with `--threshold 65` for an untouched held-out test.

## Declared assumptions & limitations (recorded in every report)

- Negatives are points/dates *without* a FIRMS detection; satellite
  detection gaps (clouds, overpass timing, short-lived fires) may mislabel
  some negatives.
- The validated quantity is the FWI-anchored component of the score
  (slope and fuel-moisture adjustments excluded to bound upstream request
  volume — `slope=0`, `fmc=None`).
- FWI is computed from ERA5-based daily aggregates (21-day spin-up); daily
  aggregates approximate noon-standard inputs.
- Results are specific to the reported bbox and period.

## Public vs scientific layer

The validation machinery is backend-only. The public homepage shows the
live risk snapshot and per-location analyses; validation evidence will be
published (as a scientific report) only after real runs exist — never as
marketing claims.
