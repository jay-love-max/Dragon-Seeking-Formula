"""Phase 5 ML pipeline — time-series split and probability calibration (scheme 16)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import average_precision_score, brier_score_loss, log_loss, roc_auc_score
from sklearn.model_selection import TimeSeriesSplit

try:  # scikit-learn >= 1.6
    from sklearn.frozen import FrozenEstimator
except Exception:  # pragma: no cover - older sklearn fallback
    FrozenEstimator = None  # type: ignore[assignment]


@dataclass
class ModelMetadata:
    """Model version metadata (scheme 16.4)."""

    feature_version: str
    rule_version: str
    training_cutoff: str
    sklearn_version: str
    random_seed: int
    training_samples: int
    data_hash: str | None = None


@dataclass
class CalibrationMetrics:
    """Probability calibration metrics (scheme 16.3)."""

    brier_score: float | None = None
    log_loss: float | None = None
    roc_auc: float | None = None
    pr_auc: float | None = None
    n_calibration_samples: int = 0
    calibrated: bool = False


def default_time_series_split(
    n_splits: int = 5,
    gap: int = 1,
) -> TimeSeriesSplit:
    """Default expanding-window split."""
    return TimeSeriesSplit(n_splits=n_splits, gap=gap)


def split_time_series_calibration(
    X: pd.DataFrame,
    y: pd.Series,
    dates: list[str] | pd.Series,
    *,
    holdout_ratio: float = 0.2,
    min_calibration_samples: int = 50,
) -> tuple[pd.DataFrame, pd.Series, pd.DataFrame | None, pd.Series | None]:
    """Split chronological training rows into fit and calibration windows."""
    if X.empty or y.empty:
        return X, y, None, None

    dates_series = pd.Series(dates, index=X.index).astype(str)
    unique_dates = sorted(dates_series.dropna().unique().tolist())
    if len(unique_dates) < 2:
        return X, y, None, None

    holdout_count = max(1, int(round(len(unique_dates) * holdout_ratio)))
    calib_dates = set(unique_dates[-holdout_count:])
    calib_mask = dates_series.isin(calib_dates)
    train_mask = ~calib_mask

    X_train = X.loc[train_mask]
    y_train = y.loc[train_mask]
    X_calib = X.loc[calib_mask]
    y_calib = y.loc[calib_mask]

    if len(X_calib) < min_calibration_samples or len(X_train) == 0:
        return X, y, None, None

    return X_train, y_train, X_calib, y_calib


def _make_calibrator(
    base_model: RandomForestClassifier,
    *,
    method: str,
) -> CalibratedClassifierCV:
    if FrozenEstimator is not None:
        return CalibratedClassifierCV(FrozenEstimator(base_model), method=method)
    return CalibratedClassifierCV(base_model, method=method, cv="prefit")


def _positive_proba(model: Any, X: pd.DataFrame) -> np.ndarray:
    proba = model.predict_proba(X)
    if proba.shape[1] > 1:
        return proba[:, 1]
    return proba[:, 0]


def train_and_calibrate(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    X_calib: pd.DataFrame | None = None,
    y_calib: pd.Series | None = None,
    *,
    random_seed: int = 42,
    n_estimators: int = 100,
    method: str = "sigmoid",
    min_calibration_samples: int = 1000,
) -> tuple[RandomForestClassifier, CalibratedClassifierCV | None, CalibrationMetrics]:
    """Train one RandomForest base model and calibrate it on held-out rows."""
    rf = RandomForestClassifier(
        n_estimators=n_estimators,
        random_state=random_seed,
        class_weight="balanced",
    )
    rf.fit(X_train, y_train)

    metrics = CalibrationMetrics()
    calib_samples = X_calib.shape[0] if X_calib is not None and y_calib is not None else 0
    metrics.n_calibration_samples = calib_samples

    if (
        X_calib is not None
        and y_calib is not None
        and calib_samples >= min_calibration_samples
        and y_calib.nunique() >= 2
    ):
        cal_model = _make_calibrator(rf, method=method)
        cal_model.fit(X_calib, y_calib)
        metrics.calibrated = True

        calib_proba = _positive_proba(cal_model, X_calib)
        try:
            metrics.brier_score = float(brier_score_loss(y_calib, calib_proba))
        except Exception:
            metrics.brier_score = None
        try:
            metrics.log_loss = float(log_loss(y_calib, calib_proba, labels=[0, 1]))
        except Exception:
            metrics.log_loss = None
        try:
            metrics.roc_auc = float(roc_auc_score(y_calib, calib_proba))
        except Exception:
            metrics.roc_auc = None
        try:
            metrics.pr_auc = float(average_precision_score(y_calib, calib_proba))
        except Exception:
            metrics.pr_auc = None
    else:
        cal_model = None
        metrics.calibrated = False

    return rf, cal_model, metrics


def predict_prob(
    model: RandomForestClassifier | CalibratedClassifierCV,
    X: pd.DataFrame,
) -> np.ndarray:
    """Predict the positive-class probability."""
    return _positive_proba(model, X)
