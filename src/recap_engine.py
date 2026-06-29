import json
import os
import sys
import uuid
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, roc_auc_score

try:
    from openai import OpenAI
except Exception:
    OpenAI = None

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from candidate_policy import CandidateEligibility, evaluate_f19, rank_candidates  # noqa: E402
from candidate_store import persist_decisions_and_top5, persist_observation  # noqa: E402
from data_adapters import get_adapter  # noqa: E402
from db import (  # noqa: E402
    apply_migrations,
    backup_database,
    create_legacy_tables,
    current_schema_version,
    ensure_sqlite_runtime,
    integrity_check,
    persist_execution_plans,
    persist_limit_up_archive,
    persist_market_recap,
    persist_market_risk,
    record_run_completion,
    record_run_start,
    record_source_snapshot,
)
from db import (
    connect as db_connect,
)
from execution_policy import auction_matrix, buy_plan, defensive_sell_plan  # noqa: E402
from feature_engineering import apply_f14_boost, check_recent_4d_2b  # noqa: E402
from market_risk import compute_adjusted_score, evaluate_market_risk  # noqa: E402
from ml_pipeline import split_time_series_calibration, train_and_calibrate  # noqa: E402
from stock_personality import (  # noqa: E402
    compute_personality,
    personality_blocked_reason,
    score_activity,
    score_capital,
    score_early_board,
    score_explosiveness,
    score_reliability,
)
from trading_calendar import (  # noqa: E402
    SHANGHAI_TZ,
    assert_corroborates,
    calendar_metadata,
    now_shanghai,
)
from trading_calendar import (
    is_trading_day as calendar_is_trading_day,
)

ADAPTER = get_adapter()
MODEL_VERSION = "rf-v2-expanding-sector"

# Base Paths
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DB_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.getenv("RECAP_DB_PATH", os.path.join(DB_DIR, "recap.db"))

# Create directories if not exist
os.makedirs(DB_DIR, exist_ok=True)

BACKEND_API_DIR = os.path.join(
    BASE_DIR, "vendor", "tickflow-stock-panel", "backend", "app", "api"
)
if BACKEND_API_DIR not in sys.path:
    sys.path.insert(0, BACKEND_API_DIR)
from _uzi_shared import (  # noqa: E402
    _evaluate_finance_trap,
    _pick,
    _safe_float,
    _safe_int,
    build_uzi_analysis_payload,
)

# THS HTTP headers
THS_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36"
}


def init_db():
    """Initialize SQLite database tables and apply migrations."""
    ensure_sqlite_runtime()
    db_file = Path(DB_PATH)
    db_file.parent.mkdir(parents=True, exist_ok=True)
    if db_file.exists() and current_schema_version(DB_PATH) == 0:
        backup_database(DB_PATH, str(db_file.with_suffix(".pre_migration.bak")))
    create_legacy_tables(DB_PATH)
    apply_migrations(DB_PATH)
    if integrity_check(DB_PATH) != "ok":
        raise RuntimeError("SQLite integrity_check failed after migration")
def get_trading_days(offset=60):
    """Fetch trading days using the current data adapter.

    适配器返回 FetchResult(方案 7.1);此处解包为旧调用方期望的列表。
    适配器失败时返回 UNAVAILABLE 而非伪装的工作日列表(方案 8.2),
    这里透传空列表,调用方应通过 publish_gate 判断是否阻断。
    """
    result = ADAPTER.get_trading_days(offset=offset)
    # 旧调用方(主日历、回填)仍消费 list[str];FetchResult 供 publish_gate 使用。
    if result.is_ok and not result.payload.empty:
        return result.payload["trade_date"].tolist()
    return []


def _index_fetchresult_to_legacy_dict(result):
    """把指数 FetchResult 解包成旧消费方期望的 dict。

    旧形状:{"sh": {"price", "change"}, "sz": ..., "cy": ..., "total_turnover": ...}
    payload 列:index, price, change_pct, amount_yuan。
    缺失的指数不写入(而非写 0),total_turnover 由 sh+sz amount 合成。
    """
    if not result.is_ok or result.payload.empty:
        return {}
    recap = {}
    sh_amount = None
    sz_amount = None
    for _, row in result.payload.iterrows():
        name = str(row["index"])
        recap[name] = {
            "price": float(row["price"]),
            "change": float(row["change_pct"]),
        }
        if name == "sh":
            sh_amount = float(row["amount_yuan"])
        elif name == "sz":
            sz_amount = float(row["amount_yuan"])
    if sh_amount is not None and sz_amount is not None:
        total_turnover = (sh_amount + sz_amount) / 1e9
        recap["total_turnover"] = round(total_turnover, 2)
    else:
        recap["total_turnover"] = None
    return recap

def get_previous_trading_day(date_str, trade_dates):
    """Find the trading day immediately before date_str.

    优先使用 XSHG 主日历(方案 8.1/11.1:必须通过交易日历寻找 T-1,
    不得用自然日减一天);仅在主日历不可用时退回 trade_dates 列表查找。
    """
    try:
        from trading_calendar import previous_trading_day
        return previous_trading_day(date_str).isoformat()
    except Exception:
        # 旧路径:列表内最大小于 date_str 的交易日(用于回填等无日历场景)
        if date_str in trade_dates:
            idx = trade_dates.index(date_str)
            if idx > 0:
                return trade_dates[idx - 1]
        smaller_dates = [d for d in trade_dates if d < date_str]
        if smaller_dates:
            return max(smaller_dates)
        return None


def resolve_recap_date(
    date_arg,
    trade_dates,
    *,
    force_non_trading_day=False,
    now=None,
):
    """Resolve the recap target date and mode.

    When no explicit date is provided, default to today's trading date. If
    today is a non-trading day and replay is not forced, fall back to the most
    recent trading day so the normal daily run stays on-market.

    时间锚定 Asia/Shanghai:容器 TZ=UTC 时 naive datetime.now() 会把"今日"误判
    成 UTC 日期(差 8 小时),导致非交易日误发布或漏发布。这里默认调用
    now_shanghai(),并接受带 tzinfo 的 now 归一到上海日期;兜底(非交易日回退)
    强制 observation_only=True,避免 INSERT OR REPLACE 覆盖已发布交易日数据
    (AGENTS.md:非交易日必须 fail closed,数据缺失不得填成看似有效的 0 发布)。
    """
    if date_arg:
        return date_arg, force_non_trading_day, False

    if now is None:
        now = now_shanghai()
    # naive datetime 视为上海本地时间(与 now_shanghai() 语义一致);
    # aware datetime 归一到上海日期,避免跨时区漂移。
    today = now.astimezone(SHANGHAI_TZ).strftime("%Y-%m-%d") if now.tzinfo else now.strftime("%Y-%m-%d")
    try:
        from trading_calendar import is_trading_day

        is_td = is_trading_day(today)
    except Exception:
        is_td = today in trade_dates

    if is_td or force_non_trading_day:
        return today, force_non_trading_day, False

    # 非交易日兜底回退:强制 observation_only=True,只写观察样本不覆盖发布产物。
    prev = get_previous_trading_day(today, trade_dates)
    return (prev or today), True, True


def _parse_time_to_seconds(time_str):
    try:
        text = str(time_str).strip()
        if not text:
            return None
        digits = "".join(ch for ch in text if ch.isdigit())
        if not digits:
            return None
        t = digits.zfill(6)[-6:]
        hours = int(t[:2])
        minutes = int(t[2:4])
        seconds = int(t[4:])
        if hours > 23 or minutes > 59 or seconds > 59:
            return None

        total_seconds = hours * 3600 + minutes * 60 + seconds
        ref_seconds = 9 * 3600 + 25 * 60
        return total_seconds - ref_seconds
    except Exception:
        return None


def time_to_seconds(time_str):
    """Convert HHMMSS string to seconds since 09:25:00"""
    value = _parse_time_to_seconds(time_str)
    return 0 if value is None else value


def _coerce_float(value, default=0.0):
    try:
        if value is None:
            return default
        if isinstance(value, str) and not value.strip():
            return default
        if isinstance(value, float) and value != value:
            return default
        return float(value)
    except Exception:
        return default


def _coerce_int(value, default=0):
    try:
        if value is None:
            return default
        if isinstance(value, str) and not value.strip():
            return default
        if isinstance(value, float) and value != value:
            return default
        return int(float(value))
    except Exception:
        return default


def _is_missing_value(value):
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    try:
        return bool(pd.isna(value))
    except Exception:
        return False


def _execution_profile(row):
    first_seal_time = row.get("first_seal_time") or ""
    parsed_first_seal_sec = _parse_time_to_seconds(first_seal_time)
    first_seal_sec = time_to_seconds(first_seal_time)
    missing_first_seal = _is_missing_value(first_seal_time) or parsed_first_seal_sec is None
    blown = _coerce_int(row.get("blown_count"), 0)
    turnover = _coerce_float(row.get("turnover", row.get("turnover_pct")), 0.0)
    seal_ratio = _coerce_float(row.get("seal_ratio"), 0.0)

    if seal_ratio <= 0:
        seal_funds = _coerce_float(row.get("seal_funds", row.get("seal_funds_yuan")), 0.0)
        float_mcap = _coerce_float(row.get("float_mcap", row.get("float_mcap_yuan")), 0.0)
        if float_mcap > 0:
            seal_ratio = seal_funds / float_mcap * 100

    if missing_first_seal:
        time_penalty = 18
    elif first_seal_sec >= 18000:
        time_penalty = 18
    elif first_seal_sec >= 12000:
        time_penalty = 12
    elif first_seal_sec >= 6000:
        time_penalty = 6
    else:
        time_penalty = 0

    stability_penalty = 0 if blown == 0 else 4 if blown == 1 else 12 if blown == 2 else 20
    liquidity_penalty = 0
    if turnover > 20.0:
        liquidity_penalty = 10
    elif turnover > 12.0:
        liquidity_penalty = 4
    elif turnover < 2.0:
        liquidity_penalty = 6

    seal_penalty = 0 if seal_ratio >= 4.0 else 4 if seal_ratio >= 2.0 else 8 if seal_ratio >= 1.0 else 14
    slippage_bp = min(60, 8 + time_penalty + stability_penalty + liquidity_penalty + seal_penalty)

    t1_tradeable = int(
        not missing_first_seal
        and first_seal_sec < 18300
        and blown <= 2
        and seal_ratio >= 1.0
        and turnover <= 20.0
    )
    execution_penalty = slippage_bp + (0 if t1_tradeable else 12)

    return {
        "execution_slippage_bp": slippage_bp,
        "t1_tradeable": t1_tradeable,
        "execution_penalty": execution_penalty,
    }


