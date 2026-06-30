"""Tests for volume ratio scoring dimension (E05)."""
from __future__ import annotations

from scorer import _volume_position_bonus, _volume_ratio_points


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


class TestVolumePositionBonus:
    # 低位(<0.33): 放量+5, 平量+2, 缩量-2
    def test_low_position_heavy_volume_plus5(self):
        assert _volume_position_bonus(2.5, 0.2) == 5

    def test_low_position_normal_volume_plus2(self):
        assert _volume_position_bonus(1.0, 0.2) == 2

    def test_low_position_shrink_neg2(self):
        assert _volume_position_bonus(0.5, 0.2) == -2

    # 中位(0.33~0.66): 放量+3, 平量0, 缩量-3
    def test_mid_position_heavy_volume_plus3(self):
        assert _volume_position_bonus(2.5, 0.5) == 3

    def test_mid_position_normal_volume_zero(self):
        assert _volume_position_bonus(1.0, 0.5) == 0

    def test_mid_position_shrink_neg3(self):
        assert _volume_position_bonus(0.5, 0.5) == -3

    # 高位(>0.66): 放量-5, 平量-2, 缩量+3
    def test_high_position_heavy_volume_neg5(self):
        assert _volume_position_bonus(3.5, 0.8) == -5

    def test_high_position_normal_volume_neg2(self):
        assert _volume_position_bonus(1.0, 0.8) == -2

    def test_high_position_shrink_plus3(self):
        assert _volume_position_bonus(0.5, 0.8) == 3

    # 边界: position 恰好 0.33 归中位, 0.66 归中位
    def test_boundary_0_33_is_mid(self):
        assert _volume_position_bonus(2.5, 0.33) == 3

    def test_boundary_0_66_is_mid(self):
        assert _volume_position_bonus(2.5, 0.66) == 3

    # 降级
    def test_none_volume_ratio_returns_0(self):
        assert _volume_position_bonus(None, 0.5) == 0

    def test_none_position_returns_0(self):
        assert _volume_position_bonus(2.5, None) == 0

    def test_nan_volume_returns_0(self):
        assert _volume_position_bonus(float("nan"), 0.5) == 0

    def test_zero_volume_returns_0(self):
        assert _volume_position_bonus(0.0, 0.5) == 0

    # 类型强转(try/except 分支, 对照 Task 1 review)
    def test_non_numeric_string_volume_returns_0(self):
        """非数值字符串触发 except 分支,返回0(降级)。"""
        assert _volume_position_bonus("abc", 0.5) == 0

    def test_numeric_string_coerces(self):
        """数值字符串能被 float() 转换,走正常阈值路径。"""
        assert _volume_position_bonus("2.5", "0.2") == 5

    # 边界: vr 恰好 2.0 归放量, 0.8 不归缩量
    def test_heavy_volume_boundary_2_0_is_heavy(self):
        """vr 恰好 2.0 归为放量(heavy>=2.0)。低位放量 → +5。"""
        assert _volume_position_bonus(2.0, 0.2) == 5

    def test_shrink_volume_boundary_0_8_is_normal(self):
        """vr 恰好 0.8 不归缩量(light<0.8),属平量。低位平量 → +2。"""
        assert _volume_position_bonus(0.8, 0.2) == 2

    # 越界: price_position 不在 [0,1] 区间降级(fail-closed)
    def test_position_below_zero_returns_0(self):
        """pos 越界(<0)降级为0(fail-closed)。"""
        assert _volume_position_bonus(2.5, -0.5) == 0

    def test_position_above_one_returns_0(self):
        """pos 越界(>1)降级为0(fail-closed)。"""
        assert _volume_position_bonus(2.5, 1.5) == 0

    # 降级(对照 sibling 类的对称性)
    def test_nan_position_returns_0(self):
        """pos 为 NaN 降级为0。"""
        assert _volume_position_bonus(2.5, float("nan")) == 0

    def test_negative_volume_returns_0(self):
        """vr 为负数降级为0。"""
        assert _volume_position_bonus(-1.0, 0.5) == 0
