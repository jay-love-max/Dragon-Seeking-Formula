"""Phase 3 F18 二进三联动风险 + 市场环境 — 纯函数实现。

方案第 11 节:
- 11.1 二进三率计算:denominator = T-1 二板数, numerator = T 晋级三板数;
- 11.2 策略映射:<20% HALT, 20-30% DEFENSIVE, 30-50% STANDARD, >50% AGGRESSIVE;
- 11.3 小样本保护:denominator=0 → UNKNOWN, 1-4 → LOW_SAMPLE, >=5 正常;
- 11.4 与候选发布结合:HALT 时所有记录 can_trade=false。

方案第 12 节:
- 12.1 最高连板状态:<=2 FROZEN, 3 SUPPRESSED, 4 ACTIVE, >=5 MAIN_UP;
- adjusted_score shadow:回测前不替换 base_score 排序。

本模块是纯函数,不做 I/O;盘后与盘中共用同一逻辑。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from rule_contract import MarketRegime, PositionPolicy, ReasonCode, RuleConfig

_STRATEGY_PREFIXES = {
    MarketRegime.FROZEN: "frozen",
    MarketRegime.SUPPRESSED: "suppressed",
    MarketRegime.ACTIVE: "active",
    MarketRegime.MAIN_UP: "main_up",
}
_STRATEGY_KEYS = ["first_board", "one_to_two", "relay", "reversal", "half_road"]


@dataclass(frozen=True)
class MarketRiskResult:
    """市场级风险与市场状态。"""

    trade_date: str
    max_consecutive_boards: int
    market_regime: MarketRegime
    one_to_two_numerator: int
    one_to_two_denominator: int
    one_to_two_rate: float | None
    two_to_three_numerator: int
    two_to_three_denominator: int
    two_to_three_rate: float | None
    f18_policy: PositionPolicy
    f18_risk_budget: float
    f18_low_sample: bool
    one_to_two_multiplier: float
    rule_version: str
    strategy_coefficients: dict[str, float] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


def _market_regime(max_boards: int, cfg: RuleConfig) -> MarketRegime:
    mr = cfg.raw["market_regime"]
    frozen_max = int(mr["frozen_max_boards"])
    suppressed_max = int(mr["suppressed_max_boards"])
    active_max = int(mr["active_max_boards"])
    main_up_min = int(mr["main_up_min_boards"])

    if max_boards >= main_up_min:
        return MarketRegime.MAIN_UP
    if max_boards == active_max:
        return MarketRegime.ACTIVE
    if max_boards == suppressed_max:
        return MarketRegime.SUPPRESSED
    if max_boards <= frozen_max:
        return MarketRegime.FROZEN
    return MarketRegime.UNKNOWN


def _one_to_two_multiplier(regime: MarketRegime, cfg: RuleConfig) -> float:
    mr = cfg.raw["market_regime"]
    mapping = {
        MarketRegime.FROZEN: float(mr["one_to_two_multiplier_frozen"]),
        MarketRegime.SUPPRESSED: float(mr["one_to_two_multiplier_suppressed"]),
        MarketRegime.ACTIVE: float(mr["one_to_two_multiplier_active"]),
        MarketRegime.MAIN_UP: float(mr["one_to_two_multiplier_main_up"]),
    }
    return mapping.get(regime, 1.0)


def strategy_coefficients(regime: MarketRegime, cfg: RuleConfig) -> dict[str, float]:
    """返回当前市场环境下的各策略系数(2026-07-01 知识库)。

    返回 {first_board, one_to_two, relay, reversal, half_road}。
    """
    prefix = _STRATEGY_PREFIXES.get(regime)
    if prefix is None:
        return {k: 1.0 for k in _STRATEGY_KEYS}
    sc = cfg.raw.get("strategy_coefficients", {})
    result = {}
    for key in _STRATEGY_KEYS:
        toml_key = f"{prefix}_{key}"
        result[key] = float(sc.get(toml_key, 1.0))
    return result


def _f18_policy(
    rate: float | None,
    denominator: int,
    cfg: RuleConfig,
) -> tuple[PositionPolicy, float, bool]:
    f18 = cfg.raw["f18"]
    low_sample_den = int(f18["low_sample_denominator"])
    low_sample = 0 < denominator < low_sample_den

    if denominator == 0 or rate is None:
        return PositionPolicy.UNKNOWN, 0.0, False

    halt = float(f18["halt_below"])
    defensive = float(f18["defensive_below"])
    standard = float(f18["standard_at_or_below"])

    if rate < halt:
        budget = float(f18["halt_risk_budget"])
        return PositionPolicy.HALT, budget, low_sample
    if rate < defensive:
        budget = float(f18["defensive_risk_budget"])
        return PositionPolicy.DEFENSIVE, budget, low_sample
    if rate <= standard:
        budget = float(f18["standard_risk_budget"])
        return PositionPolicy.STANDARD, budget, low_sample
    if low_sample:
        return PositionPolicy.STANDARD, float(f18["standard_risk_budget"]), low_sample
    return PositionPolicy.AGGRESSIVE, float(f18["aggressive_risk_budget"]), low_sample


def evaluate_market_risk(
    trade_date: str,
    *,
    max_consecutive_boards: int,
    prev_two_boards_codes: list[str],
    today_three_boards_codes: list[str],
    prev_one_board_codes: list[str] | None = None,
    today_two_boards_codes: list[str] | None = None,
    prev_trade_date: str | None = None,
    cfg: RuleConfig,
) -> MarketRiskResult:
    regime = _market_regime(max_consecutive_boards, cfg)
    multiplier = _one_to_two_multiplier(regime, cfg)

    # 二进三
    denominator = len(prev_two_boards_codes)
    numerator = len(set(prev_two_boards_codes) & set(today_three_boards_codes))
    two_to_three_rate = numerator / denominator if denominator > 0 else None

    f18_pol, f18_budget, low_sample = _f18_policy(two_to_three_rate, denominator, cfg)

    # 一进二(仅记录)
    o2d = len(prev_one_board_codes or [])
    o2n = len(set(prev_one_board_codes or []) & set(today_two_boards_codes or []))
    one_to_two_rate_val = o2n / o2d if o2d > 0 else None

    coeffs = strategy_coefficients(regime, cfg)
    return MarketRiskResult(
        trade_date=trade_date,
        max_consecutive_boards=max_consecutive_boards,
        market_regime=regime,
        one_to_two_numerator=o2n,
        one_to_two_denominator=o2d,
        one_to_two_rate=one_to_two_rate_val,
        two_to_three_numerator=numerator,
        two_to_three_denominator=denominator,
        two_to_three_rate=two_to_three_rate,
        f18_policy=f18_pol,
        f18_risk_budget=f18_budget,
        f18_low_sample=low_sample,
        one_to_two_multiplier=multiplier,
        strategy_coefficients=coeffs,
        rule_version=cfg.rule_version,
        metadata={
            "prev_trade_date": prev_trade_date,
        },
    )


def compute_adjusted_score(base_score: int, multiplier: float) -> int:
    return max(0, min(150, round(base_score * multiplier)))


def f18_reason_codes(result: MarketRiskResult) -> list[str]:
    codes: list[str] = []
    if result.f18_policy == PositionPolicy.HALT:
        codes.append(ReasonCode.MARKET_F18_HALT)
    if result.market_regime == MarketRegime.FROZEN:
        codes.append(ReasonCode.MARKET_REGIME_FROZEN)
    return codes
