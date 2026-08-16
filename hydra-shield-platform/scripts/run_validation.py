#!/usr/bin/env python
"""
Run a real-data validation of the HydraShield screening risk score against
observed fire events (NASA FIRMS).

Pipeline (all real, all declared):

    NASA FIRMS fire detections (bbox x period)      — observed positives
    points/dates in the same bbox without detection — declared negatives
    ERA5 archive weather + FWI spin-up per sample   — real features
    HydraShield screening risk score (FWI-anchored) — model under test
    temporal split (train | evaluation)             — no leakage
    confusion matrix / precision / recall / F1 /
    calibration / Brier score                       — evidence

Usage:

    FIRMS_MAP_KEY=... python scripts/run_validation.py \
        --bbox -10,36,3,44 --start 2026-07-01 --end 2026-08-10 \
        --threshold 65            # or: --auto-threshold

Requirements:
    - FIRMS_MAP_KEY (free): https://firms.modaps.eosdis.nasa.gov/api/area/
      Without it the script writes an "unavailable" report and exits 1 —
      no fire detections are ever invented.
    - Network access to FIRMS and the Open-Meteo archive.

The output JSON (default data/validation/validation_report_<start>_<end>.json)
records period, coverage, sources, model version, assumptions, limitations
and metrics, so it can later feed a scientific validation report.
"""

import argparse
import os
import random
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.prediction import training, validation  # noqa: E402
from src.prediction.validation import ValidationReport  # noqa: E402
from src.dashboard.real_analysis import HydraShieldRealAnalyser  # noqa: E402

MODEL_NAME = "HydraShield screening risk score (FWI-anchored composite)"
MODEL_VERSION = "1.0.0"

ASSUMPTIONS = [
    "A FIRMS detection within the sample day marks a positive; absence marks "
    "a negative at the sampled point (satellite detection gaps may mislabel "
    "some negatives — declared approximation).",
    "FWI is computed from ERA5-based daily aggregates (Open-Meteo archive) "
    "with a 21-day spin-up; daily aggregates approximate noon-standard inputs.",
    "Samples sharing a date are split together (temporal split by day), so "
    "train and evaluation partitions never overlap in time.",
]

