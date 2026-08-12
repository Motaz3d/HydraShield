"""
Hindcasting validation and feedback loop.

Phase 1 verification is performed through historical hindcasting using
historical burned-area observations from EFFIS. This module computes spatial
overlap and classification metrics between predicted and observed fire extents.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np


@dataclass
class HindcastResult:
    """Container for a single hindcast validation result."""

    event_id: str
    iou: float
    precision: float
    recall: float
    critical_success_index: float
    accuracy: float

    def to_dict(self) -> Dict[str, float]:
        """Return result as a dictionary."""
        return {
            "event_id": self.event_id,
            "iou": self.iou,
            "precision": self.precision,
            "recall": self.recall,
            "critical_success_index": self.critical_success_index,
            "accuracy": self.accuracy,
        }


@dataclass
class HindcastValidator:
    """
    Validate model predictions against historical burned-area observations.

    Parameters
    ----------
    threshold : float
        Probability threshold for classifying a pixel as burned.
    """

    threshold: float = 0.5

    def validate_event(
        self,
        event_id: str,
        predicted_probability: np.ndarray,
        observed_burned: np.ndarray,
    ) -> HindcastResult:
        """
        Validate a single historical fire event.

        Parameters
        ----------
        event_id : str
            Identifier of the historical fire event.
        predicted_probability : np.ndarray
            Predicted burn probability in [0, 1].
        observed_burned : np.ndarray
            Binary observed burned mask (1 = burned, 0 = not burned).

        Returns
        -------
        HindcastResult
            Validation metrics.
        """
        pred = np.asarray(predicted_probability, dtype=float)
        obs = np.asarray(observed_burned, dtype=bool)

        pred_binary = pred >= self.threshold

        tp = np.sum(pred_binary & obs)
        fp = np.sum(pred_binary & ~obs)
        fn = np.sum(~pred_binary & obs)
        tn = np.sum(~pred_binary & ~obs)

        iou = tp / (tp + fp + fn) if (tp + fp + fn) > 0 else 0.0
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        csi = tp / (tp + fn + fp) if (tp + fn + fp) > 0 else 0.0
        accuracy = (tp + tn) / (tp + tn + fp + fn) if (tp + tn + fp + fn) > 0 else 0.0

        return HindcastResult(
            event_id=event_id,
            iou=float(iou),
            precision=float(precision),
            recall=float(recall),
            critical_success_index=float(csi),
            accuracy=float(accuracy),
        )

    def validate_events(
        self,
        events: List[Dict[str, object]],
    ) -> List[HindcastResult]:
        """
        Validate a list of historical fire events.

        Parameters
        ----------
        events : List[Dict[str, object]]
            Each dict must contain 'id', 'predicted_probability', and
            'observed_burned'.

        Returns
        -------
        List[HindcastResult]
            Validation results for each event.
        """
        results: List[HindcastResult] = []
        for event in events:
            event_id = str(event.get("id", "unknown"))
            pred = np.asarray(event["predicted_probability"], dtype=float)
            obs = np.asarray(event["observed_burned"], dtype=bool)
            results.append(self.validate_event(event_id, pred, obs))
        return results

    def aggregate_metrics(
        self,
        results: List[HindcastResult],
    ) -> Dict[str, float]:
        """
        Aggregate metrics across multiple events.

        Parameters
        ----------
        results : List[HindcastResult]
            Individual event validation results.

        Returns
        -------
        Dict[str, float]
            Mean metrics across events.
        """
        if not results:
            return {
                "mean_iou": 0.0,
                "mean_precision": 0.0,
                "mean_recall": 0.0,
                "mean_csi": 0.0,
                "mean_accuracy": 0.0,
            }
        return {
            "mean_iou": float(np.mean([r.iou for r in results])),
            "mean_precision": float(np.mean([r.precision for r in results])),
            "mean_recall": float(np.mean([r.recall for r in results])),
            "mean_csi": float(np.mean([r.critical_success_index for r in results])),
            "mean_accuracy": float(np.mean([r.accuracy for r in results])),
        }