def _apply_execution_profile(df):
    profile = df.apply(_execution_profile, axis=1, result_type="expand")
    df["execution_slippage_bp"] = profile["execution_slippage_bp"].astype(float)
    df["t1_tradeable"] = profile["t1_tradeable"].astype(int)
    df["execution_penalty"] = profile["execution_penalty"].astype(float)
    return df


def _apply_realtime_snapshot(df, snapshot):
    if df.empty or not snapshot:
        return df

    df = df.copy()
    if "code" not in df.columns:
        return df

    # df_pool is canonical English (LimitUpPoolSchema); realtime_snapshot stores
    # legacy short names (turnover/float_mcap/seal_funds without _pct/_yuan).
    field_map = {
        "name": "name",
        "price": "price",
        "change_pct": "change_pct",
        "turnover_pct": "turnover",
        "float_mcap_yuan": "float_mcap",
        "seal_funds_yuan": "seal_funds",
        "first_seal_time": "first_seal_time",
        "blown_count": "blown_count",
        "sector": "sector",
    }

    codes = df["code"].astype(str).str.zfill(6)
    for idx, code in codes.items():
        record = snapshot.get(code)
        if not record:
            continue
        for target_col, source_key in field_map.items():
            if target_col not in df.columns:
                continue
            fallback = record.get(source_key)
            if not _is_missing_value(fallback):
                df.at[idx, target_col] = fallback

    return df


def _load_realtime_snapshot_from_db(db_path):
    snapshot = {}
    try:
        conn = db_connect(db_path, read_only=True)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='realtime_snapshot'"
        )
        if not cursor.fetchone():
            conn.close()
            return snapshot

        cursor = conn.execute("SELECT * FROM realtime_snapshot")
        columns = [d[0] for d in cursor.description]
        for row in cursor.fetchall():
            record = dict(zip(columns, row))
            code = str(record.pop("code", "")).zfill(6)
            if code:
                snapshot[code] = record
        conn.close()
    except Exception:
        return {}
    return snapshot


def preprocess_features(df, sector_encoding):
    """Convert raw candidate and market features to numerical features for training/inference."""
    df = df.copy()

    required_defaults = {
        "first_seal_time": "",
        "blown_count": 0,
        "turnover": 0.0,
        "float_mcap": 0.0,
        "seal_funds": 0.0,
        "seal_ratio": 0.0,
        "score": 0,
        "sh_change": 0.0,
        "sz_change": 0.0,
        "cy_change": 0.0,
        "total_turnover": 0.0,
        "limit_ups": 0,
        "limit_downs": 0,
        "promotion_rate": 0.0,
        "sentiment": "中性",
        "sector": "",
    }
    for col, default in required_defaults.items():
        if col not in df.columns:
            df[col] = default

    df["seal_time_sec"] = df["first_seal_time"].apply(time_to_seconds)
    df = _apply_execution_profile(df)

    sentiment_map = {
        "极度活跃": 5,
        "活跃": 4,
        "中性": 3,
        "低迷降温": 2,
        "恐慌冰点": 1,
        "观望低频": 0,
    }
    df["sentiment_num"] = df["sentiment"].map(sentiment_map).fillna(3)

    means = sector_encoding.get("means", {})
    global_mean = sector_encoding.get("global_mean", 0.0)
    if "sector_encoded" in df.columns:
        df["sector_encoded"] = pd.to_numeric(df["sector_encoded"], errors="coerce").fillna(global_mean)
    else:
        df["sector_encoded"] = df["sector"].map(means).fillna(global_mean)

    feature_cols = [
        "price", "change_pct", "turnover", "float_mcap", "seal_funds", "seal_ratio",
        "seal_time_sec", "blown_count", "score", "sh_change", "sz_change", "cy_change",
        "total_turnover", "limit_ups", "limit_downs", "promotion_rate", "sentiment_num",
        "sector_encoded", "execution_slippage_bp", "t1_tradeable", "execution_penalty",
    ]

    return df[feature_cols].copy().fillna(0.0)


def build_expanding_sector_encoding(df):
    """Encode each row using sector outcomes from strictly earlier dates."""
    encoded = pd.Series(index=df.index, dtype=float)
    sector_sums = {}
    sector_counts = {}
    total_sum = 0.0
    total_count = 0

    for date_value in sorted(df["date"].dropna().unique()):
        date_mask = df["date"] == date_value
        prior_global = total_sum / total_count if total_count else 0.5
        for idx, row in df.loc[date_mask].iterrows():
            sector = row["sector"]
            count = sector_counts.get(sector, 0)
            encoded.at[idx] = sector_sums[sector] / count if count else prior_global

        dated_rows = df.loc[date_mask]
        for sector, values in dated_rows.groupby("sector")["target"]:
            sector_sums[sector] = sector_sums.get(sector, 0.0) + float(values.sum())
            sector_counts[sector] = sector_counts.get(sector, 0) + int(values.count())
        total_sum += float(dated_rows["target"].sum())
        total_count += int(dated_rows["target"].count())

    global_mean = float(df["target"].mean()) if not df.empty else 0.5
    inference_encoding = {
        "means": df.groupby("sector")["target"].mean().to_dict(),
        "global_mean": global_mean,
    }
    return encoded.fillna(global_mean), inference_encoding


def _new_promotion_model():
    return RandomForestClassifier(
        n_estimators=150,
        max_depth=6,
        min_samples_leaf=2,
        random_state=42,
    )


def build_training_sector_encoding(y, sectors, train_mask):
    """Fit inference-style sector means on training rows only."""
    frame = pd.DataFrame(
        {
            "target": list(y),
            "sector": list(sectors),
            "is_train": list(train_mask),
        },
        index=y.index,
    )
    training = frame[frame["is_train"]]
    return {
        "means": training.groupby("sector")["target"].mean().to_dict(),
        "global_mean": float(training["target"].mean()) if not training.empty else 0.5,
    }


def evaluate_temporal_holdout(X, y, dates, sectors=None, holdout_fraction=0.2):
    """Evaluate on the latest trading dates without using them for fitting."""
    date_series = pd.Series(list(dates), index=X.index).astype(str)
    unique_dates = sorted(date_series.unique())
    holdout_days = max(1, int(np.ceil(len(unique_dates) * holdout_fraction)))
    split_at = max(1, len(unique_dates) - holdout_days)
    train_dates = unique_dates[:split_at]
    holdout_dates = unique_dates[split_at:]
    train_mask = date_series.isin(train_dates)
    holdout_mask = date_series.isin(holdout_dates)

    metrics = {
        "model_version": MODEL_VERSION,
        "status": "insufficient_data",
        "train_start": train_dates[0] if train_dates else None,
        "train_end": train_dates[-1] if train_dates else None,
        "train_samples": int(train_mask.sum()),
        "holdout_start": holdout_dates[0] if holdout_dates else None,
        "holdout_end": holdout_dates[-1] if holdout_dates else None,
        "holdout_samples": int(holdout_mask.sum()),
        "accuracy": None,
        "roc_auc": None,
    }
    y_train = y.loc[train_mask]
    y_holdout = y.loc[holdout_mask]
    if y_train.nunique() < 2 or y_holdout.empty:
        return metrics

    X_holdout = X.loc[holdout_mask].copy()
    if sectors is not None and "sector_encoded" in X_holdout.columns:
        sector_series = pd.Series(list(sectors), index=X.index)
        encoding = build_training_sector_encoding(y, sector_series, train_mask)
        X_holdout["sector_encoded"] = (
            sector_series.loc[holdout_mask]
            .map(encoding["means"])
            .fillna(encoding["global_mean"])
        )

    model = _new_promotion_model()
    model.fit(X.loc[train_mask], y_train)
    predictions = model.predict(X_holdout)
    probabilities = model.predict_proba(X_holdout)[:, list(model.classes_).index(1)]
    metrics["status"] = "evaluated"
    metrics["accuracy"] = float(accuracy_score(y_holdout, predictions))
    if y_holdout.nunique() >= 2:
        metrics["roc_auc"] = float(roc_auc_score(y_holdout, probabilities))
    return metrics


