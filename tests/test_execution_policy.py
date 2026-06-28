"""Phase 6 验收 — 结构化执行计划。

覆盖方案第 14 节:
- 14.2 候选买入规则(条件单);
- 14.3 持仓防守与止盈(硬止损、分档止盈);
- 14.4 次日七档竞价矩阵;
- 所有区间边界参数化测试;
- 缺 open/previous_close/cost 时不生成假价格。
"""
from __future__ import annotations

import pytest

from execution_policy import (
    auction_matrix,
    buy_plan,
    defensive_sell_plan,
    round_to_tick,
)
from rule_contract import ExecutionAction, MarketRegime, PositionPolicy

RV = "dragon-formula/1.0.0-draft"
TD = "2026-06-25"
CODE = "002518"


class TestBuyPlan:
    def test_normal_buy_with_open_price(self):
        plan = buy_plan(
            TD, CODE, open_price=10.0, previous_close=9.5, rule_version=RV,
        )
        assert plan.action == ExecutionAction.CONDITIONAL_BUY
        assert plan.trigger_price == round_to_tick(10.0 + 0.10)
        assert plan.precondition == f"last_price >= {round_to_tick(10.0 + 0.10)}"

    def test_missing_price_returns_no_trade(self):
        plan = buy_plan(
            TD, CODE, open_price=None, previous_close=None, rule_version=RV,
        )
        assert plan.action == ExecutionAction.NO_TRADE
        assert plan.precondition == "missing_price"

    def test_halt_f18_returns_no_trade(self):
        plan = buy_plan(
            TD, CODE, open_price=10.0, previous_close=9.5,
            rule_version=RV, f18_policy=PositionPolicy.HALT,
        )
        assert plan.action == ExecutionAction.NO_TRADE
        assert plan.precondition == "f18_halt"

    def test_frozen_regime_returns_watch(self):
        plan = buy_plan(
            TD, CODE, open_price=10.0, previous_close=9.5,
            rule_version=RV, market_regime=MarketRegime.FROZEN,
        )
        assert plan.action == ExecutionAction.WATCH


class TestDefensiveSell:
    def test_high_open_triggers_defensive_sell(self):
        plans = defensive_sell_plan(
            TD, CODE, open_price=10.5, previous_close=9.5,
            buy_cost=9.8, rule_version=RV,
        )
        # 至少有硬止损 + 分档止盈(2或3条,含高开防守)
        assert len(plans) >= 3
        # 检查高开防守
        defensive = [p for p in plans if p.trigger_type == "defensive_sell"]
        assert len(defensive) >= 1

    def test_no_high_open_no_defensive(self):
        plans = defensive_sell_plan(
            TD, CODE, open_price=9.8, previous_close=9.5,
            buy_cost=9.5, rule_version=RV,
        )
        defensive = [p for p in plans if p.trigger_type == "defensive_sell"]
        assert len(defensive) == 0

    def test_missing_price_returns_empty(self):
        plans = defensive_sell_plan(
            TD, CODE, open_price=None, previous_close=None,
            buy_cost=None, rule_version=RV,
        )
        assert plans == []

    def test_hard_stop_present(self):
        plans = defensive_sell_plan(
            TD, CODE, open_price=10.0, previous_close=9.5,
            buy_cost=9.8, rule_version=RV,
        )
        stops = [p for p in plans if p.trigger_type == "stop_loss"]
        assert len(stops) == 1
        assert stops[0].action == ExecutionAction.EXIT

    def test_partial_profit_triggers_present(self):
        plans = defensive_sell_plan(
            TD, CODE, open_price=10.0, previous_close=9.5,
            buy_cost=9.8, rule_version=RV,
        )
        profits = [p for p in plans if p.trigger_type.startswith("partial_profit")]
        assert len(profits) == 2


class TestAuctionMatrix:
    """次日七档竞价矩阵全部边界参数化测试。"""

    @pytest.mark.parametrize("open_px,prev_close,expected_action,expected_precondition", [
        (10.8,  10.0, ExecutionAction.REDUCE, "reduce_half_and_hold_rest"),
        (10.5,  10.0, ExecutionAction.REDUCE, "open_price - 0.10"),
        (10.3,  10.0, ExecutionAction.WATCH, "watch_until_0935"),
        (10.1,  10.0, ExecutionAction.HOLD, "hold_unless_break_open"),
        (10.0,  10.0, ExecutionAction.WATCH, "require_red_within_30s"),
        (9.8,   10.0, ExecutionAction.EXIT, "exit_at_auction"),
        (9.2,   10.0, ExecutionAction.EXIT, "exit_at_auction"),
    ])
    def test_boundaries(self, open_px, prev_close, expected_action, expected_precondition):
        plan = auction_matrix(TD, CODE, open_price=open_px, previous_close=prev_close, rule_version=RV)
        assert plan.action == expected_action, f"open_px={open_px} expected {expected_action} got {plan.action}"
        assert expected_precondition in (plan.precondition or "")

    def test_exact_8pct_boundary(self):
        plan = auction_matrix(TD, CODE, open_price=10.8, previous_close=10.0, rule_version=RV)
        assert plan.action == ExecutionAction.REDUCE

    def test_exact_5pct_boundary(self):
        plan = auction_matrix(TD, CODE, open_price=10.5, previous_close=10.0, rule_version=RV)
        assert plan.action == ExecutionAction.REDUCE

    def test_exact_3pct_boundary(self):
        plan = auction_matrix(TD, CODE, open_price=10.3, previous_close=10.0, rule_version=RV)
        assert plan.action == ExecutionAction.WATCH

    def test_exact_1pct_boundary(self):
        plan = auction_matrix(TD, CODE, open_price=10.1, previous_close=10.0, rule_version=RV)
        assert plan.action == ExecutionAction.HOLD

    def test_exact_0pct_boundary(self):
        plan = auction_matrix(TD, CODE, open_price=10.0, previous_close=10.0, rule_version=RV)
        assert plan.action == ExecutionAction.WATCH

    def test_missing_price_returns_no_trade(self):
        plan = auction_matrix(TD, CODE, open_price=None, previous_close=None, rule_version=RV)
        assert plan.action == ExecutionAction.NO_TRADE
        assert plan.precondition == "missing_price"


class TestRoundToTick:
    def test_rounds_to_0_01(self):
        assert round_to_tick(10.123) == pytest.approx(10.12)
        assert round_to_tick(10.129) == pytest.approx(10.13)
        assert round_to_tick(10.0) == pytest.approx(10.0)
