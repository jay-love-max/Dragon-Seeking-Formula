"""Phase 6 结构化执行计划 — 纯函数实现。

方案第 14 节:
- 14.1 Formula 只生成建议,不自动下单;
- 14.2 候选买入规则(条件单);
- 14.3 持仓防守与止盈(硬止损、分档止盈);
- 14.4 次日七档竞价矩阵。

所有价格按 A 股最小价位 0.01 元舍入(round_to_tick)。
缺少必要价格时返回 UNKNOWN,不能编造价位。
"""
from __future__ import annotations

from dataclasses import dataclass

from rule_contract import ExecutionAction, MarketRegime, PositionPolicy


@dataclass(frozen=True)
class ExecutionPlan:
    """结构化买入/卖出/防守建议。"""

    trade_date: str
    code: str
    action: ExecutionAction
    trigger_type: str | None
    trigger_price: float | None
    reference_price: float | None
    quantity_pct: float | None
    valid_from: str | None
    valid_until: str | None
    precondition: str | None
    rule_version: str
    reason_codes: list[str] | None = None


def round_to_tick(price: float, tick: float = 0.01) -> float:
    """A 股最小价位 0.01 元舍入。"""
    return round(price / tick) * tick


# --- 14.2 候选买入规则 ---


def buy_plan(
    trade_date: str,
    code: str,
    *,
    open_price: float | None,
    previous_close: float | None,
    rule_version: str,
    market_regime: MarketRegime | None = None,
    f18_policy: PositionPolicy | None = None,
) -> ExecutionPlan:
    """生成条件买入计划。

    若 F18 HALT、市场 FROZEN、缺少 open_price,action=NO_TRADE。
    """
    if open_price is None or previous_close is None:
        return ExecutionPlan(
            trade_date=trade_date, code=code,
            action=ExecutionAction.NO_TRADE,
            trigger_type=None, trigger_price=None,
            reference_price=open_price,
            quantity_pct=None,
            valid_from=trade_date,
            valid_until=None,
            precondition="missing_price",
            rule_version=rule_version,
        )

    if f18_policy == PositionPolicy.HALT:
        return ExecutionPlan(
            trade_date=trade_date, code=code,
            action=ExecutionAction.NO_TRADE,
            trigger_type=None, trigger_price=None,
            reference_price=open_price,
            quantity_pct=None,
            valid_from=trade_date,
            valid_until=None,
            precondition="f18_halt",
            rule_version=rule_version,
            reason_codes=["MARKET_F18_HALT"],
        )

    if market_regime == MarketRegime.FROZEN:
        return ExecutionPlan(
            trade_date=trade_date, code=code,
            action=ExecutionAction.WATCH,
            trigger_type=None, trigger_price=None,
            reference_price=open_price,
            quantity_pct=None,
            valid_from=trade_date,
            valid_until=None,
            precondition="market_frozen",
            rule_version=rule_version,
        )

    buy_price = round_to_tick(open_price + 0.10)
    return ExecutionPlan(
        trade_date=trade_date, code=code,
        action=ExecutionAction.CONDITIONAL_BUY,
        trigger_type="price_above",
        trigger_price=buy_price,
        reference_price=open_price,
        quantity_pct=None,
        valid_from=trade_date,
        valid_until=None,
        precondition=f"last_price >= {buy_price}",
        rule_version=rule_version,
    )


# --- 14.3 持仓防守与止盈 ---


def defensive_sell_plan(
    trade_date: str,
    code: str,
    *,
    open_price: float | None,
    previous_close: float | None,
    buy_cost: float | None,
    rule_version: str,
) -> list[ExecutionPlan]:
    """生成防守与止盈计划列表。

    缺少价格时返回空列表(UNKNOWN),不编造价位。
    """
    plans: list[ExecutionPlan] = []
    if open_price is None or previous_close is None or buy_cost is None:
        return plans

    # 竞价高开 >5%
    auction_premium = (open_price / previous_close - 1) * 100
    if auction_premium > 5.0:
        sell_price = round_to_tick(open_price - 0.10)
        plans.append(ExecutionPlan(
            trade_date=trade_date, code=code,
            action=ExecutionAction.REDUCE,
            trigger_type="defensive_sell",
            trigger_price=sell_price,
            reference_price=open_price,
            quantity_pct=0.5,
            valid_from=trade_date,
            valid_until=None,
            precondition=f"open_price - 0.10 >= {sell_price}",
            rule_version=rule_version,
        ))

    stop_by_cost = round_to_tick(buy_cost * 0.96)
    stop_by_close = round_to_tick(previous_close - 0.01)
    stop_price = max(stop_by_cost, stop_by_close)
    plans.append(ExecutionPlan(
        trade_date=trade_date, code=code,
        action=ExecutionAction.EXIT,
        trigger_type="stop_loss",
        trigger_price=stop_price,
        reference_price=buy_cost,
        quantity_pct=1.0,
        valid_from=trade_date,
        valid_until=None,
        precondition=f"last_price <= {stop_price}",
        rule_version=rule_version,
    ))

    # 分档止盈
    gain_4pct = round_to_tick(open_price * 1.04)
    gain_7pct = round_to_tick(open_price * 1.07)

    plans.append(ExecutionPlan(
        trade_date=trade_date, code=code,
        action=ExecutionAction.REDUCE,
        trigger_type="partial_profit_4pct",
        trigger_price=gain_4pct,
        reference_price=open_price,
        quantity_pct=0.5,
        valid_from=trade_date,
        valid_until=None,
        precondition="gain_4pct_reached_then_drop_1pct",
        rule_version=rule_version,
    ))

    plans.append(ExecutionPlan(
        trade_date=trade_date, code=code,
        action=ExecutionAction.REDUCE,
        trigger_type="partial_profit_7pct",
        trigger_price=gain_7pct,
        reference_price=open_price,
        quantity_pct=0.5,
        valid_from=trade_date,
        valid_until=None,
        precondition="gain_7pct_reached_then_drop_1pct",
        rule_version=rule_version,
    ))

    return plans