def persist_model_run(conn, date_str, metrics):
    """Upsert the model lineage and temporal holdout metrics for a recap run."""
    conn.execute(
        """
        INSERT OR REPLACE INTO model_runs (
            date, model_version, status, train_start, train_end, train_samples,
            holdout_start, holdout_end, holdout_samples, accuracy, roc_auc, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            date_str,
            metrics.get("model_version", MODEL_VERSION),
            metrics.get("status", "insufficient_data"),
            metrics.get("train_start"),
            metrics.get("train_end"),
            int(metrics.get("train_samples", 0)),
            metrics.get("holdout_start"),
            metrics.get("holdout_end"),
            int(metrics.get("holdout_samples", 0)),
            metrics.get("accuracy"),
            metrics.get("roc_auc"),
            now_shanghai().isoformat(timespec="seconds"),
        ),
    )



def get_training_features(db_path, date_str):
    """Query historical candidate_observations + decisions prior to date_str."""
    conn = db_connect(db_path, read_only=True)
    try:
        df_cands = pd.read_sql_query(
            """
            SELECT
                o.trade_date AS date,
                o.code,
                o.price_yuan AS price,
                o.change_pct,
                o.turnover_pct AS turnover,
                o.float_mcap_yuan AS float_mcap,
                o.seal_funds_yuan AS seal_funds,
                CASE WHEN o.float_mcap_yuan > 0
                     THEN (o.seal_funds_yuan / o.float_mcap_yuan) * 100
                     ELSE 0 END AS seal_ratio,
                o.first_seal_time,
                o.blown_count,
                COALESCE(d.base_score, 0) AS score,
                o.sector,
                m.sh_change, m.sz_change, m.cy_change, m.total_turnover,
                m.limit_ups, m.limit_downs, m.promotion_rate, m.sentiment,
                o.label_next_2board AS target
            FROM candidate_observations o
            LEFT JOIN candidate_decisions d
                   ON d.trade_date = o.trade_date
                  AND d.code = o.code
                  AND d.rule_version = o.rule_version
            JOIN market_recap m ON o.trade_date = m.date
            WHERE o.trade_date < ? AND o.consecutive_boards = 1
              AND o.label_next_2board IS NOT NULL
            ORDER BY o.trade_date ASC, o.code ASC
            """,
            conn,
            params=(date_str,),
        )
    finally:
        conn.close()

    if df_cands.empty:
        return pd.DataFrame(), pd.Series(dtype=int), {}

    df_cands["target"] = pd.to_numeric(df_cands["target"], errors="coerce").astype(int)
    df_cands["sector_encoded"], sector_encoding = build_expanding_sector_encoding(df_cands)

    X_train = preprocess_features(df_cands, sector_encoding)
    X_train.attrs["training_dates"] = df_cands["date"].tolist()
    X_train.attrs["training_sectors"] = df_cands["sector"].tolist()
    y_train = df_cands["target"].astype(int)
    return X_train, y_train, sector_encoding

def get_index_recap(date_str):
    """Retrieve close prices and daily change % of A-share major indices and total turnover.

    适配器返回 FetchResult(方案 7.1);此处解包为旧消费方期望的 dict。
    指数失败不再写成 0(方案 7.4.7);缺失的指数键不写入。
    """
    result = ADAPTER.get_index_recap(date_str)
    return _index_fetchresult_to_legacy_dict(result)


def get_index_recap_fetchresult(date_str):
    """返回原始 FetchResult,供 publish_gate 评估使用。"""
    return ADAPTER.get_index_recap(date_str)

def fetch_ths_reasons(date_str):
    """Fetch limit-up reason tags using the current data adapter"""
    return ADAPTER.get_concept_reasons(date_str)

def fetch_northbound_flow(date_str=None):
    """Fetch northbound minute-by-minute flow using the current data adapter"""
    if date_str is None:
        date_str = now_shanghai().strftime('%Y-%m-%d')
    return ADAPTER.get_northbound_flow(date_str)

def generate_playbook(row, sector_count, is_one_word):
    """Generate detailed momentum trading playbooks based on stock metrics."""
    from scorer import generate_playbook as _gp

    sector = row.get("sector", "")
    time_str = row.get("first_seal_time", "")
    blown = int(row.get("blown_count", 0) or 0)
    turnover = float(row.get("turnover_pct", 0.0) or 0.0)
    score = int(row.get("relay_score", 0) or 0)
    return _gp(
        sector=sector,
        time_str=time_str,
        blown=blown,
        turnover=turnover,
        score=score,
        sector_limit_ups=sector_count,
    )

def check_uzi_project():
    """
    Detect a local UZI-Skill checkout.
    External cloning and .env importing are disabled to avoid side effects.
    Returns: ("offline", uzi_path).
    """
    uzi_path = os.path.abspath(os.path.join(BASE_DIR, "..", "UZI-Skill"))
    run_script = os.path.join(uzi_path, "run.py")

    if not os.path.exists(run_script):
        print(f"UZI-Skill project not found at {uzi_path}. Using local emulator only.")
    return "offline", uzi_path














def _upsert_uzi_audit(cursor, date_str, code, name, average_score, val_vote, mom_vote, risk_level, summary, report_path, analysis_json):
    cursor.execute(
        """
        UPDATE uzi_audit
           SET name = ?,
               average_score = ?,
               val_vote = ?,
               mom_vote = ?,
               risk_level = ?,
               summary = ?,
               report_path = ?,
               analysis_json = ?
         WHERE date = ? AND code = ?
        """,
        (name, average_score, val_vote, mom_vote, risk_level, summary, report_path, analysis_json, date_str, code),
    )
    if cursor.rowcount == 0:
        cursor.execute(
            """
            INSERT INTO uzi_audit (
                date, code, name, average_score, val_vote, mom_vote, risk_level,
                summary, report_path, analysis_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (date_str, code, name, average_score, val_vote, mom_vote, risk_level, summary, report_path, analysis_json),
        )


def _load_shared_ai_settings():
    """Load AI gateway settings with this repo's env vars taking priority.

    Resolution order:
      1. AI_* env vars (this repo, self-managed). If AI_API_KEY is set, env is
         treated as the source of truth and the vendored panel is never imported.
      2. Fallback to the vendored tickflow-stock-panel secret store (panel UI),
         so existing deployments that store credentials there keep working.
      3. Empty api_key everywhere -> the caller falls back to the local
         rule-based UZI emulator (see run_real_uzi_audit).

    AI_BASE_URL / AI_MODEL intentionally have no usable default: they must be
    set via env (see .env.example); an empty api_key routes to the local rules.
    """
    defaults = {
        "provider": os.getenv("AI_PROVIDER", "openai_compat"),
        "base_url": os.getenv("AI_BASE_URL", ""),
        "api_key": os.getenv("AI_API_KEY", ""),
        "model": os.getenv("AI_MODEL", ""),
        "user_agent": os.getenv(
            "AI_USER_AGENT",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        ),
    }

    if defaults["api_key"]:
        return defaults

    try:
        backend_root = Path(BASE_DIR) / "vendor" / "tickflow-stock-panel" / "backend"
        if backend_root.exists() and str(backend_root) not in sys.path:
            sys.path.insert(0, str(backend_root))
        from app import secrets_store
        from app.config import settings as tf_settings

        vendor_key = secrets_store.get_ai_key() or tf_settings.ai_api_key or ""
        if not vendor_key:
            return defaults
        return {
            "provider": secrets_store.get_ai_config("ai_provider", tf_settings.ai_provider) or defaults["provider"],
            "base_url": secrets_store.get_ai_config("ai_base_url", tf_settings.ai_base_url) or defaults["base_url"],
            "api_key": vendor_key,
            "model": secrets_store.get_ai_config("ai_model", tf_settings.ai_model) or defaults["model"],
            "user_agent": secrets_store.get_ai_config("ai_user_agent", tf_settings.ai_user_agent) or defaults["user_agent"],
        }
    except Exception:
        return defaults

def _parse_uzi_json(content):
    text = str(content or "").strip()
    if not text:
        raise ValueError("empty AI response")
    if text.startswith("```"):
        text = text.split("```", 2)[1] if text.count("```") >= 2 else text
        text = text.replace("json\n", "", 1).strip()
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("AI response is not a JSON object")
    return payload

def _call_uzi_audit_model(prompt_payload):
    global OpenAI
    ai = _load_shared_ai_settings()
    if not ai["api_key"]:
        raise RuntimeError("AI API Key 未配置")

    if OpenAI is None:
        from openai import OpenAI as _OpenAI
        OpenAI = _OpenAI

    client = OpenAI(
        api_key=ai["api_key"],
        base_url=ai["base_url"] or None,
        timeout=180.0,
        max_retries=1,
        default_headers={"User-Agent": ai["user_agent"]},
    )
    system_prompt = (
        "你是A股盘后 UZI 智能评委席。只能输出一个 JSON object，不能输出 markdown、代码块或额外解释。"
        "必须包含 average_score, val_vote, mom_vote, risk_level, summary, analysis 六个顶层字段。"
        "val_vote 与 mom_vote 只能是 多头/空头/观望；risk_level 只能是 安全/危险/极度危险。"
        "summary 必须是 3 行，分别以【巴菲特价值席位】、【赵老哥游资席位】、【大空头排雷席位】开头。"
        "analysis 必须包含 core_conclusion, highlights, gaps_preview, coverage。"
    )
    resp = client.chat.completions.create(
        model=ai["model"],
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(prompt_payload, ensure_ascii=False, separators=(",", ":"))},
        ],
        temperature=0.2,
        max_tokens=2500,
        response_format={"type": "json_object"},
    )
    content = ""
    if getattr(resp, "choices", None):
        first = resp.choices[0]
        message = getattr(first, "message", None)
        content = getattr(message, "content", "") or ""
    return _parse_uzi_json(content)


