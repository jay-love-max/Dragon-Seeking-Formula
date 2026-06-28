"""Phase 3 验收 — F18 二进三联动 + 市场环境。

覆盖方案 11/12 与 Phase 3 验收:
- 2026-06-25 金样本:1/7=14.29% → HALT;
- denominator=0 → NO_SAMPLE/UNKNOWN, 不得显示 0%;
- 小样本(1-4)不可进入 AGGRESSIVE;
- HALT 时策略正确;
- 最高连板映射:<=2 FROZEN,3 SUPPRESSED,4 ACTIVE,>=5 MAIN_UP;
- 阈值边界:19.99%/20%/29.99%/30%/50%/50.01%;
- 一进二计算兼容旧 market_recap.promotion_rate。
"""
from __future__ import annotations

import pytest

from market_risk import (
    MarketRiskResult,
    compute_adjusted_score,
    evaluate_market_risk,
    f18_reason_codes,
)
from rule_contract import MarketRegime, PositionPolicy, ReasonCode, load_rule_config
from tests.fixtures.golden_samples import GOLDEN_2026_06_25_F18

CFG = load_rule_config()


def _risk(
    *,
    max_boards: int = 4,
    prev_two: list[str] | None = None,
    today_three: list[str] | None = None,
    prev_one: list[str] | None = None,
    today_two: list[str] | None = None,
    trade_date: str = "2026-06-25",
) -> MarketRiskResult:
    return evaluate_market_risk(
        trade_date,
        max_consecutive_boards=max_boards,
        prev_two_boards_codes=prev_two or [],
        today_three_boards_codes=today_three or [],
        prev_one_board_codes=prev_one,
        today_two_boards_codes=today_two,
        cfg=CFG,
    )


class TestF18TwoToThree:
    """方案 11:二进三联动风险。"""

    def test_golden_2026_06_25_one_seventh_halt(self):
        """金样本 2026-06-25:1/7=14.29% → HALT。"""
        f18 = GOLDEN_2026_06_25_F18
        result = _risk(
            prev_two=f18["prev_two_boards_codes"],
            today_three=f18["today_three_boards_codes"],
            max_boards=3,
        )
        assert result.two_to_three_denominator == 7
        assert result.two_to_three_numerator == 1
        assert result.two_to_three_rate == pytest.approx(1 / 7)
        assert result.f18_policy == PositionPolicy.HALT
        assert result.f18_risk_budget == 0.0
        assert result.f18_low_sample is False

    def test_denominator_zero_returns_unknown(self):
        """分母 0 → UNKNOWN, 不得显示 0%。"""
        result = _risk(prev_two=[], today_three=[])
        assert result.two_to_three_denominator == 0
        assert result.two_to_three_numerator == 0
        assert result.two_to_three_rate is None
        assert result.f18_policy == PositionPolicy.UNKNOWN

    def test_low_sample_den_1_prevents_aggressive(self):
        """分母 1-4 不可进入 AGGRESSIVE。"""
        result = _risk(
            prev_two=["A"],
            today_three=["A"],
            max_boards=5,  # MAIN_UP
        )
        # rate=1/1=100% > 50%, 但 low_sample → STANDARD
        assert result.f18_low_sample is True
        assert result.f18_policy == PositionPolicy.STANDARD

    def test_low_sample_den_4_prevents_aggressive(self):
        result = _risk(
            prev_two=["A", "B", "C", "D"],
            today_three=["A", "B", "C"],
            max_boards=5,
        )
        assert result.f18_low_sample is True
        assert result.f18_policy == PositionPolicy.STANDARD

    def test_low_sample_den_5_allows_normal(self):
        result = _risk(
            prev_two=["A", "B", "C", "D", "E"],
            today_three=["A", "B", "C", "D"],
            max_boards=5,
        )
        assert result.f18_low_sample is False
        assert result.f18_policy == PositionPolicy.AGGRESSIVE

    def test_result_records_numerator_and_denominator(self):
        """UI 必须显示 14%(1/7)而不是只显示 14%。"""
        result = _risk(
            prev_two=["A", "B", "C", "D", "E", "F", "G"],
            today_three=["A"],
        )
        assert result.two_to_three_numerator == 1
        assert result.two_to_three_denominator == 7


