#!/usr/bin/env python
"""
Evaluate the Relative Ignition-Likelihood Indicator against REAL observed
fire detections (NASA FIRMS) over a historical period.

Pipeline (all real, all declared):

    NASA FIRMS detections (bbox x period)        — observed positives
    points/dates in the same bbox w/o detection  — declared negatives
    ERA5 archive weather -> FWI spin-up -> FFMC  — real weather component
    WorldPop density + OSM roads (current)       — human-presence component
                                                   (declared vintage approx.)
    ignition.indicator_from_components           — indicator under test
    temporal split (train | evaluation)          — no leakage
    precision/recall/F1, ROC-AUC, PR-AUC, Brier,
    calibration bins, error analysis             — evidence

Usage:

    FIRMS_MAP_KEY=... python scripts/evaluate_ignition.py \
        --bbox -10,36,3,44 --start 2026-07-01 --end 2026-08-10

Without FIRMS_MAP_KEY the script writes an "unavailable" report and exits 1
— no detections are ever invented. Until a real run exists, the ignition
indicator keeps validation_status.validated = False everywhere.

Every executed run also appends one summary record to the learning store
(src/dashboard/learning.py). A single run never promotes the indicator.
"""

import argparse
import os
import random
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.prediction import training, validation  # noqa: E402
from src.prediction.validation import ValidationReport  # noqa: E402
from src.prediction.fwi import compute_fwi_series  # noqa: E402
from src.dashboard import real_data  # noqa: E402
from src.dashboard.cache import default_cache  # noqa: E402
from src.dashboard import ignition as ignition_module  # noqa: E402
from src.dashboard import population as population_module  # noqa: E402
from src.dashboard import exposure as exposure_module  # noqa: E402
from src.dashboard.learning import LearningStore  # noqa: E402

MODEL_NAME = ignition_module.INDICATOR_NAME
MODEL_VERSION = ignition_module.MODEL_VERSION

ASSUMPTIONS = [
    "A FIRMS detection within the sample day marks a positive; absence marks "
    "a negative at the sampled point (satellite detection gaps may mislabel "
    "some negatives — declared approximation).",
    "FFMC is computed from ERA5-based daily aggregates (Open-Meteo archive) "
    "with a 21-day spin-up; daily aggregates approximate noon-standard inputs.",
    "Human-presence inputs (WorldPop reference-year population density and "
    "current OSM road counts) are present-day vintage applied to historical "
    "dates — human presence changes slowly, but this is a declared "
    "approximation.",
    "Samples sharing a date are split together (temporal split by day), so "
    "train and evaluation partitions never overlap in time.",
]

LIMITATIONS = [
    "The indicator's weights and thresholds are a priori; this evaluation "
    "measures their real skill but does not refit them.",
    "Lightning ignitions are outside the indicator's scope; positives caused "
    "by lightning count against it by construction.",
    "VIIRS detects active fires at overpass times; short-lived or cloudy-"
    "scene fires can be missed.",
    "Results are specific to the reported bbox and period and do not "
    "establish skill elsewhere.",
]


def _parse_args():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--bbox", required=True,
                   help="west,south,east,north (degrees), e.g. -10,36,3,44")
    p.add_argument("--start", required=True, help="start date YYYY-MM-DD")
    p.add_argument("--end", required=True, help="end date YYYY-MM-DD")
    p.add_argument("--threshold", type=float, default=45.0,
                   help="'elevated' threshold on the 0-100 indicator (default 45)")
    p.add_argument("--auto-threshold", action="store_true",
                   help="select the threshold by max F1 on the train partition")
    p.add_argument("--train-fraction", type=float, default=0.6)
    p.add_argument("--max-positives", type=int, default=200)
    p.add_argument("--negative-ratio", type=float, default=2.0,
                   help="class-imbalance control: negatives per positive")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--out", default=None, help="output JSON path")
    return p.parse_args()


