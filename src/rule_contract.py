"""寻龙诀规则契约 — 版本化的枚举、原因码与配置加载。

盘后 (src/recap_engine.py) 与盘中 (src/data_pipeline/) 共同消费本模块。
任何规则语义变更必须升级 `rule_version`,禁止用同一版本号改变历史含义。
冲突裁决见 docs/adr/0003-rule-contract-and-conflict-adjudication.md。

本模块只定义稳定的枚举与原因码,不做业务计算;纯函数实现位于各自领域模块
(feature_engineering/market_risk/candidate_policy/...)。这样盘后与盘中不会
各自复制 F17/F18/F19 逻辑。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

try:  # Python 3.11+ stdlib;pyproject 要求 >=3.11
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - 仅为防御,生产用 3.11
    import tomli as tomllib  # type: ignore[no-redef]

class FactorId(StrEnum):
    """因子枚举(因子库.md 2026-07-01)。对应 F 系列进化规则。"""
    ICE_AGE_COEFFICIENT = "F01"
    ICE_AGE_20CM_PENALTY = "F02"
    FIRST_BOARD_BOOST = "F03"
    SECOND_BOARD_PENALTY = "F04"
    FBAO_PENALTY = "F05"
    C_GRADE_COEFFICIENT = "F06"
    FIRST_SEAL_AUCTION_BONUS = "F07"
    SEAL_FUND_WEAK_PENALTY = "F08"
    SEAL_FUND_WEAK_THRESHOLD = "F09"
    VOLUME_FIRST_BOARD_BOOST = "F13"
    VOLUME_FIRST_BOARD_SHRINK = "F14"
    VOLUME_CONTINUATION_SHRINK = "F15"
    VOLUME_CONTINUATION_EXPLODE = "F16"
    LOW_POSITION_VOLUME_BONUS = "F17"


class ConditionOrderId(StrEnum):
    """条件单因子(C 系列)。"""
    OPEN_BUY_OFFSET = "C01"
    GAP_SELL_OFFSET = "C02"
    TAKE_PROFIT_4PCT = "C03_4"
    TAKE_PROFIT_7PCT = "C03_7"
    COMPLETENESS_CHECK = "C04"


RULE_VERSION = "dragon-formula/1.0.0-draft"
CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "rules" / "dragon_formula_v1.toml"
LHB_SEATS_PATH = Path(__file__).resolve().parents[1] / "config" / "lhb_seats_v1.toml"


class DataStatus(StrEnum):
    """数据来源状态。缺失或过期数据不得用 0 伪装成 OK。"""

    OK = "OK"
    DEGRADED = "DEGRADED"  # 部分降级(如龙虎榜缺失),仍可继续但记录
    STALE = "STALE"  # 过期;已有候选可展示但不再产生新积极推送
    INVALID = "INVALID"  # 结构不合法
    UNAVAILABLE = "UNAVAILABLE"  # 请求失败


class PublicationStatus(StrEnum):
    PUBLISHED = "PUBLISHED"
    # 方案 9.3:前 5 写入 candidates 并标记 PUBLISHED_TOP5;
    # 其余通过硬门槛但排在 Top5 外的标记 RANKED_OUTSIDE_TOP5;
    # 被过滤或仅观察的标记 OBSERVATION_ONLY;发布闸门阻断的标记 BLOCKED。
    PUBLISHED_TOP5 = "PUBLISHED_TOP5"
    RANKED_OUTSIDE_TOP5 = "RANKED_OUTSIDE_TOP5"
    OBSERVATION_ONLY = "OBSERVATION_ONLY"
    BLOCKED = "BLOCKED"


class CandidateEligibility(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"
    UNKNOWN = "UNKNOWN"


class PersonalityGrade(StrEnum):
    S = "S"
    A = "A"
    B_PLUS = "B_PLUS"
    B_MINUS = "B_MINUS"  # 按 C 处理,过滤
    C = "C"
    D = "D"
    UNKNOWN = "UNKNOWN"


class MarketRegime(StrEnum):
    FROZEN = "FROZEN"
    SUPPRESSED = "SUPPRESSED"
    ACTIVE = "ACTIVE"
    MAIN_UP = "MAIN_UP"
    UNKNOWN = "UNKNOWN"


class PositionPolicy(StrEnum):
    HALT = "HALT"
    DEFENSIVE = "DEFENSIVE"
    STANDARD = "STANDARD"
    AGGRESSIVE = "AGGRESSIVE"
    UNKNOWN = "UNKNOWN"


class ExecutionAction(StrEnum):
    NO_TRADE = "NO_TRADE"
    WATCH = "WATCH"
    CONDITIONAL_BUY = "CONDITIONAL_BUY"
    HOLD = "HOLD"
    REDUCE = "REDUCE"
    EXIT = "EXIT"


class ReasonCode(StrEnum):
    """稳定的机器可读原因码。只能追加或版本化,不能改同一代码语义。"""

    # F19 候选宇宙/硬门槛
    NOT_FIRST_BOARD = "NOT_FIRST_BOARD"
    ST_OR_DELISTING_RISK = "ST_OR_DELISTING_RISK"
    SEAL_FUNDS_BELOW_50M = "SEAL_FUNDS_BELOW_50M"
    BLOWN_COUNT_ABOVE_5 = "BLOWN_COUNT_ABOVE_5"
    NO_F19_RESONANCE = "NO_F19_RESONANCE"

    # F17 股性禁买
    PERSONALITY_B_MINUS_BLOCKED = "PERSONALITY_B_MINUS_BLOCKED"
    PERSONALITY_C_BLOCKED = "PERSONALITY_C_BLOCKED"
    PERSONALITY_D_BLOCKED = "PERSONALITY_D_BLOCKED"
    PERSONALITY_DATA_MISSING = "PERSONALITY_DATA_MISSING"

    # 共振信号(positive)
    EARLY_SEAL_RESONANCE = "EARLY_SEAL_RESONANCE"
    LHB_RESONANCE = "LHB_RESONANCE"
    RECENT_3D_2B_RESONANCE = "RECENT_3D_2B_RESONANCE"
    RECENT_4D_2B_BOOST = "RECENT_4D_2B_BOOST"

    # 市场级风控
    MARKET_F18_HALT = "MARKET_F18_HALT"
    MARKET_REGIME_FROZEN = "MARKET_REGIME_FROZEN"

    # 数据质量与发布闸门
    TRADING_DAY_INVALID = "TRADING_DAY_INVALID"
    SOURCE_STALE = "SOURCE_STALE"
    SOURCE_SCHEMA_INVALID = "SOURCE_SCHEMA_INVALID"
    CRITICAL_SOURCE_UNAVAILABLE = "CRITICAL_SOURCE_UNAVAILABLE"
    CALENDAR_CONFLICT = "CALENDAR_CONFLICT"

    # 弱封单惩罚(可选)
    WEAK_SEAL_50_TO_100M = "WEAK_SEAL_50_TO_100M"

    # 量比维度(E05)
    VOLUME_RATIO_MISSING = "VOLUME_RATIO_MISSING"
    VOLUME_RATIO_NUKE = "VOLUME_RATIO_NUKE"

    # 发布结果
    PUBLISHED_TOP5 = "PUBLISHED_TOP5"
    RANKED_OUTSIDE_TOP5 = "RANKED_OUTSIDE_TOP5"


class ConfigError(ValueError):
    """规则配置无效。错误配置应阻止服务启动,不得使用默认值继续运行。"""


@dataclass(frozen=True)
class RuleConfig:
    """加载并校验后的规则配置。"""

    raw: dict[str, Any]

    @property
    def rule_version(self) -> str:
        return str(self.raw["rule_version"])

    @property
    def max_published_candidates(self) -> int:
        return int(self.raw["max_published_candidates"])


def _check(cond: bool, msg: str) -> None:
    if not cond:
        raise ConfigError(msg)


def _validate(config: dict[str, Any]) -> None:
    # 顶层
    _check(bool(config.get("rule_version")), "rule_version must not be empty")
    _check(
        config["rule_version"] == RULE_VERSION, f"rule_version mismatch: {config['rule_version']}"
    )
    _check(bool(config.get("timezone")), "timezone must not be empty")
    top_n = int(config["max_published_candidates"])
    _check(1 <= top_n <= 20, f"max_published_candidates must be 1-20, got {top_n}")

    feature_flags = config.get("feature_flags", {})
    for key in (
        "enforce_f19",
        "enforce_f17",
        "enforce_f18",
        "use_adjusted_score",
        "publish_execution_plan",
        "personality_enforce",
        "enforce_volume_ratio",
        "enforce_multiplicative_factors",
    ):
        _check(isinstance(feature_flags.get(key), bool), f"feature_flags.{key} must be bool")

    ranking_mode = feature_flags.get("ranking_mode", "additive")
    _check(ranking_mode in ("additive", "weighted"), "feature_flags.ranking_mode must be additive or weighted")

    if ranking_mode == "weighted":
        rw = config.get("ranking_weights", {})
        _check(rw, "ranking_weights must exist when ranking_mode=weighted")
        total = sum(float(rw[k]) for k in ("bid_stability", "personality_grade", "sector_heat", "seal_funds"))
        _check(abs(total - 1.0) < 0.001, f"ranking_weights must sum to 1.0, got {total}")

    f19 = config["f19"]
    _check(float(f19["min_seal_funds_yuan"]) >= 0, "f19.min_seal_funds_yuan must be >= 0")
    _check(int(f19["max_blown_count"]) >= 0, "f19.max_blown_count must be >= 0")
    _check(int(f19["recent_resonance_sessions"]) >= 1, "f19.recent_resonance_sessions must be >= 1")
    _check(
        int(f19["recent_resonance_min_limit_ups"]) >= 1,
        "f19.recent_resonance_min_limit_ups must be >= 1",
    )
    _check(int(f19["required_resonance_count"]) >= 1, "f19.required_resonance_count must be >= 1")

    f14 = config["f14"]
    _check(int(f14["lookback_sessions"]) >= 1, "f14.lookback_sessions must be >= 1")
    _check(int(f14["min_limit_ups"]) >= 1, "f14.min_limit_ups must be >= 1")
    _check(float(f14["score_multiplier"]) > 0, "f14.score_multiplier must be > 0")

    f18 = config["f18"]
    halt = float(f18["halt_below"])
    defensive = float(f18["defensive_below"])
    standard = float(f18["standard_at_or_below"])
    _check(
        0.0 <= halt <= defensive <= standard <= 1.0,
        "f18 thresholds must be 0<=halt<defensive<=standard<=1",
    )
    for k in (
        "halt_risk_budget",
        "defensive_risk_budget",
        "standard_risk_budget",
        "aggressive_risk_budget",
    ):
        _check(float(f18[k]) >= 0, f"f18.{k} must be >= 0")
    _check(int(f18["low_sample_denominator"]) >= 1, "f18.low_sample_denominator must be >= 1")

    regime = config["market_regime"]
    for k, v in regime.items():
        if k.endswith("max_boards") or k.endswith("min_boards"):
            _check(int(v) >= 0, f"market_regime.{k} must be >= 0")
        if k.startswith("one_to_two_multiplier"):
            _check(float(v) >= 0, f"market_regime.{k} must be >= 0")
    _check(
        int(regime["frozen_max_boards"])
        <= int(regime["suppressed_max_boards"])
        <= int(regime["active_max_boards"])
        <= int(regime["main_up_min_boards"]),
        "market_regime max_boards must be monotonic non-decreasing",
    )

    lr = config["limit_rule"]
    for k, v in lr.items():
        _check(float(v) >= 0, f"limit_rule.{k} must be >= 0")

    sf = config["seal_funds"]
    _check(
        float(sf["weak_seal_floor_yuan"]) <= float(sf["weak_seal_ceiling_yuan"]),
        "seal_funds weak floor must be <= ceiling",
    )

    pers = config["personality"]
    weights = [
        float(pers["weight_activity"]),
        float(pers["weight_reliability"]),
        float(pers["weight_explosiveness"]),
        float(pers["weight_capital"]),
        float(pers["weight_early_board"]),
    ]
    _check(
        abs(sum(weights) - 1.0) < 1e-6, f"personality weights must sum to 1.0, got {sum(weights)}"
    )
    _check(
        float(pers["grade_s_min"])
        >= float(pers["grade_a_min"])
        >= float(pers["grade_b_plus_min"])
        >= float(pers["grade_b_minus_min"])
        >= float(pers["grade_c_min"])
        >= 0.0,
        "personality grade thresholds must be monotonic non-increasing",
    )

    vr = config["volume_ratio"]
    _check(float(vr["nuke_threshold"]) > 0, "volume_ratio.nuke_threshold must be > 0")
    _check(
        float(vr["significant_threshold"]) <= float(vr["nuke_threshold"]),
        "volume_ratio significant_threshold must be <= nuke_threshold",
    )
    _check(
        float(vr["shrink_threshold"]) < float(vr["significant_threshold"]),
        "volume_ratio shrink_threshold must be < significant_threshold",
    )
    _check(int(vr["position_lookback"]) >= 1, "volume_ratio.position_lookback must be >= 1")
    _check(int(vr["volume_ma_window"]) >= 1, "volume_ratio.volume_ma_window must be >= 1")


def _resolve_config_path(explicit: Path | str | None, *candidates: Path) -> Path:
    if explicit is not None:
        return Path(explicit)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def load_rule_config(path: Path | str | None = None) -> RuleConfig:
    """加载并校验规则 TOML。配置无效时抛 ConfigError，阻止服务启动。"""
    cfg_path = _resolve_config_path(path, Path.cwd() / "config" / "rules" / "dragon_formula_v1.toml", CONFIG_PATH)
    with cfg_path.open("rb") as f:
        config = tomllib.load(f)
    _validate(config)
    return RuleConfig(raw=config)


def load_lhb_seats_config(path: Path | str | None = None) -> dict[str, Any]:
    """加载龙虎榜席位配置(校验 schema_version 与 seat_id 唯一)。"""
    cfg_path = _resolve_config_path(path, Path.cwd() / "config" / "lhb_seats_v1.toml", LHB_SEATS_PATH)
    with cfg_path.open("rb") as f:
        config: dict[str, Any] = tomllib.load(f)
    _check(bool(config.get("seat_schema_version")), "lhb seat_schema_version must not be empty")
    seats = config.get("seats", [])
    seat_ids = [s["seat_id"] for s in seats]
    _check(len(seat_ids) == len(set(seat_ids)), "lhb seat_id must be unique")
    valid_categories = {"GOLD", "DEATH", "INSTITUTION"}
    for s in seats:
        _check(
            s["category"] in valid_categories,
            f"lhb seat {s['seat_id']} category invalid: {s['category']}",
        )
    return config
