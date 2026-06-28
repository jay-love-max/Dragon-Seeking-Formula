from __future__ import annotations

import pandas as pd
import requests

TENCENT_URL = "http://qt.gtimg.cn/q={q}"

# Mapping of Tencent v1 field index -> normalized field name
FIELDS_V1 = [
    "market", "code", "name", "open", "prev_close", "price", "high", "low",
    "_", "_", "volume", "turnover_amount", "_", "_", "_", "_",
    "change_pct", "_", "_", "_", "_", "_", "_", "_",
    "_", "_", "_", "_", "_", "_", "turnover", "_",
    "pe", "amplitude", "circulation", "_",
]


def get_realtime_quotes(codes: list[str]) -> pd.DataFrame | None:
    """
    Fetch real-time quotes from Tencent.

    codes: list of 6-digit strings (e.g. ["600519", "000001"])
    Returns: DataFrame with columns: 代码, 名称, 最新价, 涨跌幅, 换手率, 流通市值
    """
    if not codes:
        return None

    def _prefix(c):
        c = c.strip().zfill(6)
        if c.startswith("6") or c.startswith("9"):
            return f"sh{c}"
        elif c.startswith("0") or c.startswith("3") or c.startswith("2"):
            return f"sz{c}"
        elif c.startswith("4"):
            return f"bj{c}"
        return c

    queries = ",".join(_prefix(c) for c in codes)
    url = TENCENT_URL.format(q=queries)

    try:
        resp = requests.get(url, timeout=5)
        resp.encoding = "gbk"
        text = resp.text
    except Exception:
        return None

    rows = []
    for line in text.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            parts = line.split("~")
            if len(parts) < 50:
                continue

            code = parts[2]
            name = parts[1]
            price = _float(parts[3])
            change_pct = _float(parts[32])
            turnover = _float(parts[38])
            mcap = _float(parts[45]) * 1e4  # 流通市值 in 万元 -> 元

            rows.append({
                "代码": code,
                "名称": name,
                "最新价": price,
                "涨跌幅": change_pct,
                "换手率": turnover,
                "流通市值": mcap,
            })
        except (IndexError, ValueError):
            continue

    if not rows:
        return None

    return pd.DataFrame(rows)


def _float(v) -> float:
    try:
        return float(v) if v else 0.0
    except (ValueError, TypeError):
        return 0.0