def _load_lhb_maps(date_str: str) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """Load LHB statistics and detail maps keyed by 6-digit code.

    Both maps are built from the same 30-day window. Network or parse errors
    return empty dicts so the caller never has to handle exceptions.
    """
    stat_map: dict[str, dict[str, Any]] = {}
    detail_map: dict[str, dict[str, Any]] = {}
    try:
        df = ADAPTER.get_lhb_statistics()
        if df is not None and not df.empty:
            df = df.copy()
            if "code" in df.columns:
                df["code"] = df["code"].astype(str).str.zfill(6)
                stat_map = {row["code"]: row for row in df.to_dict("records")}
    except Exception:
        pass

    try:
        end_date = date_str.replace("-", "")
        start_date = (datetime.strptime(date_str, "%Y-%m-%d") - timedelta(days=30)).strftime("%Y%m%d")
        df = ADAPTER.get_lhb_details(start_date=start_date, end_date=end_date)
        if df is not None and not df.empty:
            df = df.copy()
            if "code" in df.columns:
                df["code"] = df["code"].astype(str).str.zfill(6)
            if "list_date" in df.columns:
                df = df.sort_values(["list_date", "net_buy_yuan"], ascending=[False, False])
            for row in df.to_dict("records"):
                if "code" in row:
                    detail_map.setdefault(row["code"], row)
    except Exception:
        pass

    return stat_map, detail_map


def run_local_uzi_emulator(conn, date_str, candidates, sector_counts):
    """Run local rule-based financial emulator for Top 5 candidates"""
    cursor = conn.cursor()
    comment_map = {}
    try:
        comment_df = ADAPTER.get_stock_comments()
        if comment_df is not None and not comment_df.empty:
            comment_df = comment_df.copy()
            if "code" in comment_df.columns:
                comment_df["code"] = comment_df["code"].astype(str).str.zfill(6)
                comment_map = {row["code"]: row for row in comment_df.to_dict("records")}
    except Exception:
        comment_map = {}

    lhb_stat_map, lhb_detail_map = _load_lhb_maps(date_str)

    results = []
    market = get_index_recap(date_str)
    for c in candidates:
        code = c["code"]
        name = c["name"]
        sector = c["sector"]
        sector_count = sector_counts.get(sector, 1)

        val_score = 50
        mom_score = 50

        roe_val = 0.0
        eps_val = 0.0
        finance_dict = {}
        try:
            finance_dict = ADAPTER.get_finance_data(code)
            if finance_dict:
                jinglirun = _safe_float(finance_dict.get("jinglirun")) or 0.0
                jingzichan = _safe_float(finance_dict.get("jingzichan")) or 0.0
                zongguben = _safe_float(finance_dict.get("zongguben")) or 0.0
                roe_val = (jinglirun / jingzichan) * 100 if jingzichan else 0.0
                eps_val = jinglirun / zongguben if zongguben else 0.0
        except Exception:
            finance_dict = {}

        if roe_val >= 15.0:
            val_score += 30
        elif roe_val >= 8.0:
            val_score += 15
        elif roe_val < 0.0:
            val_score -= 20

        if eps_val >= 0.5:
            val_score += 20
        elif eps_val < 0.0:
            val_score -= 15

        if sector_count >= 5:
            mom_score += 30
        elif sector_count >= 3:
            mom_score += 15

        seal_sec = time_to_seconds(c["first_seal_time"])
        if seal_sec <= 600:
            mom_score += 20
        elif seal_sec <= 3900:
            mom_score += 10

        turnover = float(c["turnover_pct"])
        if 4.0 <= turnover <= 12.0:
            mom_score += 10

        trap_info = _evaluate_finance_trap(name, finance_dict)
        risk_level = trap_info["risk_level"]

        val_score = max(0, min(100, val_score))
        mom_score = max(0, min(100, mom_score))
        avg_score = (val_score + mom_score) / 2
        val_vote = "多头" if val_score >= 75 else ("空头" if val_score < 45 else "观望")
        mom_vote = "多头" if mom_score >= 80 else ("空头" if mom_score < 50 else "观望")

        candidate_payload = dict(c)
        candidate_payload["sector_count"] = sector_count
        candidate_payload["val_score"] = val_score
        candidate_payload["mom_score"] = mom_score
        candidate_payload["risk_level"] = risk_level
        candidate_payload["risk_flags"] = trap_info["risk_flags"]
        candidate_payload["risk_notes"] = trap_info["risk_notes"]
        candidate_payload["asset_liability_ratio"] = trap_info["asset_liability_ratio"]
        candidate_payload["goodwill_ratio"] = trap_info["goodwill_ratio"]
        candidate_payload["receivable_ratio"] = trap_info["receivable_ratio"]

        analysis_payload = build_uzi_analysis_payload(
            candidate_payload,
            market=market,
            finance=finance_dict,
            comment=comment_map.get(code),
            lhb_stat=lhb_stat_map.get(code),
            lhb_detail=lhb_detail_map.get(code),
        )
        analysis_json = json.dumps(analysis_payload, ensure_ascii=False, separators=(",", ":"))
        trap_note_text = "；".join(trap_info["risk_notes"]) if trap_info["risk_notes"] else "当前财务排雷未触发明确红线"
        summary = (
            f"【巴菲特价值席位】根据本地财务快照，该股中报ROE表现一般，价值评分为 {val_score}分，表决为：{val_vote}。"
            f"【赵老哥游资席位】日内换手合理，板块个股今日涨停 {sector_count}只，游资评分为 {mom_score}分，表决为：{mom_vote}。"
            f"【大空头排雷席位】{trap_note_text}，排雷评级为：{risk_level}。"
            f"【结构化覆盖】{analysis_payload['coverage']['label']}。"
        )

        _upsert_uzi_audit(
            cursor,
            date_str,
            code,
            name,
            round(avg_score, 1),
            val_vote,
            mom_vote,
            risk_level,
            summary,
            "",
            analysis_json,
        )
        results.append({
            "code": code,
            "name": name,
            "average_score": round(avg_score, 1),
            "val_vote": val_vote,
            "mom_vote": mom_vote,
            "risk_level": risk_level,
            "summary": summary,
            "report_path": "",
        })

    conn.commit()
    return results

def run_real_uzi_audit(conn, date_str, candidates, uzi_path):
    """Run UZI audit using shared AI config, fallback to local rules on failure."""
    sector_counts = {}
    for c in candidates:
        sector = c.get("sector", "")
        sector_counts[sector] = sector_counts.get(sector, 0) + 1

    prompt_payload = {
        "date": date_str,
        "candidates": candidates,
        "model_intent": "A股盘后 UZI 智能评委席，输出 JSON object 列表",
        "format": {
            "results": [
                {
                    "code": "600519",
                    "name": "贵州茅台",
                    "average_score": 85.0,
                    "val_vote": "多头",
                    "mom_vote": "观望",
                    "risk_level": "安全",
                    "summary": "3行，分别以【巴菲特价值席位】、【赵老哥游资席位】、【大空头排雷席位】开头",
                    "analysis": {
                        "core_conclusion": "...",
                        "highlights": [{"label": "", "value": ""}],
                        "gaps_preview": ["..."],
                        "coverage": {"filled": 0, "total": 0, "label": "0/0"},
                    },
                    "report_path": "",
                }
            ]
        },
        "constraints": [
            "只能输出 JSON object",
            "必须包含 results 数组，数组元素按候选股逐条返回",
            "val_vote/mom_vote 只能是 多头/空头/观望",
            "risk_level 只能是 安全/危险/极度危险",
        ],
    }

    try:
        ai = _load_shared_ai_settings()
        if not ai["api_key"]:
            raise RuntimeError("AI API Key 未配置")
        # Release any caller-held SQLite writer lock before external I/O.
        conn.commit()
        ai_result = _call_uzi_audit_model(prompt_payload)

        records = []
        if isinstance(ai_result, dict):
            if isinstance(ai_result.get("results"), list):
                records = [item for item in ai_result["results"] if isinstance(item, dict)]
            elif any(k in ai_result for k in ("average_score", "val_vote", "mom_vote", "risk_level", "summary", "analysis")):
                records = [ai_result]
        if not records:
            raise RuntimeError("AI response missing results")

        cursor = conn.cursor()
        results = []
        for idx, item in enumerate(records):
            base = candidates[idx] if idx < len(candidates) else {}
            code = str(item.get("code") or base.get("code", "")).zfill(6)
            name = str(item.get("name") or base.get("name", ""))
            avg = float(item.get("average_score", 0.0) or 0.0)
            val_vote = str(item.get("val_vote", "观望"))
            mom_vote = str(item.get("mom_vote", "观望"))
            risk_level = str(item.get("risk_level", "安全"))
            summary = str(item.get("summary", ""))
            report_path = str(item.get("report_path", "") or "")
            analysis = item.get("analysis")
            if not isinstance(analysis, dict):
                analysis = {}
            analysis_json = json.dumps(analysis, ensure_ascii=False, separators=(",", ":"))
            _upsert_uzi_audit(cursor, date_str, code, name, avg, val_vote, mom_vote, risk_level, summary, report_path, analysis_json)
            results.append({
                "code": code,
                "name": name,
                "average_score": avg,
                "val_vote": val_vote,
                "mom_vote": mom_vote,
                "risk_level": risk_level,
                "summary": summary,
                "report_path": report_path,
            })
        conn.commit()
        return results
    except Exception as e:
        print(f"[UZI Audit] AI path failed, falling back to local rules: {e}")
        return run_local_uzi_emulator(conn, date_str, candidates, sector_counts)
