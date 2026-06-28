"""Phase 4 龙虎榜质量评分与 F16 — 纯函数实现。

方案 13.4:
- 席位匹配:空白、括号、营业部后缀标准化,别名精确/包含匹配;
- 基础 50 分,加减金手指 GOLD、机构 INSTITUTION、死亡 DEATH 席位;
- F16:绍兴胜利东路在首板不扣分;二板及以上净买出现时扣 25。
"""
from __future__ import annotations

import re
from typing import Any

from rule_contract import load_lhb_seats_config

LHB_SEATS_CONFIG: dict[str, Any] | None = None


def _seats_config() -> dict[str, Any]:
    global LHB_SEATS_CONFIG
    if LHB_SEATS_CONFIG is None:
        LHB_SEATS_CONFIG = load_lhb_seats_config()
    return LHB_SEATS_CONFIG


# --- 席位标准化 ---


def _normalize_seat_name(name: str) -> str:
    """标准化营业部名称。

    去除:首尾空白、括号内文字(含全角括号)、"营业部"后缀。
    """
    name = name.strip()
    # 去除括号内文字(半角/全角)
    name = re.sub(r"[（(][^）)]*[）)]", "", name)
    name = name.replace("营业部", "").strip()
    return name


def _seat_matches(seat_name: str, aliases: list[str]) -> bool:
    """席位别名匹配:先精确匹配,再包含匹配。"""
    normalized = _normalize_seat_name(seat_name)
    for alias in aliases:
        alias_norm = _normalize_seat_name(alias)
        if normalized == alias_norm:
            return True
        if alias_norm and alias_norm in normalized:
            return True
    return False


# --- 单次买卖评分 ---


def score_single_trade(seats: list[dict[str, Any]]) -> float:
    """对单次龙虎榜交易的买入/卖出席位进行质量评分。

    基础 50 分,加金手指(+15/次)、机构净买(+10)、净买额加分,
    减死亡席位(-20/次);最终截断 0-100。
    """
    score = 50.0
    config = _seats_config()
    seat_data = config.get("seats", [])
    categories: dict[str, list[dict]] = {
        "GOLD": [s for s in seat_data if s["category"] == "GOLD"],
        "DEATH": [s for s in seat_data if s["category"] == "DEATH"],
        "INSTITUTION": [s for s in seat_data if s["category"] == "INSTITUTION"],
    }
    scoring = config.get("lhb_scoring", {})
    gold_delta = float(scoring.get("gold_seat_delta", 15))
    death_delta = float(scoring.get("death_seat_delta", -20))
    inst_delta = float(scoring.get("institution_delta", 10))
    net_buy_weight = float(scoring.get("net_buy_weight", 0.05))

    for seat in seats:
        seat_name = str(seat.get("seat_name", ""))
        is_buy = bool(seat.get("is_buy", True))
        buy_amount = float(seat.get("buy_amount", 0.0))

        for g in categories["GOLD"]:
            if _seat_matches(seat_name, g.get("aliases", [])):
                score += gold_delta
                break
        for d in categories["DEATH"]:
            if _seat_matches(seat_name, d.get("aliases", [])):
                score += death_delta
                break
        for inst in categories["INSTITUTION"]:
            if _seat_matches(seat_name, inst.get("aliases", [])):
                if is_buy:
                    score += inst_delta
                break

        # 净买额加分(仅买入方向)
        if is_buy and buy_amount > 0:
            score += min(buy_amount * net_buy_weight, 20.0)

    return _clamp(score, 0.0, 100.0)


# --- F16 特例 ---


def f16_check(
    seat_name: str,
    *,
    is_first_board: bool,
    is_buy: bool,
    config: dict[str, Any] | None = None,
) -> float:
    """F16 特例:绍兴胜利东路在首板不扣分;二板及以上净买出现时扣 25。

    返回 score_delta(负数表示扣分)。
    """
    cfg = config or _seats_config()
    f16 = cfg.get("lhb_scoring", {})
    shaoxing_aliases = f16.get("f16_shaoxing_aliases", ["绍兴胜利东路"])

    if not _seat_matches(seat_name, shaoxing_aliases):
        return 0.0
    if is_buy and not is_first_board:
        return float(f16.get("f16_shaoxing_second_board_plus_delta", -25))
    return 0.0


# --- 质量等级 ---


def quality_grade(raw_score: float) -> str:
    if raw_score >= 70:
        return "GOOD"
    if raw_score >= 45:
        return "NEUTRAL"
    return "DANGEROUS"


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))
