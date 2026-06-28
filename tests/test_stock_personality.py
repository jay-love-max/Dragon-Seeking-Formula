"""Phase 4 验收 — 股性评分与 F17 禁买。

覆盖方案第 10 节与 Phase 4 验收:
- 每个子分有独立边界测试;
- B−/C/D 不进入 candidates(通过 personality_blocked_reason);
- 等级边界:74.9 A, 75.0 S, 49.9 B-, 50.0 B+ 等;
- 样本不足返回 UNKNOWN。
"""
from __future__ import annotations

import pytest

from rule_contract import PersonalityGrade, ReasonCode, load_rule_config
from stock_personality import (
    compute_personality,
    personality_blocked_reason,
    score_activity,
    score_capital,
    score_early_board,
    score_explosiveness,
    score_reliability,
)

CFG = load_rule_config()


class TestActivity:
    def test_zero_limit_ups_scores_0(self):
        assert score_activity(0) == 0.0

    def test_30_limit_ups_scores_30(self):
        assert score_activity(30) == pytest.approx(30.0)

    def test_60_limit_ups_scores_60(self):
        assert score_activity(60) == pytest.approx(60.0)

    def test_90_limit_ups_scores_80(self):
        assert score_activity(90) == pytest.approx(80.0)

    def test_120_limit_ups_scores_100(self):
        assert score_activity(120) == 100.0

    def test_150_limit_ups_clamped(self):
        assert score_activity(150) == 100.0


class TestReliability:
    def test_insufficient_sample_returns_0(self):
        assert score_reliability(limit_up_count=3, blown_count=0, min_sample=5) == 0.0

    def test_zero_blown_rate_below_10pct(self):
        assert score_reliability(limit_up_count=20, blown_count=0) == 100.0

    def test_10pct_blown_rate(self):
        assert score_reliability(limit_up_count=20, blown_count=2) == 100.0

    def test_15pct_blown_rate_scores_80(self):
        assert score_reliability(limit_up_count=20, blown_count=3) == 80.0

    def test_25pct_blown_rate_scores_60(self):
        assert score_reliability(limit_up_count=20, blown_count=5) == 60.0

    def test_40pct_blown_rate_scores_40(self):
        assert score_reliability(limit_up_count=10, blown_count=4) == 40.0

    def test_80pct_blown_rate_scores_0(self):
        assert score_reliability(limit_up_count=10, blown_count=8) == 0.0


class TestExplosiveness:
    @pytest.mark.parametrize("boards,expected", [
        (0, 0.0), (1, 5.0), (2, 20.0), (3, 45.0),
        (4, 65.0), (5, 80.0), (6, 90.0), (7, 100.0),
        (10, 100.0),
    ])
    def test_mapping(self, boards, expected):
        assert score_explosiveness(boards) == pytest.approx(expected)


class TestCapital:
    def test_zero_lhb_count(self):
        assert score_capital(0, 0.0) == 0.0

    def test_10_lhb_scores_30(self):
        assert score_capital(10, 0.0) == pytest.approx(30.0)

    def test_net_buy_bonus(self):
        s = score_capital(10, 100_000_000.0)
        assert s > 30.0

    def test_institution_bonus(self):
        s = score_capital(5, 0.0, has_institution=True)
        assert s == pytest.approx(25.0)

    def test_max_clamped(self):
        assert score_capital(100, 1_000_000_000.0) == 100.0


class TestEarlyBoard:
    def test_insufficient_sample(self):
        assert score_early_board(2, 4, min_sample=5) == 0.0

    def test_above_80pct_scores_100(self):
        assert score_early_board(9, 10) == 100.0

    def test_70pct_scores_75(self):
        assert score_early_board(7, 10) == 75.0

    def test_50pct_scores_50(self):
        assert score_early_board(5, 10) == 50.0

    def test_30pct_scores_25(self):
        assert score_early_board(3, 10) == 25.0

    def test_10pct_scores_10(self):
        assert score_early_board(1, 10) == 10.0


