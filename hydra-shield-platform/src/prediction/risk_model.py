"""
Machine Learning-based wildfire risk assessment.

Trains and evaluates ML models (e.g., Random Forest, Gradient Boosting) on
historical wildfire data to identify risk patterns and predict fire behavior.

The model supports:
    - Training on historical fire events.
    - Probability prediction of fire occurrence.
    - Feature importance extraction (for SHAP-based explainability).
    - Validation metrics (AUC, precision/recall, Critical Success Index).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np

try:
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.metrics import (
        auc,
        confusion_matrix,
        precision_recall_curve,
        roc_curve,
    )
    from sklearn.model_selection import train_test_split
    _HAS_SKLEARN = True
except ImportError:  # pragma: no cover
    _HAS_SKLEARN = False


@dataclass
class RiskMetrics:
    """Container for model validation metrics."""

    auc_score: float
    precision: float
    recall: float
    critical_success_index: float
    accuracy: float

    def to_dict(self) -> Dict[str, float]:
        """Return metrics as a dictionary."""
        return {
            "auc": self.auc_score,
            "precision": self.precision,
            "recall": self.recall,
            "critical_success_index": self.critical_success_index,
            "accuracy": self.accuracy,
        }


@dataclass
class WildfireRiskModel:
    """
    ML-based wildfire risk model.

    Parameters
    ----------
    n_estimators : int
        Number of trees in the Random Forest.
    max_depth : Optional[int]
        Maximum tree depth.
    random_state : int
        Random seed for reproducibility.
    """

    n_estimators: int = 100
    max_depth: Optional[int] = None
    random_state: int = 42
    model: object = field(default=None, init=False, repr=False)
    feature_names: List[str] = field(default_factory=list, init=False)
    _is_fitted: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        if not _HAS_SKLEARN:
            raise ImportError(
                "scikit-learn is required for WildfireRiskModel. "
                "Install it with: pip install scikit-learn"
            )
        self.model = RandomForestClassifier(
            n_estimators=self.n_estimators,
            max_depth=self.max_depth,
            random_state=self.random_state,
            n_jobs=-1,
        )

    def train(
        self,
        X: np.ndarray,
        y: np.ndarray,
        feature_names: Optional[List[str]] = None,
        test_size: float = 0.2,
    ) -> RiskMetrics:
        """
        Train the model and evaluate on a held-out test set.

        Parameters
        ----------
        X : np.ndarray
            Feature matrix of shape (n_samples, n_features).
        y : np.ndarray
            Binary target labels (0 = no fire, 1 = fire).
        feature_names : Optional[List[str]]
            Names of the features.
        test_size : float
            Fraction of data to hold out for testing.

        Returns
        -------
        RiskMetrics
            Validation metrics on the test set.
        """
        X = np.asarray(X, dtype=float)
        y = np.asarray(y, dtype=int)

        if feature_names is not None:
            self.feature_names = list(feature_names)

        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=test_size, random_state=self.random_state,
            stratify=y if len(np.unique(y)) > 1 else None,
        )

        self.model.fit(X_train, y_train)
        self._is_fitted = True
        y_prob = self.model.predict_proba(X_test)[:, 1]
        y_pred = self.model.predict(X_test)

        return self._compute_metrics(y_test, y_prob, y_pred)

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        """
        Predict probability of fire occurrence.

        Parameters
        ----------
        X : np.ndarray
            Feature matrix.

        Returns
        -------
        np.ndarray
            Probability of fire in [0, 1].
        """
        if not self._is_fitted:
            raise RuntimeError("Model has not been trained yet.")
        return self.model.predict_proba(np.asarray(X, dtype=float))[:, 1]

    def predict(self, X: np.ndarray) -> np.ndarray:
        """
        Predict binary fire occurrence.

        Parameters
        ----------
        X : np.ndarray
            Feature matrix.

        Returns
        -------
        np.ndarray
            Binary predictions.
        """
        if not self._is_fitted:
            raise RuntimeError("Model has not been trained yet.")
        return self.model.predict(np.asarray(X, dtype=float))

    def feature_importances(self) -> Dict[str, float]:
        """
        Return feature importance scores.

        Returns
        -------
        Dict[str, float]
            Mapping of feature name to importance score.
        """
        if not self._is_fitted:
            raise RuntimeError("Model has not been trained yet.")
        importances = self.model.feature_importances_
        if self.feature_names:
            return dict(zip(self.feature_names, importances))
        return {f"feature_{i}": float(v) for i, v in enumerate(importances)}

    def _compute_metrics(
        self,
        y_true: np.ndarray,
        y_prob: np.ndarray,
        y_pred: np.ndarray,
    ) -> RiskMetrics:
        """Compute validation metrics from predictions."""
        # AUC
        try:
            fpr, tpr, _ = roc_curve(y_true, y_prob)
            auc_score = auc(fpr, tpr)
        except Exception:
            auc_score = 0.5

        # Precision / Recall
        cm = confusion_matrix(y_true, y_pred)
        if cm.shape == (2, 2):
            tn, fp, fn, tp = cm.ravel()
        else:
            tn = fp = fn = tp = 0
            if len(cm) == 1:
                if y_pred[0] == 1:
                    tp = cm[0, 0]
                else:
                    tn = cm[0, 0]

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        # Critical Success Index (CSI) = hits / (hits + misses + false alarms)
        csi = tp / (tp + fn + fp) if (tp + fn + fp) > 0 else 0.0
        accuracy = (tp + tn) / (tp + tn + fp + fn) if (tp + tn + fp + fn) > 0 else 0.0

        return RiskMetrics(
            auc_score=float(auc_score),
            precision=float(precision),
            recall=float(recall),
            critical_success_index=float(csi),
            accuracy=float(accuracy),
        )
