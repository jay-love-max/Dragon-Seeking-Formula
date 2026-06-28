from __future__ import annotations

import pandas as pd

SOURCE_PRIORITY = ["zt_pool", "ashare", "news"]

# Quote fields belong to the fastest realtime source. Limit-up metadata belongs
# to the ZT pool. Other fields use the record-level default priority above.
FIELD_SOURCE_PRIORITY = {
    "price": ["ashare", "zt_pool"],
    "change_pct": ["ashare", "zt_pool"],
    "turnover": ["ashare", "zt_pool"],
    "float_mcap": ["ashare", "zt_pool"],
    "seal_funds": ["zt_pool"],
    "first_seal_time": ["zt_pool"],
    "blown_count": ["zt_pool"],
    "consecutive_boards": ["zt_pool"],
    "sector": ["zt_pool"],
}

FIELD_SOURCE_GROUP = {
    "price": "quote_source_tag",
    "change_pct": "quote_source_tag",
    "turnover": "quote_source_tag",
    "float_mcap": "quote_source_tag",
    "seal_funds": "limit_up_source_tag",
    "first_seal_time": "limit_up_source_tag",
    "blown_count": "limit_up_source_tag",
    "consecutive_boards": "limit_up_source_tag",
    "sector": "limit_up_source_tag",
}

SNAPSHOT_COLUMNS = [
    "code", "name", "price", "change_pct", "turnover",
    "seal_funds", "first_seal_time", "blown_count", "sector",
    "consecutive_boards", "float_mcap", "sector_limit_ups",
    "score_intraday", "score_intraday_prev",
    "quality_state", "missing_fields",
    "ts", "source_tag", "quote_source_tag", "limit_up_source_tag",
]

MISSING_STRINGS = {"", "nan", "none", "null", "na", "n/a", "-", "--"}


def _is_missing(value) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip().lower() in MISSING_STRINGS
    try:
        return bool(pd.isna(value))
    except Exception:
        return False


def _normalize_code(value) -> str:
    text = str(value or "").strip().upper()
    text = text.replace(".SH", "").replace(".SZ", "").replace(".BJ", "")
    digits = "".join(ch for ch in text if ch.isdigit())
    return digits[:6].zfill(6) if digits else ""


def _priority(source: str, field: str = "") -> int:
    priorities = FIELD_SOURCE_PRIORITY.get(field, SOURCE_PRIORITY)
    if source in priorities:
        return priorities.index(source)
    return 999


def merge(source: str, new_df: pd.DataFrame, snapshot: dict) -> pd.DataFrame:
    """
    Merge new collector data with existing in-memory snapshot.

    snapshot: dict of {code: dict} — the current in-memory state.
    Returns the complete materialized snapshot, ready for scoring and DB upsert.
    """
    merged_snapshot = {}
    for snapshot_code, record in snapshot.items():
        code = _normalize_code(snapshot_code)
        if code:
            merged_snapshot[code] = {**record, "code": code}

    for _, row in new_df.iterrows():
        code = _normalize_code(row.get("code", ""))
        if not code:
            continue

        base = dict(merged_snapshot.get(code, {}))
        old_source = str(base.get("source_tag", "") or "")
        new_source = str(row.get("source_tag") or source or "")
        changed_meaningful = False

        for col, val in row.items():
            if col in {"code", "source_tag"}:
                continue
            if col == "ts":
                if not _is_missing(val):
                    base[col] = val
                continue
            if _is_missing(val):
                continue

            provenance_field = FIELD_SOURCE_GROUP.get(col)
            old_field_source = str(base.get(provenance_field) or old_source)
            if col in base and not _is_missing(base[col]):
                new_rank = _priority(new_source, col)
                old_rank = _priority(old_field_source, col)
                if new_rank > old_rank:
                    continue
                if new_rank == old_rank and base[col] == val:
                    continue

            base[col] = val
            if provenance_field:
                base[provenance_field] = new_source
            changed_meaningful = True

        base["code"] = code

        new_rank = _priority(new_source)
        old_rank = _priority(old_source)
        if _is_missing(old_source):
            if not _is_missing(new_source):
                base["source_tag"] = new_source
        elif new_rank < old_rank:
            base["source_tag"] = new_source
        elif new_rank == old_rank and changed_meaningful and not _is_missing(new_source):
            base["source_tag"] = new_source
        elif "source_tag" not in base and not _is_missing(new_source):
            base["source_tag"] = new_source

        merged_snapshot[code] = base

    if not merged_snapshot:
        return pd.DataFrame(columns=SNAPSHOT_COLUMNS)

    result = pd.DataFrame(merged_snapshot.values())
    for col in SNAPSHOT_COLUMNS:
        if col not in result.columns:
            result[col] = None
    return result[SNAPSHOT_COLUMNS]
