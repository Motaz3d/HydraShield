"""Tests for the validation metric machinery (pure computation, no network)."""

import json
import os

import pytest

from src.prediction import validation
from src.prediction.validation import (
    ConfusionMatrix,
    ValidationReport,
    brier_score,
    compute_calibration,
    compute_confusion_matrix,
    evaluate_scores,
    pr_auc,
    roc_auc,
    select_threshold,
    temporal_train_test_split,
)


# --------------------------------------------------------------------------
# Confusion matrix
# --------------------------------------------------------------------------

def test_confusion_counts():
    cm = compute_confusion_matrix([1, 1, 0, 0, 1], [1, 0, 0, 1, 1])
    assert (cm.tp, cm.fn, cm.tn, cm.fp) == (2, 1, 1, 1)
    assert cm.total == 5


def test_confusion_metrics_known_values():
    cm = ConfusionMatrix(tp=8, fp=2, tn=85, fn=5)
    assert cm.precision == 0.8
    assert cm.recall == round(8 / 13, 4)
    assert cm.f1 == round(2 * 0.8 * (8 / 13) / (0.8 + 8 / 13), 4)
    assert cm.accuracy == round(93 / 100, 4)
    assert cm.critical_success_index == round(8 / 15, 4)
    assert cm.false_alarm_ratio == 0.2


def test_confusion_zero_divisions_are_none():
    assert ConfusionMatrix().precision is None
    assert ConfusionMatrix(tp=0, fp=0, tn=5, fn=0).recall is None
    assert ConfusionMatrix(tp=0, fp=3, tn=5, fn=0).f1 is None


def test_confusion_length_mismatch_raises():
    with pytest.raises(ValueError):
        compute_confusion_matrix([1], [1, 0])


# --------------------------------------------------------------------------
# Calibration & Brier
# --------------------------------------------------------------------------

def test_calibration_bins():
    scores = [5, 15, 25, 85, 95]
    labels = [0, 0, 1, 1, 1]
    bins = compute_calibration(scores, labels, n_bins=10)
    assert sum(b["count"] for b in bins) == 5
    low = next(b for b in bins if b["lower"] == 0)
    high = next(b for b in bins if b["lower"] == 90)
    assert low["observed_frequency"] == 0.0
    assert high["observed_frequency"] == 1.0
    assert high["mean_predicted"] == 95.0


def test_brier_score_perfect_and_worst():
    assert brier_score([0, 100], [0, 1]) == 0.0
    assert brier_score([100, 0], [0, 1]) == 1.0
    assert brier_score([], []) is None


# --------------------------------------------------------------------------
# Temporal split (anti-leakage)
# --------------------------------------------------------------------------

def test_temporal_split_no_leakage():
    dates = ["2026-07-01", "2026-07-02", "2026-07-03", "2026-07-04", "2026-07-05"]
    train_idx, test_idx = temporal_train_test_split(dates, train_fraction=0.6)
    train_dates = {dates[i] for i in train_idx}
    test_dates = {dates[i] for i in test_idx}
    assert train_dates.isdisjoint(test_dates)
    assert max(train_dates) < min(test_dates)
    assert len(train_idx) + len(test_idx) == len(dates)


def test_temporal_split_rejects_degenerate_input():
    with pytest.raises(ValueError):
        temporal_train_test_split(["2026-07-01"] * 5)
    with pytest.raises(ValueError):
        temporal_train_test_split(["a", "b"], train_fraction=1.2)


# --------------------------------------------------------------------------
# Threshold selection & evaluation driver
# --------------------------------------------------------------------------

def test_select_threshold_maximises_f1():
    scores = [10, 20, 30, 70, 80, 90]
    labels = [0, 0, 0, 1, 1, 1]
    threshold, info = select_threshold(scores, labels, candidates=[25.0, 55.0, 95.0])
    assert threshold == 55.0
    assert info["f1_on_selection_partition"] == 1.0


def test_evaluate_scores_uses_evaluation_partition_only():
    # 10 days; first 6 days low scores & no fires, last 4 days high scores & fires.
    dates = [f"2026-07-{d:02d}" for d in range(1, 11)]
    scores = [10.0] * 6 + [80.0] * 4
    labels = [0] * 6 + [1] * 4
    cm, details = evaluate_scores(scores, labels, dates, threshold=65.0,
                                  train_fraction=0.6)
    assert details["evaluation_samples"] == 4
    assert (cm.tp, cm.fp, cm.tn, cm.fn) == (4, 0, 0, 0)
    assert details["train_period"][1] < details["evaluation_period"][0]
    assert details["brier_score"] is not None
    assert isinstance(details["calibration"], list)


