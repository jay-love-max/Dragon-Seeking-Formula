"""Tests for volume ratio scoring dimension (E05)."""
from __future__ import annotations

from scorer import _volume_ratio_points


class TestVolumeRatioPoints:
    def test_nuke_threshold_returns_10(self):
        assert _volume_ratio_points(3.5) == 10

    def test_nuke_boundary_3_0_returns_10(self):
        assert _volume_ratio_points(3.0) == 10

    def test_significant_2_to_3_returns_5(self):
        assert _volume_ratio_points(2.5) == 5

    def test_significant_boundary_2_0_returns_5(self):
        assert _volume_ratio_points(2.0) == 5

    def test_neutral_0_8_to_2_returns_0(self):
        assert _volume_ratio_points(1.0) == 0

    def test_neutral_boundary_0_8_returns_0(self):
        assert _volume_ratio_points(0.8) == 0

    def test_shrink_below_0_8_returns_neg3(self):
        assert _volume_ratio_points(0.5) == -3

    def test_none_returns_0(self):
        assert _volume_ratio_points(None) == 0

    def test_nan_returns_0(self):
        assert _volume_ratio_points(float("nan")) == 0

    def test_zero_returns_0(self):
        assert _volume_ratio_points(0.0) == 0

    def test_negative_returns_0(self):
        assert _volume_ratio_points(-1.0) == 0

    def test_non_numeric_string_returns_0(self):
        """非数值字符串触发 except 分支,返回0(降级)。"""
        assert _volume_ratio_points("abc") == 0

    def test_numeric_string_coerces(self):
        """数值字符串能被 float() 转换,走正常阈值路径。"""
        assert _volume_ratio_points("3.0") == 10
