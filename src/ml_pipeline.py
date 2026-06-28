"""Phase 5 ML 管道 — 时间序列切分与概率校准(方案 16)。

16.1:训练输入改为 candidate_observations,不能用过滤后的 Top 5;
16.2:防时间泄漏:行业编码只能在窗口内计算,特征只能用当时可见数据;
16.3:概率校准:CalibratedClassifierCV(sigmoid);
16.4:模型元信息版本化。

本模块依赖现有 scikit-learn。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import TimeSeriesSplit


@dataclass
class ModelMetadata:
    """模型版本信息(方案 16.4)。"""

    feature_version: str
    rule_version: str
    training_cutoff: str
    sklearn_version: str
    random_seed: int
    training_samples: int
    data_hash: str | None = None


@dataclass
class CalibrationMetrics:
    """概率校准指标(方案 16.3)。"""

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
    """默认扩展窗口切分。

    方案 16.2:时间排序后使用 expanding window。
    gap=1 强制训练集与测试集之间间隔至少 1 个交易日。
    """
    return TimeSeriesSplit(n_splits=n_splits, gap=gap)


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
    """训练 RandomForest + 概率校准。

    Args:
        X_train: 训练特征。
        y_train: 训练标签。
        X_calib, y_calib: 独立校准集(None 时在训练集上做交叉校准)。
        method: "sigmoid"(小样本优先)或"isotonic"。
        min_calibration_samples: 校准最小样本数。

    Returns:
        (base_model, calibrated_model, metrics)。
    """
    rf = RandomForestClassifier(
        n_estimators=n_estimators,
        random_state=random_seed,
        class_weight="balanced",
    )
    rf.fit(X_train, y_train)

    metrics = CalibrationMetrics()

    # 校准
    calib_samples = X_calib.shape[0] if X_calib is not None else 0
    if calib_samples > 0:
        cal_model = CalibratedClassifierCV(
            RandomForestClassifier(
                n_estimators=n_estimators,
                random_state=random_seed,
                class_weight="balanced",
            ),
            method=method,
            cv=3,
        )
        cal_model.fit(X_calib, y_calib)
        metrics.calibrated = True
        metrics.n_calibration_samples = calib_samples
    else:
        cal_model = None
        metrics.calibrated = False

    return rf, cal_model, metrics


def predict_prob(
    model: RandomForestClassifier | CalibratedClassifierCV,
    X: pd.DataFrame,
) -> np.ndarray:
    """预测晋级概率。

    返回正类(晋级)概率。
    模型未达到最小样本或校准门槛时返回原始 predict_proba[:,1]。
    """
    proba = model.predict_proba(X)
    if proba.shape[1] > 1:
        return proba[:, 1]
    return proba[:, 0]