def test_evaluate_scores_auto_threshold_tuned_on_train():
    dates = [f"2026-07-{d:02d}" for d in range(1, 11)]
    # Train partition: separation at 50; evaluation partition: same pattern.
    scores = [10, 20, 30, 60, 70, 80, 15, 25, 75, 85]
    labels = [0, 0, 0, 1, 1, 1, 0, 0, 1, 1]
    cm, details = evaluate_scores(scores, labels, dates, auto_threshold=True,
                                  train_fraction=0.6)
    assert details["threshold"]["selection"].startswith("max-F1")
    assert details["threshold"]["value"] <= 60.0
    assert cm.tp + cm.fn == sum(labels[i] for i in range(6, 10))


def test_evaluate_scores_rejects_bad_input():
    with pytest.raises(ValueError):
        evaluate_scores([1.0], [1], ["a", "b"])
    with pytest.raises(ValueError):
        evaluate_scores([], [], [])


# --------------------------------------------------------------------------
# Report structure
# --------------------------------------------------------------------------

def test_validation_report_roundtrip(tmp_path):
    report = ValidationReport(
        status="ok",
        data_period={"start": "2026-07-01", "end": "2026-08-01"},
        geographic_coverage={"bbox": [-10, 36, 3, 44]},
        data_sources={"fires": "NASA FIRMS"},
        model={"name": "screening score", "version": "1.0.0", "threshold": 65},
        sample_counts={"total": 100, "positives": 50, "negatives": 50},
        confusion_matrix={"tp": 40, "fp": 5, "tn": 45, "fn": 10},
        metrics={"precision": 0.8889, "recall": 0.8, "f1": 0.8421},
        calibration=[{"lower": 60, "upper": 70, "count": 10,
                      "mean_predicted": 65.0, "observed_frequency": 0.8}],
        assumptions=["a"], limitations=["l"],
    )
    path = report.save(str(tmp_path / "report.json"))
    data = json.loads(open(path).read())
    for key in ("status", "data_period", "geographic_coverage", "data_sources",
                "model", "confusion_matrix", "metrics", "calibration",
                "assumptions", "limitations", "generated_at"):
        assert key in data
    assert data["metrics"]["f1"] == 0.8421


def test_unavailable_report_carries_reason_and_no_metrics(tmp_path):
    report = ValidationReport(status="unavailable", message="FIRMS_MAP_KEY missing")
    path = report.save(str(tmp_path / "r.json"))
    data = json.loads(open(path).read())
    assert data["status"] == "unavailable"
    assert "FIRMS_MAP_KEY" in data["message"]
    assert data["metrics"] is None
    assert data["confusion_matrix"] is None


# --------------------------------------------------------------------------
# Error analysis
# --------------------------------------------------------------------------

def test_explain_error_false_positive_cites_real_values():
    text = validation.explain_error(
        "fp", {"fwi": 45.0, "rh_mean_pct": 28.0, "wind_max_kmh": 30.0}, 72.0, 65.0)
    assert "45.0" in text
    assert "28" in text
    assert "no ignition" in text
    assert "danger" in text and "occurrence" in text  # distinguishes the two


def test_explain_error_false_negative_cites_conditions():
    text = validation.explain_error(
        "fn", {"fwi": 15.0, "precip_mm": 4.5, "wind_max_kmh": 30.0}, 40.0, 65.0)
    assert "40.0 < 65" in text
    assert "4.5 mm" in text
    assert "wind" in text