class TestCompositeGrade:
    """股性 V2 综合公式(方案 10.2)。"""

    def test_s_grade_75_plus(self):
        s, grade, warn = compute_personality(
            activity=80.0, reliability=80.0, explosiveness=80.0,
            capital=80.0, early_board=80.0, cfg=CFG,
            sample_count=50,
        )
        assert grade == PersonalityGrade.S
        assert s >= 75.0

    def test_a_grade_60_to_74_9(self):
        s, grade, warn = compute_personality(
            activity=65.0, reliability=65.0, explosiveness=65.0,
            capital=50.0, early_board=50.0, cfg=CFG,
            sample_count=50,
        )
        assert grade == PersonalityGrade.A
        assert 60.0 <= s <= 74.9

    def test_b_plus_50_to_59_9(self):
        s, grade, warn = compute_personality(
            activity=55.0, reliability=55.0, explosiveness=55.0,
            capital=40.0, early_board=40.0, cfg=CFG,
            sample_count=50,
        )
        assert grade == PersonalityGrade.B_PLUS

    def test_b_minus_45_to_49_9(self):
        s, grade, warn = compute_personality(
            activity=50.0, reliability=50.0, explosiveness=50.0,
            capital=35.0, early_board=35.0, cfg=CFG,
            sample_count=50,
        )
        assert grade == PersonalityGrade.B_MINUS

    def test_c_30_to_44_9(self):
        s, grade, warn = compute_personality(
            activity=40.0, reliability=40.0, explosiveness=40.0,
            capital=25.0, early_board=25.0, cfg=CFG,
            sample_count=50,
        )
        assert grade == PersonalityGrade.C

    def test_d_below_30(self):
        s, grade, warn = compute_personality(
            activity=25.0, reliability=25.0, explosiveness=25.0,
            capital=15.0, early_board=15.0, cfg=CFG,
            sample_count=50,
        )
        assert grade == PersonalityGrade.D


class TestGradeBoundaries:
    """方案 19.1:等级边界 -ε/等于/+ε。"""

    @pytest.mark.parametrize("score,expected", [
        (75.0, PersonalityGrade.S),
        (74.9, PersonalityGrade.A),
        (60.0, PersonalityGrade.A),
        (59.9, PersonalityGrade.B_PLUS),
        (50.0, PersonalityGrade.B_PLUS),
        (49.9, PersonalityGrade.B_MINUS),
        (45.0, PersonalityGrade.B_MINUS),
        (44.9, PersonalityGrade.C),
        (30.0, PersonalityGrade.C),
        (29.9, PersonalityGrade.D),
    ])
    def test_boundaries(self, score, expected):
        from stock_personality import _grade
        assert _grade(score, CFG) == expected


class TestF17Blocked:
    def test_s_returns_none(self):
        assert personality_blocked_reason(PersonalityGrade.S) is None

    def test_a_returns_none(self):
        assert personality_blocked_reason(PersonalityGrade.A) is None

    def test_b_plus_returns_none(self):
        assert personality_blocked_reason(PersonalityGrade.B_PLUS) is None

    def test_b_minus_blocked(self):
        reason = personality_blocked_reason(PersonalityGrade.B_MINUS)
        assert reason == ReasonCode.PERSONALITY_B_MINUS_BLOCKED

    def test_c_blocked(self):
        reason = personality_blocked_reason(PersonalityGrade.C)
        assert reason == ReasonCode.PERSONALITY_C_BLOCKED

    def test_d_blocked(self):
        reason = personality_blocked_reason(PersonalityGrade.D)
        assert reason == ReasonCode.PERSONALITY_D_BLOCKED

    def test_unknown_flagged(self):
        reason = personality_blocked_reason(PersonalityGrade.UNKNOWN)
        assert reason == ReasonCode.PERSONALITY_DATA_MISSING


class TestInsufficientSample:
    """方案 10.5:样本不足返回 UNKNOWN。"""

    def test_sample_below_threshold(self):
        s, grade, warn = compute_personality(
            activity=80.0, reliability=80.0, explosiveness=80.0,
            capital=80.0, early_board=80.0, cfg=CFG,
            sample_count=5,
        )
        assert grade == PersonalityGrade.UNKNOWN
        assert warn == "insufficient_sample"
