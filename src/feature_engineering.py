"""Phase 5 因子工程 — 限幅归一化、历史共振、封单资金评分。

方案 13.1:10/20/30/5cm 归一化;
方案 13.2:recent_3d_2b / recent_4d_2b;
方案 13.3:绝对封单资金(WeakSeal);
方案 13.4:龙虎榜质量(委托 score_lhb 给 lhb_quality)。

本模块是纯函数,不做 I/O;盘后与盘中共用同一逻辑。
"""
from __future__ import annotations

import re

from rule_contract import ReasonCode, RuleConfig

# --- 板块识别(方案 13.1) ---


def detect_limit_rule(code: str, name: str = "", sector: str = "") -> float:
    """识别股票涨停幅度。

    返回涨停幅度倍数(10/20/30/5)。
    板块识别规则必须有独立测试,不能散落在评分函数中。
    """
    code = code.strip()
    name = name.strip() if name else ""
    is_st = bool(re.match(r"^(\*?ST|S\*ST|退市)", name))

    if is_st:
        return 5.0
    if code.startswith(("300", "301")):
        return 20.0
    if code.startswith(("688", "689")):
        return 20.0
    if code.startswith(("4", "8")) and (not code.startswith(("600", "601", "603", "605", "000", "001", "002", "003"))):
        return 30.0
    return 10.0


def normalize_change_pct(actual_change_pct: float, limit_pct: float) -> float:
    """归一化涨幅。

    normalized_change = actual_change_pct / limit_pct * 10。
    未知限幅(limit_pct <= 0)返回 actual_change_pct 本身。
    """
    if limit_pct <= 0:
        return actual_change_pct
    return actual_change_pct / limit_pct * 10.0


# --- 历史共振(方案 13.2) ---


def check_recent_3d_2b(
    code: str,
    recent_limit_ups_by_code: dict[str, list[str]],
    min_boards: int = 2,
) -> bool:
    """最近 3 个交易日封板次数 >= min_boards。参与 F19 共振。"""
    boards = recent_limit_ups_by_code.get(code, [])
    return len(boards) >= min_boards


def check_recent_4d_2b(
    code: str,
    recent_limit_ups_by_code: dict[str, list[str]],
    min_boards: int = 2,
) -> bool:
    """最近 4 个交易日封板次数 >= min_boards。触发 F14 评分加成。"""
    boards = recent_limit_ups_by_code.get(code, [])
    return len(boards) >= min_boards


# --- 绝对封单资金(方案 13.3) ---


def seal_funds_weak_check(
    seal_funds_yuan: float,
    cfg: RuleConfig,
) -> tuple[str | None, str | None]:
    """检查封单资金是否属于弱封单区间。

    Returns (reason_code_or_None, warning_or_None)。
    50m-100m:记录 WEAK_SEAL_50_TO_100M,是否扣分由配置控制。
    """
    sf = cfg.raw["seal_funds"]
    floor = float(sf["weak_seal_floor_yuan"])
    ceiling = float(sf["weak_seal_ceiling_yuan"])

    if seal_funds_yuan < floor:
        return None, None
    if seal_funds_yuan < ceiling:
        if sf.get("weak_seal_penalty_enabled", False):
            return ReasonCode.WEAK_SEAL_50_TO_100M, None
        return ReasonCode.WEAK_SEAL_50_TO_100M, "weak_seal_penalty_disabled"
    return None, None


def seal_funds_penalty_points(
    seal_funds_yuan: float,
    cfg: RuleConfig,
) -> int:
    """返回封单不足的扣分(方案 25 未确认前默认不扣)。"""
    sf = cfg.raw["seal_funds"]
    if (
        sf.get("weak_seal_penalty_enabled", False)
        and float(sf["weak_seal_floor_yuan"]) <= seal_funds_yuan < float(sf["weak_seal_ceiling_yuan"])
    ):
        return int(sf["weak_seal_penalty_points"])
    return 0


# --- F14 评分加成 ---


def apply_f14_boost(
    base_score: int,
    has_recent_4d_2b: bool,
    cfg: RuleConfig,
) -> int:
    """如果 4 天 2 板共振成立,乘以 F14 score_multiplier。

    返回调整后的 base_score(0-150 范围内)。
    """
    if not has_recent_4d_2b:
        return base_score
    mult = float(cfg.raw["f14"]["score_multiplier"])
    return max(0, min(150, round(base_score * mult)))