def _ffmc_for(lat: float, lon: float, day: str):
    """FFMC for one point/date from the real ERA5 archive (cached)."""
    cache = default_cache()
    key = cache.make_key("ign_eval_ffmc", round(lat, 3), round(lon, 3), day)
    hit = cache.get(key)
    if hit is not None:
        return hit.get("ffmc")
    end = datetime.strptime(day, "%Y-%m-%d").date()
    start = end - timedelta(days=21)
    try:
        data = real_data.fetch_weather_archive(lat, lon, start.isoformat(), end.isoformat())
    except Exception:
        data = {"error": "archive unavailable"}
    ffmc = None
    if "error" not in data and data.get("time"):
        tmax = data.get("temperature_2m_max") or []
        rh = data.get("relative_humidity_2m_mean") or []
        wind = data.get("wind_speed_10m_max") or []
        rain = data.get("precipitation_sum") or []
        series_in = []
        for i, t in enumerate(data["time"]):
            if i >= len(tmax) or i >= len(rh) or i >= len(wind):
                break
            if tmax[i] is None or rh[i] is None or wind[i] is None:
                continue
            series_in.append({
                "date": t, "temp_c": float(tmax[i]), "rh_pct": float(rh[i]),
                "wind_kmh": float(wind[i]),
                "rain_mm": float(rain[i] or 0.0) if i < len(rain) else 0.0,
            })
        if len(series_in) >= 5:
            ffmc = float(compute_fwi_series(series_in)[-1].ffmc)
    cache.set(key, {"ffmc": ffmc}, 3600 if ffmc is None else 7 * 24 * 3600)
    return ffmc


def _human_inputs(lat: float, lon: float):
    """Present-day WorldPop density + OSM road count (cached upstream)."""
    pop = population_module.fetch_population(round(lat, 2), round(lon, 2))
    density = pop.get("mean_density_per_km2") if "error" not in pop else None
    osm = exposure_module.fetch_osm_context(round(lat, 2), round(lon, 2))
    roads = (osm.get("counts") or {}).get("roads_all") if "error" not in osm else None
    return density, roads


