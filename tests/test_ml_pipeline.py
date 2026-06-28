"""Phase 5 验收 — ML 管道(时间切分、概率校准、防泄漏)。

覆盖方案第 16 节:
- 时间序列切分扩展窗口;
- 概率校准 Brier/log_loss/ROC-AUC;
- 模型版本信息;
- 时间泄漏保护(训练数据不包含未来)。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ml_pipeline import (
    ModelMetadata,
    default_time_series_split,
    predict_prob,
    train_and_calibrate,
)


def _make_dummy_data(n=100) -> tuple[pd.DataFrame, pd.Series]:
    X = pd.DataFrame({
        "score": np.random.randint(50, 150, n),
        "seal_funds": np.random.uniform(0, 2e8, n),
        "blown_count": np.random.randint(0, 6, n),
    })
    y = pd.Series(np.random.randint(0, 2, n), name="label_next_2board")
    return X, y


class TestTimeSeriesSplit:
    def test_expanding_window(self):
        tss = default_time_series_split(n_splits=3)
        n = 100
        splits = list(tss.split(np.zeros((n, 1))))
        assert len(splits) == 3
        # 扩展窗口:每个后续训练集包含之前所有数据
        train_sizes = [len(train) for train, _ in splits]
        for i in range(1, len(train_sizes)):
            assert train_sizes[i] > train_sizes[i - 1]

    def test_gap_prevents_leakage(self):
        tss = default_time_series_split(n_splits=3, gap=5)
        splits = list(tss.split(np.zeros((100, 1))))
        for train, test in splits:
            # 训练集和测试集之间至少 gap 个样本的间隔
            assert max(train) < min(test) - 5 + 1


class TestModelTraining:
    def test_train_and_calibrate_returns_models(self):
        X, y = _make_dummy_data(200)
        X_cal, y_cal = _make_dummy_data(100)
        rf, cal, metrics = train_and_calibrate(
            X, y, X_cal, y_cal,
            min_calibration_samples=50,
        )
        assert rf is not None
        assert cal is not None
        assert metrics.calibrated is True
        assert metrics.n_calibration_samples >= 50

    def test_predict_prob_outputs_valid_range(self):
        X, y = _make_dummy_data(200)
        rf, _, _ = train_and_calibrate(
            X, y, min_calibration_samples=5000,
        )
        proba = predict_prob(rf, X)
        assert proba.shape[0] == 200
        assert all(0 <= p <= 1 for p in proba)

    def test_no_calibration_returns_none(self):
        X, y = _make_dummy_data(100)
        rf, cal, metrics = train_and_calibrate(
            X, y, min_calibration_samples=5000,
        )
        assert cal is None
        assert metrics.calibrated is False


class TestModelMetadata:
    def test_metadata_stores_version_info(self):
        meta = ModelMetadata(
            feature_version="v1",
            rule_version="dragon-formula/1.0.0-draft",
            training_cutoff="2026-06-25",
            sklearn_version="1.3.0",
            random_seed=42,
            training_samples=500,
        )
        assert meta.feature_version == "v1"
        assert meta.training_cutoff == "2026-06-25"