LIMITATIONS = [
    "Terrain (slope) and fuel-moisture adjustments are excluded from the "
    "validated score (slope=0, fmc=None) to bound upstream request volume; "
    "the evaluated quantity is the FWI-anchored component of the score.",
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
    p.add_argument("--threshold", type=float, default=65.0,
                   help="high-risk threshold on the 0-100 score (default 65)")
    p.add_argument("--auto-threshold", action="store_true",
                   help="select the threshold by max F1 on the train partition")
    p.add_argument("--train-fraction", type=float, default=0.6,
                   help="fraction of distinct sample days used for tuning (default 0.6)")
    p.add_argument("--max-positives", type=int, default=500)
    p.add_argument("--negative-ratio", type=float, default=1.0)
    p.add_argument("--seed", type=int, default=42,
                   help="seed for reproducible negative sampling")
    p.add_argument("--out", default=None, help="output JSON path")
    return p.parse_args()


def _score_from_features(features):
    """HydraShield screening score from real ERA5/FWI features."""
    fwi = features[4]
    wind = features[2]
    return HydraShieldRealAnalyser._risk_score(
        fwi=fwi, slope=0.0, fmc=None, wind_kmh=wind
    )


def main() -> int:
    args = _parse_args()
    try:
        bbox = tuple(float(x) for x in args.bbox.split(","))
        if len(bbox) != 4:
            raise ValueError
    except ValueError:
        print("✗ --bbox must be west,south,east,north (4 numbers)")
        return 2
    # Validate dates early.
    datetime.strptime(args.start, "%Y-%m-%d")
    datetime.strptime(args.end, "%Y-%m-%d")

    out_path = args.out or os.path.join(
        "data", "validation", f"validation_report_{args.start}_{args.end}.json"
    )
    report = ValidationReport(
        status="unavailable",
        data_period={"start": args.start, "end": args.end},
        geographic_coverage={"bbox": list(bbox)},
        data_sources={
            "fires": "NASA FIRMS VIIRS S-NPP (375 m) area CSV API",
            "weather": "ERA5 reanalysis via Open-Meteo archive",
            "fwi": "Canadian FWI System (Van Wagner 1987), 21-day spin-up",
        },
        model={"name": MODEL_NAME, "version": MODEL_VERSION},
        assumptions=ASSUMPTIONS,
        limitations=LIMITATIONS,
    )

    if not os.environ.get("FIRMS_MAP_KEY"):
        report.message = (
            "NASA FIRMS API key not configured (set FIRMS_MAP_KEY; register "
            "free at https://firms.modaps.eosdis.nasa.gov/api/area/). "
            "Observed fire events are required for validation and are never "
            "invented."
        )
        report.save(out_path)
        print(f"✗ {report.message}\n  Unavailable report written to {out_path}")
        return 1

    # ---- Observed fire events (real) -----------------------------------
    print(f"Fetching FIRMS detections {args.start}..{args.end} for bbox {bbox} ...")
    try:
        fire_points = training.firms_fire_points_in_range(bbox, args.start, args.end)
    except Exception as exc:
        report.message = f"FIRMS retrieval failed: {exc}"
        report.save(out_path)
        print(f"✗ {report.message}")
        return 1
    if not fire_points:
        report.message = ("No FIRMS detections in this bbox/period — validation "
                          "requires observed fire events.")
        report.save(out_path)
        print(f"✗ {report.message}")
        return 1

    rng = random.Random(args.seed)
    rng.shuffle(fire_points)
    positives = fire_points[: args.max_positives]
    fire_keys = {(round(p["lat"], 2), round(p["lon"], 2), p["date"]) for p in fire_points}
    print(f"  {len(fire_points)} detections; using {len(positives)} positives")

    # ---- Samples (positives + declared negatives) ----------------------
    scores, labels, dates = [], [], []
    dropped = 0

    def _add_sample(lat, lon, day, label):
        nonlocal dropped
        feats = training._features_for(lat, lon, day)
        if feats is None:
            dropped += 1
            return
        score = _score_from_features(feats)
        if score is None:
            dropped += 1
            return
        scores.append(score)
        labels.append(label)
        dates.append(day)

    for p in positives:
        _add_sample(p["lat"], p["lon"], p["date"], 1)

    west, south, east, north = bbox
    start_d = datetime.strptime(args.start, "%Y-%m-%d").date()
    end_d = datetime.strptime(args.end, "%Y-%m-%d").date()
    span_days = (end_d - start_d).days
    n_neg_target = int(len([l for l in labels if l == 1]) * args.negative_ratio)
    attempts = 0
    while len([l for l in labels if l == 0]) < n_neg_target and attempts < max(20, n_neg_target * 5):
        attempts += 1
        lat = rng.uniform(south, north)
        lon = rng.uniform(west, east)
        day = (start_d + timedelta(days=rng.randint(0, max(span_days, 0)))).isoformat()
        if (round(lat, 2), round(lon, 2), day) in fire_keys:
            continue
        _add_sample(lat, lon, day, 0)

    print(f"  {len(scores)} scored samples "
          f"({sum(labels)} fire / {len(labels) - sum(labels)} no-fire, {dropped} dropped)")
    if len(scores) < 40 or len(set(labels)) < 2:
        report.message = (f"Too few usable samples ({len(scores)}) for a meaningful "
                          "validation. Widen the bbox or period.")
        report.sample_counts = {"total": len(scores), "dropped": dropped}
        report.save(out_path)
        print(f"✗ {report.message}")
        return 1

    # ---- Temporally separated evaluation --------------------------------
    cm, details = validation.evaluate_scores(
        scores, labels, dates,
        threshold=args.threshold,
        train_fraction=args.train_fraction,
        auto_threshold=args.auto_threshold,
    )

    report.status = "ok"
    report.message = None
    report.model["threshold"] = details["threshold"]
    report.temporal_separation = {
        "train_fraction": args.train_fraction,
        "train_period": details["train_period"],
        "evaluation_period": details["evaluation_period"],
        "train_samples": details["train_samples"],
        "evaluation_samples": details["evaluation_samples"],
        "note": "The threshold (when auto-selected) is tuned on the earlier "
                "train partition only; all reported metrics come from the "
                "later evaluation partition.",
    }
    report.sample_counts = {
        "total": len(scores),
        "positives": sum(labels),
        "negatives": len(labels) - sum(labels),
        "dropped_no_features": dropped,
    }
    report.confusion_matrix = {"tp": cm.tp, "fp": cm.fp, "tn": cm.tn, "fn": cm.fn}
    report.metrics = {
        "precision": cm.precision,
        "recall": cm.recall,
        "f1": cm.f1,
        "accuracy": cm.accuracy,
        "critical_success_index": cm.critical_success_index,
        "false_alarm_ratio": cm.false_alarm_ratio,
        "brier_score": details["brier_score"],
    }
    report.calibration = details["calibration"]
    report.save(out_path)

    print("\nValidation complete (evaluation partition only):")
    print(f"  threshold: {details['threshold']['value']} ({details['threshold']['selection']})")
    print(f"  TP {cm.tp} / FP {cm.fp} / TN {cm.tn} / FN {cm.fn}")
    print(f"  precision {cm.precision}  recall {cm.recall}  F1 {cm.f1}  "
          f"CSI {cm.critical_success_index}")
    print(f"  Report written to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