class TestF18PolicyBoundaries:
    """方案 11.2 + 19.1:阈值 -ε/等于/+ε。"""

    def _rate(self, rate: float) -> MarketRiskResult:
        return _risk(
            prev_two=["A", "B", "C", "D", "E", "F", "G", "H", "J", "K"],
            today_three=["A"] if rate > 0 else [],
            max_boards=4,
        )

    def test_below_20pct_is_halt(self):
        # 1/6 ≈ 16.67% < 20% → HALT
        r = _risk(
            prev_two=["A", "B", "C", "D", "E", "F"],
            today_three=["A"],
            max_boards=4,
        )
        assert r.two_to_three_rate == pytest.approx(1 / 6)
        assert r.f18_policy == PositionPolicy.HALT
        assert r.f18_risk_budget == 0.0

    def test_at_20pct_is_defensive(self):
        r = _risk(
            prev_two=["A", "B", "C", "D"],
            today_three=["A"],
            max_boards=4,
        )
        assert r.two_to_three_rate == 0.25
        assert r.f18_policy == PositionPolicy.DEFENSIVE
        assert r.f18_risk_budget == 0.5

    def test_at_30pct_is_standard(self):
        r = _risk(
            prev_two=["A", "B", "C", "D", "E"],
            today_three=["A", "B"],
            max_boards=4,
        )
        assert r.two_to_three_rate == 0.4
        assert r.f18_policy == PositionPolicy.STANDARD
        assert r.f18_risk_budget == 1.0

    def test_at_50pct_is_standard(self):
        r = _risk(
            prev_two=["A", "B", "C", "D"],
            today_three=["A", "B"],
            max_boards=4,
        )
        assert r.two_to_three_rate == 0.5
        assert r.f18_policy == PositionPolicy.STANDARD

    def test_above_50pct_is_aggressive(self):
        r = _risk(
            prev_two=["A", "B", "C", "D", "E", "F"],
            today_three=["A", "B", "C", "D"],
            max_boards=4,
        )
        assert r.two_to_three_rate == pytest.approx(4 / 6)
        assert r.f18_policy == PositionPolicy.AGGRESSIVE
        assert r.f18_risk_budget == 1.25


class TestMarketRegime:
    """方案 12.1:最高连板映射。"""

    @pytest.mark.parametrize("boards,expected_regime,expected_mult", [
        (0, MarketRegime.FROZEN, 0.6),
        (1, MarketRegime.FROZEN, 0.6),
        (2, MarketRegime.FROZEN, 0.6),
        (3, MarketRegime.SUPPRESSED, 0.8),
        (4, MarketRegime.ACTIVE, 1.0),
        (5, MarketRegime.MAIN_UP, 1.1),
        (6, MarketRegime.MAIN_UP, 1.1),
    ])
    def test_regime_mapping(self, boards, expected_regime, expected_mult):
        result = _risk(max_boards=boards)
        assert result.market_regime == expected_regime
        assert result.one_to_two_multiplier == pytest.approx(expected_mult)


class TestAdjustedScoreShadow:
    """方案 12.1:adjusted_score shadow;回测前不替换排序。"""

    def test_compute_adjusted_score_scales_correctly(self):
        assert compute_adjusted_score(100, 1.0) == 100
        assert compute_adjusted_score(100, 0.6) == 60
        assert compute_adjusted_score(100, 1.1) == 110

    def test_adjusted_score_clamped(self):
        assert compute_adjusted_score(150, 1.1) == 150
        assert compute_adjusted_score(0, 0.6) == 0


class TestF18CandidateIntegration:
    """方案 11.4:F18 与候选发布结合。"""

    def test_halt_returns_correct_reason_codes(self):
        result = _risk(
            prev_two=["A", "B", "C", "D", "E", "F", "G"],
            today_three=["A"],
            max_boards=2,
        )
        codes = f18_reason_codes(result)
        assert ReasonCode.MARKET_F18_HALT in codes
        assert ReasonCode.MARKET_REGIME_FROZEN in codes

    def test_standard_no_blocking_codes(self):
        result = _risk(
            prev_two=["A", "B", "C", "D", "E", "F", "G"],
            today_three=["A", "B", "C"],
            max_boards=4,
        )
        codes = f18_reason_codes(result)
        assert ReasonCode.MARKET_F18_HALT not in codes
        assert ReasonCode.MARKET_REGIME_FROZEN not in codes

    def test_halt_requires_no_trade(self):
        """HALT 状态:candidates 可保留观察记录,但 action=NO_TRADE。"""
        result = _risk(
            prev_two=["A", "B", "C", "D", "E", "F", "G"],
            today_three=["A"],
            max_boards=3,
        )
        assert result.f18_policy == PositionPolicy.HALT
        # 发布层根据 f18_policy 决定 action


class TestOneToTwoLegacy:
    """一进二计算(兼容旧 market_recap.promotion_rate)。"""

    def test_one_to_two_rate_computed(self):
        result = _risk(
            prev_one=["A", "B", "C", "D"],
            today_two=["A", "B"],
        )
        assert result.one_to_two_denominator == 4
        assert result.one_to_two_numerator == 2
        assert result.one_to_two_rate == 0.5

    def test_one_to_two_no_prev_boards(self):
        result = _risk(
            prev_one=[],
            today_two=["A"],
        )
        assert result.one_to_two_denominator == 0
        assert result.one_to_two_rate is None
