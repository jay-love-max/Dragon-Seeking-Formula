from __future__ import annotations

import re
from datetime import datetime

import pandas as pd

FIELD_MAP = {
    "代码": "code", "code": "code", "symbol": "code",
    "名称": "name", "name": "name",
    "最新价": "price", "price": "price", "current": "price",
    "涨跌幅": "change_pct", "change_pct": "change_pct", "pct_chg": "change_pct",
    "换手率": "turnover", "turnover": "turnover", "turnover_ratio": "turnover",
    "流通市值": "float_mcap",
    "封板资金": "seal_funds", "seal_funds": "seal_funds", "funds": "seal_funds",
    "炸板次数": "blown_count", "blown_count": "blown_count",
    "首次封板时间": "first_seal_time",
    "所属行业": "sector", "sector": "sector",
    "标题": "title", "title": "title",
    "内容": "content", "content": "content",
    "时间": "ts", "datetime": "ts",
}

PRESERVE_COLUMNS = {
    "source_tag",
    "quality_state",
    "missing_fields",
    "consecutive_boards",
    "sector_limit_ups",
}

NUMERIC_COLUMNS = {
    "price",
    "change_pct",
    "turnover",
    "float_mcap",
    "seal_funds",
}

INT_COLUMNS = {
    "blown_count",
    "consecutive_boards",
    "sector_limit_ups",
}

REQUIRED_BY_SOURCE = {
    "ashare": ["code", "price", "change_pct", "turnover", "float_mcap"],
    "zt_pool": [
        "code", "name", "price", "change_pct", "turnover", "float_mcap",
        "seal_funds", "first_seal_time", "blown_count", "consecutive_boards", "sector",
    ],
    "news": ["code", "title", "content", "ts"],
}


def _is_missing(value) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        text = value.strip().lower()
        return text in {"", "nan", "none", "null", "na", "n/a", "-", "--"}
    try:
        return bool(pd.isna(value))
    except Exception:
        return False


def _normalize_code(value) -> str:
    if _is_missing(value):
        return ""
    text = str(value).strip().upper()
    text = re.sub(r"\.(SH|SZ|BJ)$", "", text)
    digits = re.sub(r"\D", "", text)
    return digits[:6].zfill(6) if digits else ""


def _normalize_time(value) -> str:
    if _is_missing(value):
        return ""
    digits = re.sub(r"\D", "", str(value))
    if not digits:
        return ""
    if len(digits) >= 6:
        return digits[:6]
    if len(digits) == 4:
        return f"{digits}00"
    return digits.zfill(6)


def _coerce_source(value: object, fallback: str) -> str:
    return fallback if _is_missing(value) else str(value)


def _quality_state_for_row(row: pd.Series, source: str) -> tuple[str, str]:
    required = REQUIRED_BY_SOURCE.get(source, [])
    missing = [col for col in required if col not in row.index or _is_missing(row[col])]
    if not missing:
        return "complete", ""
    return "degraded", ",".join(missing)


def normalize(source: str, df: pd.DataFrame) -> pd.DataFrame:
    """Normalize field names, code format, numeric types, timestamps, and quality markers."""
    if df.empty:
        return df.copy()

    df = df.copy().rename(columns=FIELD_MAP)

    keep_cols = [
        c for c in df.columns
        if c in set(FIELD_MAP.values()) or c == "ts" or c in PRESERVE_COLUMNS
    ]
    df = df[keep_cols]

    if "code" in df.columns:
        df["code"] = df["code"].apply(_normalize_code)
        df = df[df["code"] != ""]

    for col in NUMERIC_COLUMNS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    for col in INT_COLUMNS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)

    if "first_seal_time" in df.columns:
        df["first_seal_time"] = df["first_seal_time"].apply(_normalize_time)

    if "source_tag" not in df.columns:
        df["source_tag"] = source
    else:
        df["source_tag"] = df["source_tag"].apply(lambda v: _coerce_source(v, source))

    if "ts" not in df.columns:
        df["ts"] = datetime.now().isoformat(timespec="seconds")
    else:
        now = datetime.now().isoformat(timespec="seconds")
        df["ts"] = df["ts"].apply(lambda v: now if _is_missing(v) else str(v))

    if source in REQUIRED_BY_SOURCE:
        states = df.apply(lambda row: _quality_state_for_row(row, source), axis=1, result_type="expand")
        df["quality_state"] = states[0]
        df["missing_fields"] = states[1]
    else:
        df["quality_state"] = "complete"
        df["missing_fields"] = ""

    return df.reset_index(drop=True)
