"""Phase 4 股性评分与 F17 禁买 — 纯函数实现。

方案第 10 节:
- 10.1 数据基础:炸板率、早盘板率、龙虎榜资金等;
- 10.2 评分公式:composite = activity*0.25 + reliability*0.25 + explosiveness*0.20
  + capital*0.15 + early_board*0.15;
- 10.3 观察窗口:近 750 个交易日(资金面 2 个月),严格排除未来数据;
- 10.4 等级映射:>=75 S,60-74.9 A,50-59.9 B+,45-49.9 B-,30-44.9 C,<30 D;
- 10.5 分阶段启用:shadow → coverage_gate → compare → enforce → monitor。

本模块是纯函数,不做 I/O;盘后与盘中共用同一逻辑。
"""
from __future__ import annotations

from rule_contract import PersonalityGrade, ReasonCode, RuleConfig

# 子分范围
MIN_SCORE = 0.0
MAX_SCORE = 100.0


def _clamp(value: float, lo: float = MIN_SCORE, hi: float = MAX_SCORE) -> float:
    return max(lo, min(hi, value))


# --- 活性评分 ---


def score_activity(total_limit_ups: int, max_possible: int = 120) -> float:
    """按历史涨停次数的分段阈值线性插值。

    方案 10.2:默认 max_possible=120(近 3 年交易日约 750 天,顶级游资约 120 次涨停)。
    插值:0→0, 60→60, 120→100, 中间线性,超过 120 截断。
    """
    if total_limit_ups <= 0:
        return 0.0
    if total_limit_ups >= max_possible:
        return 100.0
    if total_limit_ups <= 60:
        return total_limit_ups / 60 * 60
    return 60.0 + (total_limit_ups - 60) / (max_possible - 60) * 40.0


# --- 可靠性评分 ---


def score_reliability(
    limit_up_count: int,
    blown_count: int,
    min_sample: int = 5,
) -> float:
    """按炸板率评分。必须同时输出样本数(方案 10.2)。

    炸板率 = 炸板次数 / (封板次数 + 炸板次数)。
    样本数不足(limit_up_count < min_sample)时返回 None/0,表示不可靠。
    """
    if limit_up_count < min_sample or limit_up_count == 0:
        return 0.0
    rate = blown_count / limit_up_count
    if rate <= 0.1:
        return 100.0
    if rate <= 0.2:
        return 80.0
    if rate <= 0.3:
        return 60.0
    if rate <= 0.5:
        return 40.0
    if rate <= 0.7:
        return 20.0
    return 0.0


# --- 爆发力评分 ---


def score_explosiveness(max_consecutive_boards: int) -> float:
    """按历史最高连板映射。

    >=7:100, 6:90, 5:80, 4:65, 3:45, 2:20, 1:5, 0:0。
    """
    mapping = {0: 0.0, 1: 5.0, 2: 20.0, 3: 45.0, 4: 65.0, 5: 80.0, 6: 90.0}
    if max_consecutive_boards >= 7:
        return 100.0
    return mapping.get(max_consecutive_boards, 0.0)


# --- 资金面评分 ---


def score_capital(
    lhb_count: int,
    net_buy_yuan: float,
    has_institution: bool = False,
    lhb_count_max: int = 20,
    net_buy_max: float = 200_000_000.0,
) -> float:
    """近 2 月龙虎榜次数、净买额和机构方向评分。

    基础分为 lhb_count 归一化(最高 lhb_count_max=20 次)。
    净买额加分(最高 net_buy_max=2 亿)。
    机构方向额外加分。
    """
    base = _clamp(lhb_count / lhb_count_max * 60)
    buy_bonus = _clamp(net_buy_yuan / net_buy_max * 30) if net_buy_yuan > 0 else 0.0
    inst_bonus = 10.0 if has_institution else 0.0
    return _clamp(base + buy_bonus + inst_bonus)


# --- 早盘板评分 ---


def score_early_board(
    early_limit_count: int,
    total_limit_count: int,
    min_sample: int = 5,
) -> float:
    """历史首封早于 10:00 的比例。

    样本不足 total_limit_count < min_sample 时返回 0.0。
    """
    if total_limit_count < min_sample or total_limit_count == 0:
        return 0.0
    ratio = early_limit_count / total_limit_count
    if ratio >= 0.8:
        return 100.0
    if ratio >= 0.6:
        return 75.0
    if ratio >= 0.4:
        return 50.0
    if ratio >= 0.2:
        return 25.0
    return 10.0


# --- 综合评分与等级 ---


def compute_personality(
    *,
    activity: float,
    reliability: float,
    explosiveness: float,
    capital: float,
    early_board: float,
    cfg: RuleConfig,
    sample_count: int | None = None,
) -> tuple[float, PersonalityGrade, str | None]:
    """Compute composite personality score and grade.

    Returns (composite_score, grade, warning_or_None).
    样本不足(activity/reliability 为 0 可能因为缺数据)返回 UNKNOWN。
    """
    pers = cfg.raw["personality"]
    w_act = float(pers["weight_activity"])
    w_rel = float(pers["weight_reliability"])
    w_exp = float(pers["weight_explosiveness"])
    w_cap = float(pers["weight_capital"])
    w_early = float(pers["weight_early_board"])

    composite = (
        activity * w_act
        + reliability * w_rel
        + explosiveness * w_exp
        + capital * w_cap
        + early_board * w_early
    )
    composite = round(composite, 1)

    # Detect insufficient data: if activity/reliability both zero, likely no data
    min_grade_sample = int(pers.get("personality_min_sample_count", 20))
    if sample_count is not None and sample_count < min_grade_sample:
        return composite, PersonalityGrade.UNKNOWN, "insufficient_sample"

    grade = _grade(composite, cfg)
    return composite, grade, None


def _grade(score: float, cfg: RuleConfig) -> PersonalityGrade:
    pers = cfg.raw["personality"]
    s_min = float(pers["grade_s_min"])
    a_min = float(pers["grade_a_min"])
    b_plus_min = float(pers["grade_b_plus_min"])
    b_minus_min = float(pers["grade_b_minus_min"])
    c_min = float(pers["grade_c_min"])

    if score >= s_min:
        return PersonalityGrade.S
    if score >= a_min:
        return PersonalityGrade.A
    if score >= b_plus_min:
        return PersonalityGrade.B_PLUS
    if score >= b_minus_min:
        return PersonalityGrade.B_MINUS
    if score >= c_min:
        return PersonalityGrade.C
    return PersonalityGrade.D


def personality_blocked_reason(grade: PersonalityGrade) -> str | None:
    """F17 禁买判断:如果 grade 为 B-/C/D,返回原因码;否则返回 None。

    方案 10.5:enforce 阶段启用。shadow 阶段仅记录不阻断。
    """
    mapping = {
        PersonalityGrade.B_MINUS: ReasonCode.PERSONALITY_B_MINUS_BLOCKED,
        PersonalityGrade.C: ReasonCode.PERSONALITY_C_BLOCKED,
        PersonalityGrade.D: ReasonCode.PERSONALITY_D_BLOCKED,
    }
    code = mapping.get(grade)
    if code:
        return code
    if grade == PersonalityGrade.UNKNOWN:
        return ReasonCode.PERSONALITY_DATA_MISSING
    return None
