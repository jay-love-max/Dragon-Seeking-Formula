"""Shared relay score computation — used by recap_engine and data_pipeline."""

from __future__ import annotations

from typing import Any


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        if isinstance(value, str) and not value.strip():
            return default
        if isinstance(value, float) and value != value:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        if isinstance(value, str) and not value.strip():
            return default
        if isinstance(value, float) and value != value:
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _normalize_time(value: Any, default: str = "120000") -> str:
    text = "".join(ch for ch in str(value or "") if ch.isdigit())
    if len(text) >= 6:
        return text[:6]
    if len(text) == 4:
        return f"{text}00"
    if len(text) == 6:
        return text
    return default


def _time_points(time_str: str) -> int:
    if time_str == "092500":
        return 25
    if time_str <= "093500":
        return 20
    if time_str <= "094500":
        return 15
    if time_str <= "103000":
        return 10
    if time_str <= "113000":
        return 5
    if time_str >= "143000":
        return -15
    if time_str >= "130000":
        return -5
    return 0


def _stability_points(blown: int) -> int:
    if blown == 0:
        return 15
    if blown == 1:
        return 5
    if blown == 2:
        return -5
    return -15


def _seal_points(seal_funds: float, float_mcap: float) -> int:
    seal_ratio = (seal_funds / float_mcap) * 100 if float_mcap > 0 else 0.0
    if seal_ratio >= 8.0:
        return 20
    if seal_ratio >= 4.0:
        return 15
    if seal_ratio >= 2.0:
        return 10
    if seal_ratio >= 1.0:
        return 5
    if seal_ratio < 0.5:
        return -10
    return 0


def _size_points(float_mcap: float) -> int:
    mcap_yi = float_mcap / 1e8
    if mcap_yi <= 30.0:
        return 15
    if mcap_yi <= 80.0:
        return 10
    if mcap_yi <= 150.0:
        return 5
    if mcap_yi > 300.0:
        return -20
    return -10


def _turnover_points(turnover: float, is_one_word: bool) -> int:
    if 4.0 <= turnover <= 12.0:
        return 10
    if 12.0 <= turnover <= 20.0:
        return 5
    if turnover < 2.0 and not is_one_word:
        return -10
    if turnover > 20.0:
        return -15
    return 0


def _sector_points(sector_limit_ups: int) -> int:
    if sector_limit_ups >= 6:
        return 20
    if sector_limit_ups >= 4:
        return 15
    if sector_limit_ups == 3:
        return 10
    if sector_limit_ups == 2:
        return 5
    return 0


def _noise_caps(
    score: int,
    time_str: str,
    blown: int,
    turnover: float,
    sector_limit_ups: int,
    is_one_word: bool,
    timing_points: int,
    stability_points: int,
    seal_points: int,
    size_points: int,
    turnover_points: int,
    sector_points: int,
) -> int:
    supportive_factors = sum(
        p >= 10
        for p in (
            timing_points,
            stability_points,
            seal_points,
            size_points,
            turnover_points,
            sector_points,
        )
    )

    if supportive_factors <= 2:
        score = min(score, 85)
    elif supportive_factors == 3:
        score = min(score, 100)

    if blown >= 2:
        score = min(score, 80)
    if sector_limit_ups <= 1 and not is_one_word:
        score = min(score, 90)
    if time_str >= "140000" and not is_one_word:
        score = min(score, 75)
    if turnover > 20.0 and blown >= 1:
        score = min(score, 70)

    return score