def _build_uzi_candidates(df_1b: pd.DataFrame, ranked: list[Any]) -> list[dict[str, Any]]:
    """Only keep published Top5 rows for UZI audit."""
    df_by_code = df_1b.set_index("code", drop=False)
    cands_for_audit: list[dict[str, Any]] = []
    for d in ranked:
        if getattr(d.publication_status, "value", d.publication_status) != "PUBLISHED_TOP5":
            continue
        if d.code not in df_by_code.index:
            continue
        row = df_by_code.loc[d.code]
        if isinstance(row, pd.DataFrame):
            row = row.iloc[0]
        raw_time = str(row["first_seal_time"])
        first_seal_time = f"{raw_time[:2]}:{raw_time[2:4]}:{raw_time[4:]}" if len(raw_time) == 6 else raw_time
        cands_for_audit.append(
            {
                "code": row["code"],
                "name": row["name"],
                "first_seal_time": first_seal_time,
                "turnover_pct": float(row["turnover_pct"]),
                "sector": row["sector"],
            }
        )
    return cands_for_audit


def run_recap(date_str, trade_dates, observation_only=False):
    """Execute recap for a specific trading day."""
    from contracts import FetchResult, validate_limit_up_pool
    from execution_policy import ExecutionAction
    from publish_gate import evaluate_publishable
    from rule_contract import PositionPolicy, PublicationStatus, load_rule_config
    from trading_calendar import CalendarConflict

    def _normalize_time(value):
        text = str(value or "").strip()
        if not text:
            return ""
        if ":" in text and len(text) == 8:
            return text
        digits = "".join(ch for ch in text if ch.isdigit())
        if not digits:
            return text
        digits = digits.zfill(6)[-6:]
        return f"{digits[:2]}:{digits[2:4]}:{digits[4:]}"

    run_id = f"recap-{date_str}-{uuid.uuid4().hex[:12]}"
    schema_version = current_schema_version(DB_PATH)
    try:
        calendar_source = json.dumps(calendar_metadata(), ensure_ascii=False)
    except Exception:
        calendar_source = "{}"
    record_run_start(
        DB_PATH,
        run_id=run_id,
        trade_date=date_str,
        run_type="OBSERVATION_ONLY" if observation_only else "RECAP",
        schema_version=schema_version,
        calendar_source=calendar_source,
    )

    def _complete(status: str, publishable: bool, failure_code: str | None = None, failure_message: str | None = None):
        record_run_completion(
            DB_PATH,
            run_id=run_id,
            status=status,
            publishable=publishable,
            failure_code=failure_code,
            failure_message=failure_message,
        )

    try:
        snapshot = {}
        try:
            snapshot = _load_realtime_snapshot_from_db(DB_PATH)
            if snapshot:
                print(f"Loaded {len(snapshot)} records from realtime_snapshot (intraday cache)")
        except Exception:
            snapshot = {}

        idx_fetch = get_index_recap_fetchresult(date_str)
        idx_recap = _index_fetchresult_to_legacy_dict(idx_fetch)

        print("Fetching limit-up pool...")
        try:
            pool_fetch = ADAPTER.get_limit_up_pool(date_str)
            print(f"Total limit-up stocks: {pool_fetch.row_count}")
        except Exception as e:
            print(f"Failed to fetch limit-up pool for {date_str}: {e}")
            pool_fetch = FetchResult.unavailable(
                dataset_name="limit_up_pool",
                provider="akshare",
                requested_trade_date=date_str,
                error_code="FETCH_FAILED",
                error_message=str(e),
                schema_version=1,
            )
        df_pool = pool_fetch.payload.copy()
        if pool_fetch.is_ok and not df_pool.empty:
            valid, error = validate_limit_up_pool(df_pool)
            if not valid:
                pool_fetch = FetchResult.invalid(
                    dataset_name="limit_up_pool",
                    provider="akshare",
                    requested_trade_date=date_str,
                    error_message=error or "limit_up_pool invalid",
                    schema_version=1,
                    payload=df_pool,
                )

        print("Fetching limit-down pool...")
        limit_downs = 0
        try:
            df_dt = ADAPTER.get_limit_down_pool(date_str)
            limit_downs = len(df_dt)
            print(f"Total limit-down stocks: {limit_downs}")
        except Exception as e:
            print(f"Failed to fetch limit-down pool for {date_str}: {e}")

        print("Fetching THS concept reasons...")
        ths_reasons = fetch_ths_reasons(date_str)
        if not isinstance(ths_reasons, dict):
            ths_reasons = {}

        if not df_pool.empty:
            df_pool = df_pool.copy()
            df_pool["code"] = df_pool["code"].astype(str).str.zfill(6)
            if "concept" not in df_pool.columns:
                df_pool["concept"] = ""
            df_pool["concept"] = df_pool["code"].map(ths_reasons).fillna(df_pool["concept"]).fillna("")
            if snapshot:
                df_pool = _apply_realtime_snapshot(df_pool, snapshot)
            sector_counts = df_pool["sector"].value_counts().to_dict()
            df_1b = df_pool[df_pool["consecutive_boards"] == 1].copy().reset_index(drop=True)
        else:
            sector_counts = {}
            df_1b = pd.DataFrame()

        try:
            assert_corroborates(date_str, trade_dates or None)
        except CalendarConflict as exc:
            if observation_only:
                print(f"[calendar] WARNING for {date_str}: {exc} (observation-only, continuing)")
            else:
                _complete("BLOCKED", False, exc.reason_code, str(exc))
                print(f"[calendar] BLOCKED for {date_str}: {exc}")
                return False

        cfg = load_rule_config()
        gate = evaluate_publishable(
            date_str,
            is_trading_day=calendar_is_trading_day(date_str),
            sources={"limit_up_pool": pool_fetch, "index_recap": idx_fetch},
            config_valid=True,
            migration_ok=True,
            decision_exception=False,
        )

        record_source_snapshot(
            DB_PATH,
            run_id=run_id,
            dataset_name="limit_up_pool",
            provider=pool_fetch.provider,
            as_of=pool_fetch.as_of,
            fetched_at=pool_fetch.fetched_at,
            status=pool_fetch.status.value,
            row_count=pool_fetch.row_count,
            schema_version=pool_fetch.schema_version,
            error=pool_fetch.error_message,
        )
        record_source_snapshot(
            DB_PATH,
            run_id=run_id,
            dataset_name="index_recap",
            provider=idx_fetch.provider,
            as_of=idx_fetch.as_of,
            fetched_at=idx_fetch.fetched_at,
            status=idx_fetch.status.value,
            row_count=idx_fetch.row_count,
            schema_version=idx_fetch.schema_version,
            error=idx_fetch.error_message,
        )

        if not gate.publishable and not observation_only:
            print(f"[publish_gate] BLOCKED for {date_str}: {gate.reason_codes}")
            print(f"[publish_gate] warnings: {gate.warnings}")
            _complete("BLOCKED", False, gate.reason_codes[0] if gate.reason_codes else "PUBLISH_GATE", json.dumps(gate.warnings, ensure_ascii=False))
            return False

        from scorer import compute_relay_score, generate_playbook

        if not df_1b.empty:
            df_1b["relay_score"] = df_1b.apply(
                lambda r: compute_relay_score(
                    {
                        "first_seal_time": r["first_seal_time"],
                        "blown_count": r["blown_count"],
                        "float_mcap": r["float_mcap_yuan"],
                        "seal_funds": r["seal_funds_yuan"],
                        "turnover": r["turnover_pct"],
                    },
                    sector_counts.get(r["sector"], 1),
                ),
                axis=1,
            ).astype(int)
            df_1b["playbook"] = df_1b.apply(
                lambda r: generate_playbook(
                    sector=r["sector"],
                    time_str=r["first_seal_time"],
                    blown=int(r["blown_count"]),
                    turnover=float(r["turnover_pct"]),
                    score=int(r["relay_score"]),
                    sector_limit_ups=sector_counts.get(r["sector"], 1),
                ),
                axis=1,
            )
        sorted_sectors = sorted(sector_counts.items(), key=lambda x: x[1], reverse=True)
        sector_ranking_list = []
        for sec_name, count in sorted_sectors[:10]:
            leader_name = "无"
            df_sec = df_pool[df_pool["sector"] == sec_name] if not df_pool.empty else pd.DataFrame()
            if not df_sec.empty:
                df_sec_sorted = df_sec.sort_values(by=["consecutive_boards", "first_seal_time"], ascending=[False, True])
                leader_name = df_sec_sorted.iloc[0]["name"]
            sector_ranking_list.append({"name": sec_name, "count": count, "leader": leader_name})
        sector_ranking_json = json.dumps(sector_ranking_list, ensure_ascii=False)

        promotion_rate = 0.0
        prev_date = get_previous_trading_day(date_str, trade_dates)
        if prev_date:
            print(f"Previous trading day is {prev_date}. Calculating promotion rate...")
            conn = db_connect(DB_PATH, read_only=True)
            try:
                prev_candidates = [
                    row[0]
                    for row in conn.execute(
                        "SELECT code FROM candidate_observations WHERE trade_date = ? AND consecutive_boards = 1",
                        (prev_date,),
                    ).fetchall()
                ]
            finally:
                conn.close()
            if prev_candidates:
                df_2b = df_pool[df_pool["consecutive_boards"] == 2] if not df_pool.empty else pd.DataFrame()
                today_2b_codes = set(df_2b["code"].tolist()) if not df_2b.empty else set()
                successful_promotions = set(prev_candidates).intersection(today_2b_codes)
                promotion_rate = (len(successful_promotions) / len(prev_candidates)) * 100
                conn = db_connect(DB_PATH)
                try:
                    for code in prev_candidates:
                        conn.execute(
                            "UPDATE candidate_observations SET label_next_2board = ? WHERE trade_date = ? AND code = ?",
                            (1 if code in successful_promotions else 0, prev_date, code),
                        )
                    conn.commit()
                finally:
                    conn.close()
                print(f"Yesterday 1-board count: {len(prev_candidates)}")
                print(f"Today 2-board count: {len(df_2b)}")
                print(f"Successful promotions: {len(successful_promotions)} ({promotion_rate:.2f}%)")
            else:
                print("No candidates stored for yesterday in the database. Can't calculate promotion rate yet.")
        else:
            print("No previous trading day found. Promotion rate set to 0.0.")

        hgt_flow, sgt_flow = None, None
        if date_str == now_shanghai().strftime("%Y-%m-%d"):
            print("Fetching realtime northbound capital flow...")
            hgt_flow, sgt_flow = fetch_northbound_flow(date_str)
            print(f"Northbound Flow - HGT: {hgt_flow:.2f}亿, SGT: {sgt_flow:.2f}亿")

        total_lu = int(len(df_pool))
        sentiment_label = "中性"
        if total_lu >= 110 and limit_downs <= 5:
            sentiment_label = "极度活跃"
        elif total_lu >= 80 and limit_downs <= 10:
            sentiment_label = "活跃"
        elif limit_downs >= 25:
            sentiment_label = "恐慌冰点"
        elif limit_downs >= 12 and total_lu < 50:
            sentiment_label = "低迷降温"
        elif total_lu <= 40:
            sentiment_label = "观望低频"
        market_recap_row = {
            "date": date_str,
            "sh_price": idx_recap.get("sh", {}).get("price"),
            "sh_change": idx_recap.get("sh", {}).get("change"),
            "sz_price": idx_recap.get("sz", {}).get("price"),
            "sz_change": idx_recap.get("sz", {}).get("change"),
            "cy_price": idx_recap.get("cy", {}).get("price"),
            "cy_change": idx_recap.get("cy", {}).get("change"),
            "total_turnover": idx_recap.get("total_turnover"),
            "limit_ups": total_lu,
            "limit_downs": limit_downs,
            "promotion_rate": round(promotion_rate, 2),
            "hgt_flow": hgt_flow,
            "sgt_flow": sgt_flow,
            "sentiment": sentiment_label,
            "sector_ranking": sector_ranking_json,
        }

        # 发布产物(market_recap / limit_ups_archive)只在可发布时写入;
        # observation-only 回放时跳过,避免非交易日留下"有市场、无候选"
        # 的半写脏记录(AGENTS.md:禁止把缺失数据填成看似有效的 0 后发布)。
        # candidate_observations(全量首板观察样本)仍写入,供 ML 训练,
        # 与 Top5 发布表分开保存(AGENTS.md 不可破坏约束)。
        if not observation_only:
            persist_limit_up_archive(DB_PATH, date_str, df_pool.to_dict("records") if not df_pool.empty else [])
            persist_market_recap(DB_PATH, market_recap_row)
        for _, row in df_1b.iterrows() if not df_1b.empty else []:
            persist_observation(
                DB_PATH,
                {
                    "trade_date": date_str,
                    "code": str(row["code"]).zfill(6),
                    "name": str(row["name"]),
                    "price": float(row["price"]),
                    "change_pct": float(row["change_pct"]),
                    "turnover_pct": float(row["turnover_pct"]),
                    "float_mcap_yuan": float(row["float_mcap_yuan"]),
                    "seal_funds_yuan": float(row["seal_funds_yuan"]),
                    "first_seal_time": _normalize_time(row["first_seal_time"]),
                    "blown_count": int(row["blown_count"]),
                    "consecutive_boards": int(row["consecutive_boards"]),
                    "is_st": bool(row["is_st"]) if "is_st" in row else ("ST" in str(row["name"]) or "退市" in str(row["name"])),
                    "sector": str(row["sector"]),
                    "concept": str(row.get("concept", "")),
                },
            )
        if observation_only:
            _complete("BLOCKED", False, "TRADING_DAY_INVALID", "observation-only replay")
            print(f"[gate] {date_str} observation-only mode: observations written, publishing skipped.")
            return False

        current_max_boards = int(pd.to_numeric(df_pool["consecutive_boards"], errors="coerce").fillna(0).max()) if not df_pool.empty else 0
        prev_one_board_codes: list[str] = []
        prev_two_boards_codes: list[str] = []
        today_two_boards_codes: list[str] = df_pool.loc[df_pool["consecutive_boards"] == 2, "code"].tolist() if not df_pool.empty else []
        today_three_boards_codes: list[str] = df_pool.loc[df_pool["consecutive_boards"] == 3, "code"].tolist() if not df_pool.empty else []
        if prev_date:
            conn = db_connect(DB_PATH, read_only=True)
            try:
                prev_rows = conn.execute(
                    "SELECT code, consecutive_boards FROM limit_ups_archive WHERE date = ?",
                    (prev_date,),
                ).fetchall()
                for code, boards in prev_rows:
                    code = str(code).zfill(6)
                    boards = int(boards or 0)
                    if boards == 1:
                        prev_one_board_codes.append(code)
                    elif boards == 2:
                        prev_two_boards_codes.append(code)
            finally:
                conn.close()
        market_risk = evaluate_market_risk(
            date_str,
            max_consecutive_boards=current_max_boards,
            prev_two_boards_codes=prev_two_boards_codes,
            today_three_boards_codes=today_three_boards_codes,
            prev_one_board_codes=prev_one_board_codes,
            today_two_boards_codes=today_two_boards_codes,
            prev_trade_date=prev_date,
            cfg=cfg,
        )
        persist_market_risk(DB_PATH, market_risk)

        print("Initializing Machine Learning Pipeline...")
        pred_probs = [None] * len(df_1b)
        model_run = None
        try:
            X_train, y_train, sector_encoding = get_training_features(DB_PATH, date_str)
            print(f"[ML Model] Training samples: {len(X_train)}")
            training_dates = X_train.attrs.get("training_dates", [])
            X_fit, y_fit, X_calib, y_calib = split_time_series_calibration(
                X_train,
                y_train,
                training_dates,
                min_calibration_samples=20,
            )

            if len(X_fit) > 0:
                print(f"[ML Model] Fit samples: {len(X_fit)}")
                base_model, calibrated_model, metrics = train_and_calibrate(
                    X_fit,
                    y_fit,
                    X_calib,
                    y_calib,
                    random_seed=42,
                    n_estimators=150,
                    method="sigmoid",
                    min_calibration_samples=20,
                )
                active_model = calibrated_model or base_model

                if X_calib is not None and y_calib is not None and len(X_calib) > 0:
                    calib_proba = active_model.predict_proba(X_calib)
                    positive = calib_proba[:, 1] if calib_proba.shape[1] > 1 else calib_proba[:, 0]
                    accuracy = float(((positive >= 0.5).astype(int) == y_calib.to_numpy()).mean())
                    roc_auc = float(roc_auc_score(y_calib, positive)) if y_calib.nunique() >= 2 else None
                else:
                    accuracy = None
                    roc_auc = None

                model_run = {
                    "model_version": MODEL_VERSION,
                    "status": "calibrated" if metrics.calibrated else "trained",
                    "train_start": training_dates[0] if training_dates else None,
                    "train_end": training_dates[-1] if training_dates else None,
                    "train_samples": len(X_fit),
                    "holdout_start": training_dates[-len(X_calib)] if X_calib is not None and len(X_calib) > 0 else None,
                    "holdout_end": training_dates[-1] if X_calib is not None and len(X_calib) > 0 else None,
                    "holdout_samples": len(X_calib) if X_calib is not None else 0,
                    "accuracy": accuracy,
                    "roc_auc": roc_auc,
                    "brier_score": metrics.brier_score,
                    "log_loss": metrics.log_loss,
                    "pr_auc": metrics.pr_auc,
                    "n_calibration_samples": metrics.n_calibration_samples,
                    "calibrated": metrics.calibrated,
                }
                print(
                    "[ML Model] "
                    f"calibrated={metrics.calibrated} "
                    f"brier={metrics.brier_score} "
                    f"log_loss={metrics.log_loss} "
                    f"roc_auc={metrics.roc_auc} "
                    f"pr_auc={metrics.pr_auc} "
                    f"n_calibration={metrics.n_calibration_samples}"
                )

                if not X_train.empty:
                    feature_importances = pd.Series(base_model.feature_importances_, index=X_train.columns)
                    print("Feature importances ranking:")
                    for feature_name, importance in feature_importances.sort_values(ascending=False).items():
                        print(f"  {feature_name}: {importance:.4f}")

                    df_pred = pd.DataFrame()
                    df_pred["price"] = df_1b["price"].astype(float)
                    df_pred["change_pct"] = df_1b["change_pct"].astype(float)
                    df_pred["turnover"] = df_1b["turnover_pct"].astype(float)
                    raw_mcap = df_1b["float_mcap_yuan"].astype(float)
                    raw_seal = df_1b["seal_funds_yuan"].astype(float)
                    df_pred["float_mcap"] = (raw_mcap / 1e9).round(2)
                    df_pred["seal_funds"] = (raw_seal / 1e6).round(2)
                    df_pred["seal_ratio"] = ((raw_seal / raw_mcap) * 100).where(raw_mcap > 0, 0.0).round(2)
                    df_pred["first_seal_time"] = df_1b["first_seal_time"].astype(str).map(_normalize_time)
                    df_pred["blown_count"] = df_1b["blown_count"].astype(int)
                    df_pred["score"] = df_1b["relay_score"].astype(int)
                    df_pred["sector"] = df_1b["sector"]
                    df_pred["sh_change"] = idx_recap.get("sh", {}).get("change")
                    df_pred["sz_change"] = idx_recap.get("sz", {}).get("change")
                    df_pred["cy_change"] = idx_recap.get("cy", {}).get("change")
                    df_pred["total_turnover"] = idx_recap.get("total_turnover")
                    df_pred["limit_ups"] = total_lu
                    df_pred["limit_downs"] = limit_downs
                    df_pred["promotion_rate"] = promotion_rate
                    df_pred["sentiment"] = sentiment_label

                    X_pred = preprocess_features(df_pred, sector_encoding)
                    probs = active_model.predict_proba(X_pred)
                    positive = probs[:, 1] if probs.shape[1] > 1 else probs[:, 0]
                    pred_probs = [round(float(p), 4) for p in positive]
            else:
                print("[ML Model] Fallback to no predictions (empty training split)")
        except Exception as e:
            print(f"Error in ML Pipeline: {e}")

        history_df = pd.DataFrame()
        conn = db_connect(DB_PATH, read_only=True)
        try:
            history_df = pd.read_sql_query(
                """
                SELECT trade_date AS date, code, blown_count, consecutive_boards, first_seal_time
                  FROM candidate_observations
                 WHERE trade_date < ?
                 ORDER BY trade_date ASC, code ASC
                """,
                conn,
                params=(date_str,),
            )
        finally:
            conn.close()

        def _recent_trade_dates(window: int) -> list[str]:
            recent = [d for d in trade_dates if d <= date_str][-window:]
            if date_str not in recent:
                recent = (recent + [date_str])[-window:]
            return recent

        def _load_recent_limit_ups_by_code(window: int) -> dict[str, list[str]]:
            recent_dates = _recent_trade_dates(window)
            recent_map: dict[str, list[str]] = {}
            if not recent_dates:
                return recent_map
            conn = db_connect(DB_PATH, read_only=True)
            try:
                placeholders = ",".join("?" for _ in recent_dates)
                for trade_day, code in conn.execute(
                    f"SELECT date, code FROM limit_ups_archive WHERE date IN ({placeholders})",
                    tuple(recent_dates),
                ).fetchall():
                    recent_map.setdefault(str(code).zfill(6), []).append(str(trade_day))
            finally:
                conn.close()
            return recent_map

        recent_3d_limit_ups_by_code = _load_recent_limit_ups_by_code(3)
        recent_4d_limit_ups_by_code = _load_recent_limit_ups_by_code(4)

        lhb_stat_map, lhb_detail_map = _load_lhb_maps(date_str)

        decisions = []
        extra_fields_by_code: dict[str, dict[str, Any]] = {}
        score_by_code: dict[str, int] = {}
        name_by_code: dict[str, str] = {}
        current_rows = {str(row["code"]).zfill(6): row for _, row in df_1b.iterrows()}

        for idx, row in df_1b.iterrows():
            code = str(row["code"]).zfill(6)
            name = str(row["name"])
            first_seal_time = _normalize_time(row["first_seal_time"])
            record = {
                "trade_date": date_str,
                "code": code,
                "name": name,
                "price": float(row["price"]),
                "change_pct": float(row["change_pct"]),
                "turnover": float(row["turnover_pct"]),
                "float_mcap_yuan": float(row["float_mcap_yuan"]),
                "seal_funds_yuan": float(row["seal_funds_yuan"]),
                "first_seal_time": first_seal_time,
                "blown_count": int(row["blown_count"]),
                "consecutive_boards": int(row["consecutive_boards"]),
                "sector": str(row["sector"]),
                "concept": str(row.get("concept", "")),
                "score": int(row["relay_score"]),
                "is_st": bool(row["is_st"]) if "is_st" in row else ("ST" in name or "退市" in name),
            }

            lhb_status = "UNKNOWN"
            if code in lhb_stat_map or code in lhb_detail_map:
                lhb_status = "LISTED"
            elif lhb_stat_map or lhb_detail_map:
                lhb_status = "NOT_LISTED"

            decision = evaluate_f19(
                record,
                cfg,
                recent_limit_ups_by_code=recent_3d_limit_ups_by_code,
                lhb_status=lhb_status,
                base_score=record["score"],
                pred_prob=pred_probs[idx] if idx < len(pred_probs) else None,
            )
            shadow_eligible = decision.eligible

            hist = history_df[history_df["code"] == code] if not history_df.empty else pd.DataFrame()
            total_limit_count = int(len(hist))
            blown_total = int(pd.to_numeric(hist["blown_count"], errors="coerce").fillna(0).sum()) if not hist.empty else 0
            max_consecutive = int(pd.to_numeric(hist["consecutive_boards"], errors="coerce").fillna(0).max()) if not hist.empty else 0
            early_count = 0
            if not hist.empty:
                early_cutoff = time_to_seconds("10:00:00")
                early_count = int(
                    hist["first_seal_time"].map(_normalize_time).map(time_to_seconds).fillna(0).lt(early_cutoff).sum()
                )

            lhb_stat = lhb_stat_map.get(code, {})
            lhb_detail = lhb_detail_map.get(code, {})
            lhb_count = _safe_int(_pick(lhb_stat.get("list_count"), lhb_detail.get("list_count"), 0), 0)
            net_buy_yuan = _safe_float(
                _pick(
                    lhb_stat.get("net_buy_yuan"),
                    lhb_detail.get("net_buy_yuan"),
                    0.0,
                )
            ) or 0.0
            has_institution = bool(_safe_int(_pick(lhb_stat.get("inst_buy_count"), lhb_detail.get("inst_buy_count"), 0), 0))

            activity = score_activity(total_limit_count)
            reliability = score_reliability(total_limit_count, blown_total)
            explosiveness = score_explosiveness(max_consecutive)
            capital = score_capital(lhb_count, net_buy_yuan, has_institution=has_institution)
            early_board = score_early_board(early_count, total_limit_count)
            personality_score, personality_grade, personality_warning = compute_personality(
                activity=activity,
                reliability=reliability,
                explosiveness=explosiveness,
                capital=capital,
                early_board=early_board,
                cfg=cfg,
                sample_count=total_limit_count,
            )
            blocked_reason = personality_blocked_reason(personality_grade)
            enforce_f17 = bool(cfg.raw.get("feature_flags", {}).get("enforce_f17", False)) and bool(
                cfg.raw.get("feature_flags", {}).get("personality_enforce", False)
            )
            enforce_f18 = bool(cfg.raw.get("feature_flags", {}).get("enforce_f18", False))
            enforce_f19 = bool(cfg.raw.get("feature_flags", {}).get("enforce_f19", False))
            use_adjusted_score = bool(cfg.raw.get("feature_flags", {}).get("use_adjusted_score", False))
            can_trade = market_risk.f18_policy != PositionPolicy.HALT if enforce_f18 else True
            has_recent_4d_2b = check_recent_4d_2b(code, recent_4d_limit_ups_by_code, int(cfg.raw["f14"]["min_limit_ups"]))
            f14_boosted_score = apply_f14_boost(decision.base_score, has_recent_4d_2b, cfg)
            adjusted_score = compute_adjusted_score(f14_boosted_score, market_risk.one_to_two_multiplier)
            reason_codes = list(decision.reason_codes)
            if blocked_reason:
                reason_codes.append(blocked_reason)

            eligible = shadow_eligible if enforce_f19 else CandidateEligibility.ELIGIBLE
            block_f17 = 1 if blocked_reason else 0
            if blocked_reason and enforce_f17:
                eligible = CandidateEligibility.INELIGIBLE
            if shadow_eligible != CandidateEligibility.ELIGIBLE and enforce_f19:
                eligible = shadow_eligible

            signals = dict(decision.signals)
            signals.update(
                {
                    "rule_version": cfg.rule_version,
                    "eligible": eligible.value,
                    "shadow_eligible": shadow_eligible.value,
                    "market_regime": str(market_risk.market_regime),
                    "one_to_two_rate": market_risk.one_to_two_rate,
                    "two_to_three_rate": market_risk.two_to_three_rate,
                    "f14_recent_4d_2b": has_recent_4d_2b,
                    "f14_boosted_base_score": f14_boosted_score,
                    "f14_score_multiplier": float(cfg.raw["f14"]["score_multiplier"]) if has_recent_4d_2b else 1.0,
                    "f18_policy": str(market_risk.f18_policy),
                    "f18_risk_budget": market_risk.f18_risk_budget,
                    "f18_low_sample": market_risk.f18_low_sample,
                    "adjusted_score": adjusted_score,
                    "personality_score": personality_score,
                    "personality_grade": str(personality_grade),
                    "personality_warning": personality_warning,
                    "can_trade": can_trade,
                    "block_f16": 0,
                    "block_f17": block_f17,
                    "block_f18": 1 if market_risk.f18_policy == PositionPolicy.HALT else 0,
                    "block_f19": 0 if shadow_eligible == CandidateEligibility.ELIGIBLE else 1,
                    "use_adjusted_score": use_adjusted_score,
                    "adjusted_score_shadow": adjusted_score if not use_adjusted_score else None,
                    "lhb_status": lhb_status,
                }
            )

            decision = replace(
                decision,
                eligible=eligible,
                adjusted_score=adjusted_score,
                personality_score=personality_score,
                personality_grade=str(personality_grade),
                reason_codes=reason_codes,
                signals=signals,
            )
            decisions.append(decision)
            score_by_code[code] = decision.base_score
            name_by_code[code] = name
            extra_fields_by_code[code] = {
                "price": round(float(row["price"]), 2),
                "change_pct": round(float(row["change_pct"]), 2),
                "turnover": round(float(row["turnover_pct"]), 2),
                "float_mcap": round(float(row["float_mcap_yuan"]) / 1e9, 2),
                "seal_funds": round(float(row["seal_funds_yuan"]) / 1e6, 2),
                "seal_ratio": round((float(row["seal_funds_yuan"]) / float(row["float_mcap_yuan"]) * 100) if float(row["float_mcap_yuan"]) > 0 else 0.0, 2),
                "first_seal_time": first_seal_time,
                "blown_count": int(row["blown_count"]),
                "sector": str(row["sector"]),
                "concept": str(row.get("concept", "")),
                "playbook": str(row["playbook"]),
                "personality_grade": str(personality_grade),
                "personality_dims": {
                    "activity": activity,
                    "explosiveness": explosiveness,
                    "capital": capital,
                    "early_board": early_board,
                    "sample_count": total_limit_count,
                    "lhb_count": lhb_count,
                    "net_buy_yuan": net_buy_yuan,
                },
                "lhb_gold_net": net_buy_yuan if str(personality_grade) == "S" else None,
                "lhb_death_net": net_buy_yuan if str(personality_grade) in {"C", "D"} else None,
                "lhb_inst_net": net_buy_yuan if has_institution else None,
                "block_f16": 0,
                "block_f17": block_f17,
                "block_f18": 1 if market_risk.f18_policy == PositionPolicy.HALT else 0,
                "block_f19": 0 if shadow_eligible == CandidateEligibility.ELIGIBLE else 1,
            }

        ranked = rank_candidates(decisions, cfg)
        persist_decisions_and_top5(
            DB_PATH,
            ranked,
            score_by_code=score_by_code,
            name_by_code=name_by_code,
            extra_fields_by_code=extra_fields_by_code,
        )

        if model_run is not None:
            conn = db_connect(DB_PATH)
            try:
                persist_model_run(conn, date_str, model_run)
                conn.commit()
            finally:
                conn.close()

        plans = []
        for d in ranked:
            if d.publication_status != PublicationStatus.PUBLISHED_TOP5:
                continue
            row = current_rows.get(d.code)
            if row is None:
                continue
            open_price = float(row["price"])
            previous_close = open_price / (1 + float(row["change_pct"]) / 100) if float(row["change_pct"]) != -100 else None
            effective_f18_policy = market_risk.f18_policy if bool(cfg.raw.get("feature_flags", {}).get("enforce_f18", False)) else None
            buy = buy_plan(
                date_str,
                d.code,
                open_price=open_price,
                previous_close=previous_close,
                rule_version=cfg.rule_version,
                market_regime=market_risk.market_regime,
                f18_policy=effective_f18_policy,
            )
            if buy.action != ExecutionAction.NO_TRADE:
                plans.append(buy)
            plans.extend(
                defensive_sell_plan(
                    date_str,
                    d.code,
                    open_price=open_price,
                    previous_close=previous_close,
                    buy_cost=open_price,
                    rule_version=cfg.rule_version,
                )
            )
            plans.append(
                auction_matrix(
                    date_str,
                    d.code,
                    open_price=open_price,
                    previous_close=previous_close,
                    rule_version=cfg.rule_version,
                )
            )
        if bool(cfg.raw.get("feature_flags", {}).get("publish_execution_plan", False)):
            persist_execution_plans(DB_PATH, plans)

        print("Running UZI Jury Audit...")
        try:
            cands_for_audit = _build_uzi_candidates(df_1b, ranked)
            conn = db_connect(DB_PATH)
            try:
                run_real_uzi_audit(conn, date_str, cands_for_audit, uzi_path="")
                conn.commit()
            finally:
                conn.close()
        except Exception as e:
            print(f"Error during UZI Audit scheduling: {e}")

        _complete("COMPLETED", True)
        print(f"Recap for {date_str} completed successfully!")
        return True
    except Exception as e:
        try:
            _complete("BLOCKED", False, "UNHANDLED_EXCEPTION", str(e))
        except Exception:
            pass
        print(f"Error running recap for {date_str}: {e}")
        return False

