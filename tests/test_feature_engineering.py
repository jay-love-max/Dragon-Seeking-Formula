"""Phase 5 验收 — 因子工程(限幅归一化、历史共振、封单资金)。

覆盖方案第 13 节与 Phase 5 验收:
- 10/20/30/5cm 和未知板块;
- 3d2b / 4d2b 布尔信号;
- 绝对封单资金边界;
- F14 评分加成。
"""
from __future__ import annotations

import pytest

from feature_engineering import (
    apply_f14_boost,
    check_recent_3d_2b,
    check_recent_4d_2b,
    detect_limit_rule,
    normalize_change_pct,
    seal_funds_penalty_points,
    seal_funds_weak_check,
)
from rule_contract import ReasonCode, load_rule_config

CFG = load_rule_config()


class TestLimitRuleDetection:
    """13.1 板块识别。"""

    @pytest.mark.parametrize("code,name,expected", [
        ("600000", "普通股", 10.0),
        ("300000", "创业板", 20.0),
        ("301000", "创业板2", 20.0),
        ("688000", "科创板", 20.0),
        ("689000", "科创板2", 20.0),
        ("830000", "北交所", 30.0),
        ("400000", "北交所2", 30.0),
        ("600000", "*ST普通", 5.0),
        ("000001", "ST平安", 5.0),
        ("300000", "*ST创业", 5.0),
    ])
    def test_detection(self, code, name, expected):
        assert detect_limit_rule(code, name) == expected

    def test_unknown_sector_defaults_to_10pct(self):
        assert detect_limit_rule("999999", "未知") == 10.0


class TestNormalizeChange:
    def test_normal_10pct_to_10(self):
        assert normalize_change_pct(10.0, 10.0) == 10.0

    def test_20pct_chinext_normalized(self):
        assert normalize_change_pct(20.0, 20.0) == 10.0

    def test_30pct_bse_normalized(self):
        assert normalize_change_pct(30.0, 30.0) == 10.0

    def test_unknown_limit_returns_actual(self):
        assert normalize_change_pct(5.0, 0.0) == 5.0

    def test_partial_normalization(self):
        # 创业板 15% → 归一化 7.5
        assert normalize_change_pct(15.0, 20.0) == 7.5


class TestRecentResonance:
    def test_3d_2b_true(self):
        assert check_recent_3d_2b("600584", {"600584": ["d1", "d2"]}) is True

    def test_3d_2b_false(self):
        assert check_recent_3d_2b("600584", {"600584": ["d1"]}) is False

    def test_3d_2b_missing_code(self):
        assert check_recent_3d_2b("600584", {}) is False

    def test_4d_2b_true(self):
        assert check_recent_4d_2b("600584", {"600584": ["d1", "d2"]}) is True

    def test_4d_2b_false(self):
        assert check_recent_4d_2b("600584", {"600584": ["d1"]}) is False


class TestSealFunds:
    def test_below_50m_no_check(self):
        code, warn = seal_funds_weak_check(30_000_000.0, CFG)
        assert code is None
        assert warn is None

    def test_50m_to_100m_triggers_weak(self):
        code, warn = seal_funds_weak_check(75_000_000.0, CFG)
        assert code == ReasonCode.WEAK_SEAL_50_TO_100M

    def test_at_100m_no_weak(self):
        code, warn = seal_funds_weak_check(100_000_000.0, CFG)
        assert code is None

    def test_above_100m_no_weak(self):
        code, warn = seal_funds_weak_check(150_000_000.0, CFG)
        assert code is None

    def test_penalty_disabled_by_default(self):
        pts = seal_funds_penalty_points(75_000_000.0, CFG)
        assert pts == 0


class TestF14Boost:
    def test_no_boost_without_resonance(self):
        assert apply_f14_boost(100, False, CFG) == 100

    def test_boost_with_resonance(self):
        assert apply_f14_boost(100, True, CFG) == 110

    def test_boost_clamped(self):
        assert apply_f14_boost(140, True, CFG) == 150

    def test_boost_low_score(self):
        assert apply_f14_boost(10, True, CFG) == 11