# --- 14.4 次日七档竞价矩阵 ---


def auction_matrix(
    trade_date: str,
    code: str,
    *,
    open_price: float | None,
    previous_close: float | None,
    rule_version: str,
) -> ExecutionPlan:
    """根据竞价高开幅度生成次日操作建议。

    缺少价格时返回 UNKNOWN。
    """
    if open_price is None or previous_close is None:
        return ExecutionPlan(
            trade_date=trade_date, code=code,
            action=ExecutionAction.NO_TRADE,
            trigger_type=None, trigger_price=None,
            reference_price=None,
            quantity_pct=None,
            valid_from=trade_date,
            valid_until=None,
            precondition="missing_price",
            rule_version=rule_version,
        )

    premium = (open_price / previous_close - 1) * 100

    if premium >= 8.0:
        return ExecutionPlan(
            trade_date=trade_date, code=code,
            action=ExecutionAction.REDUCE,
            trigger_type="auction_ge_8pct",
            trigger_price=open_price,
            reference_price=open_price,
            quantity_pct=0.5,
            valid_from=trade_date,
            valid_until=f"{trade_date}T09:25:00",
            precondition="reduce_half_and_hold_rest",
            rule_version=rule_version,
        )
    if premium >= 5.0:
        sell_price = round_to_tick(open_price - 0.10)
        return ExecutionPlan(
            trade_date=trade_date, code=code,
            action=ExecutionAction.REDUCE,
            trigger_type="auction_5_to_8pct",
            trigger_price=sell_price,
            reference_price=open_price,
            quantity_pct=1.0,
            valid_from=trade_date,
            valid_until=f"{trade_date}T15:00:00",
            precondition=f"open_price - 0.10 >= {sell_price}",
            rule_version=rule_version,
        )
    if premium >= 3.0:
        return ExecutionPlan(
            trade_date=trade_date, code=code,
            action=ExecutionAction.WATCH,
            trigger_type="auction_3_to_5pct",
            trigger_price=open_price,
            reference_price=open_price,
            quantity_pct=None,
            valid_from=trade_date,
            valid_until=f"{trade_date}T09:35:00",
            precondition="watch_until_0935",
            rule_version=rule_version,
        )
    if premium >= 1.0:
        return ExecutionPlan(
            trade_date=trade_date, code=code,
            action=ExecutionAction.HOLD,
            trigger_type="auction_1_to_3pct",
            trigger_price=open_price,
            reference_price=open_price,
            quantity_pct=None,
            valid_from=trade_date,
            valid_until=None,
            precondition="hold_unless_break_open",
            rule_version=rule_version,
        )
    if premium >= 0.0:
        return ExecutionPlan(
            trade_date=trade_date, code=code,
            action=ExecutionAction.WATCH,
            trigger_type="auction_0_to_1pct",
            trigger_price=open_price,
            reference_price=open_price,
            quantity_pct=None,
            valid_from=trade_date,
            valid_until=f"{trade_date}T09:30:30",
            precondition="require_red_within_30s",
            rule_version=rule_version,
        )
    # < 0%
    return ExecutionPlan(
        trade_date=trade_date, code=code,
        action=ExecutionAction.EXIT,
        trigger_type="auction_negative",
        trigger_price=open_price,
        reference_price=open_price,
        quantity_pct=1.0,
        valid_from=trade_date,
        valid_until=f"{trade_date}T09:25:00",
        precondition="exit_at_auction",
        rule_version=rule_version,
    )