def calculate_calibration_stats(conn):
    """Calculate historical promotion rates for score buckets"""
    cursor = conn.cursor()
    try:
        # Check if limit_ups_archive table exists and has data
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='limit_ups_archive'")
        if not cursor.fetchone():
            return []

        df_cands = pd.read_sql_query(
            "SELECT date, code, score FROM candidates WHERE consecutive_boards = 1", conn
        )
        df_promoted = pd.read_sql_query(
            "SELECT date, code FROM limit_ups_archive WHERE consecutive_boards = 2", conn
        )

        if df_cands.empty or df_promoted.empty:
            return []

        # Find next trading day mapping
        dates_sorted = sorted(df_cands["date"].unique())
        date_to_next = {dates_sorted[i]: dates_sorted[i+1] for i in range(len(dates_sorted) - 1)}

        promoted_keys = set(zip(df_promoted["date"], df_promoted["code"]))

        success_flags = []
        for _, row in df_cands.iterrows():
            curr_date = row["date"]
            next_date = date_to_next.get(curr_date)
            code = row["code"]
            if next_date and (next_date, code) in promoted_keys:
                success_flags.append(1)
            else:
                success_flags.append(0)

        df_cands["success"] = success_flags

        buckets = [
            {"name": "极强接力 (>=120分)", "min": 120, "max": 150},
            {"name": "黄金接力 (100-119分)", "min": 100, "max": 119},
            {"name": "强势潜力 (80-99分)", "min": 80, "max": 99},
            {"name": "弱势跟风 (<80分)", "min": 0, "max": 79}
        ]

        results = []
        for b in buckets:
            df_b = df_cands[(df_cands["score"] >= b["min"]) & (df_cands["score"] <= b["max"])]
            total = len(df_b)
            promoted = df_b["success"].sum() if total > 0 else 0
            rate = (promoted / total * 100) if total > 0 else 0.0
            results.append({
                "bucket_name": b["name"],
                "score_range": f"{b['min']}-{b['max']}",
                "total_count": int(total),
                "promoted_count": int(promoted),
                "win_rate": round(rate, 2)
            })
        return results
    except Exception as e:
        print(f"Error calculating calibration stats: {e}")
        return []