def test_analyze_errors_patterns_and_records():
    scores = [20, 80, 75, 30, 85, 25, 70, 35, 22, 78, 33, 88]
    labels = [0, 1, 0, 0, 1, 0, 1, 1, 0, 0, 1, 1]
    dates = ["2026-07-01"] * 6 + ["2026-08-01"] * 6
    feats = [{"fwi": f, "wind_max_kmh": 10.0} for f in
             [5, 42, 40, 8, 44, 6, 38, 9, 5, 41, 10, 46]]
    lats = [36.0, 36.0, 36.0, 38.0, 38.0, 38.0, 36.0, 36.0, 36.0, 38.0, 38.0, 38.0]
    lons = [-7.0, -7.0, -7.0, -7.0, -7.0, -7.0, -4.0, -4.0, -4.0, -4.0, -4.0, -4.0]
    out = validation.analyze_errors(scores, labels, dates, feats, threshold=65.0,
                                    lats=lats, lons=lons)
    types = [r["type"] for r in out["records"]]
    assert types == ["tn", "tp", "fp", "tn", "tp", "tn",
                     "tp", "fn", "tn", "fp", "fn", "tp"]
    assert out["n_errors"] == 4
    assert out["false_positives"][0]["explanation"]
    assert out["false_negatives"][0]["explanation"]
    assert "2026-07" in out["patterns"]["by_month"]
    geo = out["patterns"]["by_geography"]
    assert set(geo.keys()) == {"SW", "NW", "SE", "NE"}
    assert all(v["total"] == 3 for v in geo.values())
    assert "danger" in out["danger_vs_occurrence_note"]


def test_analyze_errors_length_mismatch():
    with pytest.raises(ValueError):
        validation.analyze_errors([1.0], [1], ["d"], [])


# --------------------------------------------------------------------------
# Calibration learning
# --------------------------------------------------------------------------

def test_fit_and_apply_calibration():
    scores = [5, 15, 25, 35, 45, 55, 65, 75, 85, 95] * 4
    labels = ([0] * 5 + [1] * 5) * 4  # fires only above 50
    mapping = validation.fit_score_calibration(scores, labels, n_bins=10)
    calibrated = validation.apply_calibration([10.0, 90.0], mapping)
    assert calibrated[0] < 0.2
    assert calibrated[1] > 0.8
    assert mapping["n_train"] == 40


def test_calibration_improvement_uses_heldout_data():
    train_scores = [5, 15, 25, 35, 45, 55, 65, 75, 85, 95] * 4
    train_labels = ([0] * 5 + [1] * 5) * 4
    eval_scores = [10, 20, 30, 60, 70, 80, 90, 90]
    eval_labels = [0, 0, 0, 1, 1, 1, 1, 1]
    out = validation.calibration_improvement(
        train_scores, train_labels, eval_scores, eval_labels)
    assert out["brier_before"] is not None
    assert out["brier_after"] is not None
    assert "train partition" in out["note"]
    # On this separable toy data, calibration should not make things worse.
    assert out["brier_after"] <= out["brier_before"]


# --------------------------------------------------------------------------
# Model registry
# --------------------------------------------------------------------------

def test_model_registry_records_candidates(tmp_path):
    reg = validation.ModelRegistry(str(tmp_path / "registry.json"))
    entry = reg.record({"model": "screening score", "model_version": "1.0.0",
                        "metrics": {"f1": 0.7}})
    assert entry["status"] == "candidate"  # never auto-promoted
    assert entry["registered_at"]
    versions = reg.list()
    assert len(versions) == 1
    reg.record({"model": "screening score", "model_version": "1.0.1"})
    assert len(reg.list()) == 2


# --------------------------------------------------------------------------
# ROC-AUC / PR-AUC (ranking quality; None when undefined — never fabricated)
# --------------------------------------------------------------------------

def test_roc_auc_perfect_and_reversed():
    assert roc_auc([10, 20, 80, 90], [0, 0, 1, 1]) == 1.0
    assert roc_auc([10, 20, 80, 90], [1, 1, 0, 0]) == 0.0


def test_roc_auc_all_ties_is_chance():
    assert roc_auc([50, 50, 50, 50], [0, 1, 0, 1]) == 0.5


def test_roc_auc_single_class_is_none():
    assert roc_auc([1, 2, 3], [1, 1, 1]) is None
    assert roc_auc([1, 2, 3], [0, 0, 0]) is None


def test_roc_auc_length_mismatch_raises():
    with pytest.raises(ValueError):
        roc_auc([1.0], [1, 0])


def test_pr_auc_perfect_ranking_is_one():
    assert pr_auc([10, 20, 80, 90], [0, 0, 1, 1]) == 1.0


def test_pr_auc_no_positives_is_none():
    assert pr_auc([1, 2, 3], [0, 0, 0]) is None


def test_pr_auc_known_intermediate_value():
    # Highest score is a false alarm, lowest is the positive:
    # area = (recall 0->1) * (precision 1.0->0.5 trapezoid) = 0.25.
    assert pr_auc([90, 10], [0, 1]) == 0.25


def test_pr_auc_length_mismatch_raises():
    with pytest.raises(ValueError):
        pr_auc([1.0], [1, 0])
