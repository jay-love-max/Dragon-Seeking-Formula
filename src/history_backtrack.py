from __future__ import annotations

from enum import StrEnum


class BacktrackPattern(StrEnum):
    SHRINK_DOJI = "SHRINK_DOJI"
    SEVERE_REVERSAL = "SEVERE_REVERSAL"
    SHALLOW_DIP = "SHALLOW_DIP"


def detect_shrink_doji(
    closes: list[float],
    volumes: list[float],
    opens: list[float] | None = None,
    *,
    shrink_target: float = 0.50,
    doji_pct: float = 0.15,
    lookback: int = 15,
) -> tuple[bool, float, str]:
    if len(closes) < 8 or len(volumes) < 8:
        return False, 0.0, "insufficient_data"
    recent = min(lookback, len(closes))
    rv = volumes[-recent:]
    rc = closes[-recent:]
    ro = opens[-recent:] if opens else rc

    peak_vol = max(rv[:-1])
    today_vol = rv[-1]
    if peak_vol <= 0:
        return False, 0.0, "zero_peak_volume"
    vol_ratio = today_vol / peak_vol
    if vol_ratio > shrink_target:
        return False, 0.0, f"vol_ratio={vol_ratio:.3f}>{shrink_target}"

    today_o = ro[-1]
    today_c = rc[-1]
    body = abs(today_c - today_o)
    recent_high = max(rc)
    recent_low = min(rc)
    amp = recent_high - recent_low
    if amp > 0 and (body / amp) > doji_pct:
        return False, 0.0, f"body_ratio={body/amp:.3f}>{doji_pct}"

    vol_score = max(0, 1.0 - vol_ratio / shrink_target) * 50
    price_pos = (today_c - recent_low) / amp if amp > 0 else 0.5
    price_score = max(0, 1.0 - price_pos * 1.5) * 50
    score = round(min(100, vol_score + price_score), 1)
    evidence = (
        f"shrink_doji:vol_ratio={vol_ratio:.3f},"
        f"peak_vol={peak_vol:.0f},close={today_c:.2f},score={score}"
    )
    return True, score, evidence


def detect_severe_reversal(
    closes: list[float],
    *,
    drop_threshold: float = -0.15,
    reversal_lookback: int = 3,
    total_lookback: int = 15,
) -> tuple[bool, float, str]:
    if len(closes) < 8:
        return False, 0.0, "insufficient_data"
    recent = min(total_lookback, len(closes))
    rc = closes[-recent:]
    max_idx = max(range(len(rc)), key=lambda i: rc[i])
    min_idx = min(range(len(rc)), key=lambda i: rc[i])
    if max_idx >= min_idx:
        return False, 0.0, "no_downtrend"
    drop = (rc[min_idx] - rc[max_idx]) / rc[max_idx]
    if drop > drop_threshold:
        return False, 0.0, f"drop={drop:.3f}>{drop_threshold}"

    reversal_window = rc[min_idx:]
    if len(reversal_window) < 2:
        return False, 0.0, "no_reversal_window"
    reversal_move = (reversal_window[-1] - reversal_window[0]) / reversal_window[0]
    if reversal_move <= 0:
        return False, 0.0, f"no_reversal:move={reversal_move:.3f}"
    if len(reversal_window) <= reversal_lookback + 1:
        rebound = reversal_window[-1] / reversal_window[0] - 1
        rebound_score = rebound * 3
    else:
        rebound = (max(reversal_window) - reversal_window[0]) / reversal_window[0]
        rebound_score = rebound * 2
    rebound_score = max(0, min(100, rebound_score * 100))
    score = round(rebound_score, 1)
    evidence = (
        f"severe_reversal:drop={drop:.3f},"
        f"reversal={reversal_move:.3f},score={score}"
    )
    return True, score, evidence


def detect_shallow_dip(
    closes: list[float],
    float_mcap_yuan: float | None = None,
    *,
    large_cap_threshold: float = 10e9,
    dip_max: float = -0.05,
    lookback: int = 20,
) -> tuple[bool, float, str]:
    if len(closes) < 8:
        return False, 0.0, "insufficient_data"
    if float_mcap_yuan is None or float_mcap_yuan < large_cap_threshold:
        return False, 0.0, "not_large_cap"
    recent = min(lookback, len(closes))
    rc = closes[-recent:]
    high = max(rc)
    low = min(rc)
    dip = (low - high) / high
    if dip < dip_max:
        return False, 0.0, f"dip={dip:.3f}<{dip_max}"
    latest = rc[-1]
    recovery = (latest - low) / low if low > 0 else 0
    score = round(min(100, (1 - abs(dip) / abs(dip_max)) * 60 + min(recovery, 0.05) * 800), 1)
    evidence = (
        f"shallow_dip:dip={dip:.3f},"
        f"recovery={recovery:.3f},high={high:.2f},score={score}"
    )
    return True, score, evidence