def main():
    import argparse
    parser = argparse.ArgumentParser(description="A-share daily post-market recap engine")
    parser.add_argument(
        "--date",
        type=str,
        help="Specify date in YYYY-MM-DD format (defaults to today, or previous trading day on non-trading days)",
    )
    parser.add_argument("--backfill", type=int, help="Backfill N trading days from history")
    parser.add_argument(
        "--force-non-trading-day",
        action="store_true",
        help="Bypass trading-day gate for replay/tests; output is always observation-only",
    )
    args = parser.parse_args()

    init_db()

    # master trading calendar from mootdx index (last 60 trading days)
    print("Loading trade dates from mootdx index calendar...")
    trade_dates = get_trading_days(offset=60)
    if not trade_dates:
        print("[main] ERROR: trade_dates 为空(适配器不可用),无法继续。")
        return
    print(f"Index calendar loaded. Last trading day in calendar: {trade_dates[-1]}")

    if args.backfill:
        n_days = args.backfill
        if not trade_dates:
            print("[backfill] ERROR: trade_dates 为空(mootdx 不可用),无法执行回填。")
            return
        latest_day = now_shanghai().strftime('%Y-%m-%d')
        valid_dates = [d for d in trade_dates if d <= latest_day]
        backfill_dates = valid_dates[-n_days:]
        if not backfill_dates:
            print(f"[backfill] ERROR: 未找到 <= {latest_day} 的有效交易日。")
            return

        if len(backfill_dates) < n_days:
            print(f"[backfill] WARNING: 请求 {n_days} 天但仅 {len(backfill_dates)} 天可用，继续执行可用部分。")

        print(f"Backfilling {len(backfill_dates)} trading days: {backfill_dates}")
        for date_str in backfill_dates:
            try:
                run_recap(date_str, trade_dates)
            except Exception as e:
                print(f"Error running backfill for {date_str}: {e}")


    else:
        now = now_shanghai()
        date_str, observation_only, defaulted_from_non_trading = resolve_recap_date(
            args.date,
            trade_dates,
            force_non_trading_day=args.force_non_trading_day,
            now=now,
        )

        if defaulted_from_non_trading:
            print(
                f"[gate] {now.strftime('%Y-%m-%d')} 非交易日,默认回退到最近交易日 {date_str}"
                " 并以 observation-only 模式运行(不覆盖已发布数据)。"
                "如需补发布请显式指定 --date。"
            )

        # 交易日闸门:显式指定的非交易日默认拒绝发布(方案 8.3)。
        # 仅 --force-non-trading-day 可绕过,且输出永远为 observation-only;
        # 数据质量闸门不可由该 flag 绕过。
        try:
            from trading_calendar import is_trading_day

            is_td = is_trading_day(date_str)
        except Exception:
            is_td = date_str in trade_dates  # 日历不可用时退回指数日历判定
        if args.date and not is_td and not args.force_non_trading_day:
            print(
                f"[gate] {date_str} 非交易日,拒绝发布(TRADING_DAY_INVALID)。"
                "回放/测试请使用 --force-non-trading-day,输出为 observation-only。"
            )
            return
        if not is_td and args.force_non_trading_day:
            print(f"[gate] {date_str} 非交易日,已强制进入 observation-only 模式。")

        run_recap(date_str, trade_dates, observation_only=observation_only)
if __name__ == "__main__":
    main()