def main() -> int:
    args = _parse_args()
    try:
        bbox = tuple(float(x) for x in args.bbox.split(","))
        if len(bbox) != 4:
            raise ValueError
    except ValueError:
        print("✗ --bbox must be west,south,east,north (4 numbers)")
        return 2
    datetime.strptime(args.start, "%Y-%m-%d")
    datetime.strptime(args.end, "%Y-%m-%d")

    out_path = args.out or os.path.join(
        "data", "validation", f"ignition_evaluation_{args.start}_{args.end}.json"
    )
    report = ValidationReport(
        status="unavailable",
        data_period={"start": args.start, "end": args.end},
        geographic_coverage={"bbox": list(bbox)},
        data_sources={
            "fires": "NASA FIRMS VIIRS S-NPP (375 m) area CSV API",
            "weather": "ERA5 reanalysis via Open-Meteo archive (FFMC, 21-day spin-up)",
            "population": "WorldPop gridded population (reference year per product)",
            "roads": "OpenStreetMap (ohsome/Overpass), current vintage",
        },
        model={"name": MODEL_NAME, "version": MODEL_VERSION},
        assumptions=ASSUMPTIONS,
        limitations=LIMITATIONS,
    )

    if not os.environ.get("FIRMS_MAP_KEY"):
        report.message = (
            "NASA FIRMS API key not configured (set FIRMS_MAP_KEY; register "
            "free at https://firms.modaps.eosdis.nasa.gov/api/area/). "
            "Observed fire detections are required and are never invented."
        )
        report.save(out_path)
        print(f"✗ {report.message}\n  Unavailable report written to {out_path}")
        return 1

    print(f"Fetching FIRMS detections {args.start}..{args.end} for bbox {bbox} ...")
    try:
        fire_points = training.firms_fire_points_in_range(bbox, args.start, args.end)
    except Exception as exc:
        report.message = f"FIRMS retrieval failed: {exc}"
        report.save(out_path)
        print(f"✗ {report.message}")
        return 1
    if not fire_points:
        report.message = "No FIRMS detections in this bbox/period."
        report.save(out_path)
        print(f"✗ {report.message}")
        return 1

    rng = random.Random(args.seed)
    rng.shuffle(fire_points)
    positives = fire_points[: args.max_positives]
    fire_keys = {(round(p["lat"], 2), round(p["lon"], 2), p["date"]) for p in fire_points}

    scores, labels, dates = [], [], []
    dropped = 0

    def _add_sample(lat, lon, day, label):
        nonlocal dropped
        ffmc = _ffmc_for(lat, lon, day)
        if ffmc is None:
            dropped += 1
            return
        density, roads = _human_inputs(lat, lon)
        result = ignition_module.indicator_from_components(
            ffmc=ffmc,
            population_density_per_km2=density,
            roads_mapped=roads,
        )
        if result["indicator"] is None:
            dropped += 1
            return
        scores.append(result["indicator"])
        labels.append(label)
        dates.append(day)

    for p in positives:
        _add_sample(p["lat"], p["lon"], p["date"], 1)

    west, south, east, north = bbox
    start_d = datetime.strptime(args.start, "%Y-%m-%d").date()
    end_d = datetime.strptime(args.end, "%Y-%m-%d").date()
    span_days = (end_d - start_d).days
    n_neg_target = int(sum(labels) * args.negative_ratio)
    attempts = 0
    while (len(labels) - sum(labels)) < n_neg_target and attempts < max(20, n_neg_target * 5):
        attempts += 1
        lat = rng.uniform(south, north)
        lon = rng.uniform(west, east)
        day = (start_d + timedelta(days=rng.randint(0, max(span_days, 0)))).isoformat()
        if (round(lat, 2), round(lon, 2), day) in fire_keys:
            continue
        _add_sample(lat, lon, day, 0)

    prevalence = sum(labels) / len(labels) if labels else 0.0
    print(f"  {len(scores)} scored samples "
          f"({sum(labels)} fire / {len(labels) - sum(labels)} no-fire, "
          f"{dropped} dropped, prevalence {prevalence:.3f})")
    if len(scores) < 40 or len(set(labels)) < 2:
        report.message = (f"Too few usable samples ({len(scores)}). "
                          "Widen the bbox or period.")
        report.sample_counts = {"total": len(scores), "dropped": dropped}
        report.save(out_path)
        print(f"✗ {report.message}")
        return 1

    cm, details = validation.evaluate_scores(
        scores, labels, dates,
        threshold=args.threshold,
        train_fraction=args.train_fraction,
        auto_threshold=args.auto_threshold,
    )
    train_idx, test_idx = validation.temporal_train_test_split(dates, args.train_fraction)
    test_scores = [scores[i] for i in test_idx]
    test_labels = [labels[i] for i in test_idx]

    roc = validation.roc_auc(test_scores, test_labels)
    pr = validation.pr_auc(test_scores, test_labels)

    report.status = "ok"
    report.model["threshold"] = details["threshold"]
    report.temporal_separation = {
        "train_fraction": args.train_fraction,
        "train_period": details["train_period"],
        "evaluation_period": details["evaluation_period"],
        "train_samples": details["train_samples"],
        "evaluation_samples": details["evaluation_samples"],
        "note": "Metrics are computed on the later evaluation partition only.",
    }
    report.sample_counts = {
        "total": len(scores),
        "positives": sum(labels),
        "negatives": len(labels) - sum(labels),
        "prevalence": round(prevalence, 4),
        "dropped_no_features": dropped,
        "class_imbalance_note": "PR-AUC is reported because positives are rare; "
                                "the no-skill PR baseline equals the prevalence.",
    }
    report.confusion_matrix = {"tp": cm.tp, "fp": cm.fp, "tn": cm.tn, "fn": cm.fn}
    report.metrics = {
        "precision": cm.precision,
        "recall": cm.recall,
        "f1": cm.f1,
        "accuracy": cm.accuracy,
        "roc_auc": roc,
        "pr_auc": pr,
        "pr_auc_baseline_prevalence": round(prevalence, 4),
        "brier_score": details["brier_score"],
    }
    report.calibration = details["calibration"]
    report.error_analysis = {
        "note": "Indicator is relative and uncalibrated; false positives/negatives "
                "are listed in the report file for manual review.",
    }
    report.learning = {
        "status": "evidence only — the indicator is NOT promoted by this run; "
                  "promotion requires repeated multi-period evidence and review",
        "records": "one summary record appended to the learning store",
    }
    report.save(out_path)

    try:
        LearningStore().record(
            kind="ignition",
            model_version=MODEL_VERSION,
            location=f"bbox {bbox}",
            prediction_time=f"{args.start}..{args.end}",
            observation_time=f"{args.start}..{args.end}",
            predicted={"threshold": details["threshold"],
                       "samples": report.sample_counts["total"]},
            observed={"positives": sum(labels), "source": "NASA FIRMS VIIRS S-NPP"},
            error=None,
            lesson=(f"Evaluation partition: F1 {cm.f1}, ROC-AUC {roc}, "
                    f"PR-AUC {pr} (prevalence {round(prevalence, 4)})"),
            confidence="single-run evidence; no promotion",
            sources=list(report.data_sources.values()),
        )
    except Exception as exc:  # learning records must never break the run
        print(f"  (learning record skipped: {exc})")

    print("\nIgnition-indicator evaluation complete (evaluation partition only):")
    print(f"  threshold: {details['threshold']['value']} ({details['threshold']['selection']})")
    print(f"  TP {cm.tp} / FP {cm.fp} / TN {cm.tn} / FN {cm.fn}")
    print(f"  precision {cm.precision}  recall {cm.recall}  F1 {cm.f1}")
    print(f"  ROC-AUC {roc}  PR-AUC {pr} (baseline {round(prevalence, 4)})  "
          f"Brier {details['brier_score']}")
    print(f"  Report written to {out_path}")
    print("  The indicator remains UNVALIDATED for public claims until these "
          "results are reviewed and reproduced over further periods.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