def compute_relay_score(row: dict, sector_limit_ups: int) -> int:
    """Compute the 1进2 relay score (0-150) for a limit-up candidate."""
    time_str = _normalize_time(row.get("first_seal_time"))
    is_one_word = time_str == "092500"

    blown = _safe_int(row.get("blown_count"), 0)
    float_mcap = _safe_float(row.get("float_mcap"), 0.0)
    seal_funds = _safe_float(row.get("seal_funds"), 0.0)
    turnover = _safe_float(row.get("turnover"), 0.0)
    sector_limit_ups = _safe_int(sector_limit_ups, 0)

    timing_points = _time_points(time_str)
    stability_points = _stability_points(blown)
    seal_points = _seal_points(seal_funds, float_mcap)
    size_points = _size_points(float_mcap)
    turnover_points = _turnover_points(turnover, is_one_word)
    sector_points = _sector_points(sector_limit_ups)

    score = 50 + (
        timing_points
        + stability_points
        + seal_points
        + size_points
        + turnover_points
        + sector_points
    )

    score = _noise_caps(
        score=score,
        time_str=time_str,
        blown=blown,
        turnover=turnover,
        sector_limit_ups=sector_limit_ups,
        is_one_word=is_one_word,
        timing_points=timing_points,
        stability_points=stability_points,
        seal_points=seal_points,
        size_points=size_points,
        turnover_points=turnover_points,
        sector_points=sector_points,
    )

    return max(0, min(150, score))


def generate_playbook(
    sector: str,
    time_str: str,
    blown: int,
    turnover: float,
    score: int,
    sector_limit_ups: int,
) -> str:
    """Generate momentum trading playbook based on stock metrics."""
    sector = sector or "未分类"
    time_str = _normalize_time(time_str)
    blown = _safe_int(blown, 0)
    turnover = _safe_float(turnover, 0.0)
    score = _safe_int(score, 0)
    sector_limit_ups = _safe_int(sector_limit_ups, 0)
    is_one_word = time_str == "092500"
    time_formatted = f"{time_str[:2]}:{time_str[2:4]}:{time_str[4:]}"

    if is_one_word:
        return (
            "【一字极速板】今日全天一字锁死，筹码高度锁定。明日接力策略：不要在竞价或开盘直接挂单排队以防'炸板闷杀'。"
            "可关注明日开盘后的'分歧洗盘再封板'机会。若明日竞价放量且高开在5%-8%之间，可等换手承接充分、下探均线重新走强时介入。"
        )
    if score >= 115:
        return (
            f"【核心领涨黄金标的】今日于 {time_formatted} 极速封板，炸板 {blown} 次，属于多头资金绝对主导的超强首板。所属【{sector}】"
            f"板块今日大面积爆发（共 {sector_limit_ups} 只涨停），板块效应极佳。明日接力策略：明日大概率高开（>4%）。若早盘竞价成交量"
            f"达到今日首板成交额的10%以上，且开盘5分钟内快速放量拉升，可果断半路跟进；或在换手率达到5%左右、股价再度封死二板瞬间打板买入。"
        )
    if score >= 95:
        return (
            f"【强势突围潜力股】首次封板时间 {time_formatted} 处于早盘黄金期，炸板仅 {blown} 次，换手率 {turnover}% 适中，筹码换手健康。"
            f"明日接力策略：明日竞价若小幅高开（2%-4%）且放量，说明有资金继续做接力。建议开盘后等冲高回调至均线守住、再度向上翻红放量时介入；"
            f"或者等日内充分换手（>10%）后，尾盘重新冲击极限封板时确认打板。"
        )
    if blown >= 2 or time_str >= "140000":
        return (
            f"【分歧烂板/尾盘偷袭】今日封板极晚（{time_formatted}）且炸板 {blown} 次，资金分歧剧烈，换手率偏高，筹码结构不稳。"
            f"明日接力策略：该股属于弱势板，明日接力必须遵循'弱转强'原则。弱转强标志：明日竞价超预期高开在2%以上，且开盘快速放量拉升。"
            f"如果明日平开或低开，说明今天套牢盘压力沉重，资金弃疗，应坚决放弃关注，避免接盘。"
        )
    return (
        f"【常规轮动跟风标的】首次封板时间 {time_formatted}，换手率 {turnover}% 正常。所属行业【{sector}】今天有 {sector_limit_ups} 只涨停，"
        f"地位属于跟风或侧翼。明日接力策略：除非明日所属板块龙头开盘封死一字板，带动资金溢出做跟风接力，否则该股性价比一般。"
        f"建议明日不急于建仓，仅作为同板块情绪风向标观察，避免冲高回落被套。"
    )
