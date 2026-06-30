"""Phase 2 候选持久化 — observations / decisions / candidates 兼容表。

方案 15.3/15.4/15.5:
- candidate_observations 写入全部首板(含被过滤的),供 ML 训练;
- candidate_decisions 记录完整可解释输出(reason_codes/signals/input_hash);
- candidates 兼容表只写 Top 5,score 0-150 语义不变(ADR 0002);
- 缺失特征保持 NULL,不用 0 填充。

所有写操作走 db.connect(短事务 + WAL)。金额统一"元"单位;
candidates 兼容表沿用旧库的展示转换(float_mcap 十亿、seal_funds 百万)。
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pandas as pd

from candidate_policy import CandidateDecision
from db import connect
from rule_contract import PublicationStatus


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


# --- candidate_observations ---


def persist_observation(
    db_path: str,
    record: dict[str, Any],
    *,
    label_next_2board: int | None = None,
    source_quality: str = "LIVE",
    rule_version: str | None = None,
    input_hash: str | None = None,
) -> None:
    """写入一条首板观察(UPSERT)。

    缺失特征保持 NULL,不用 0 填充(方案 15.5 第 5 条)。
    """
    from rule_contract import RULE_VERSION

    rv = rule_version or RULE_VERSION
    from candidate_policy import input_hash as _input_hash

    conn = connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO candidate_observations (
                trade_date, code, name,
                price_yuan, change_pct, turnover_pct, float_mcap_yuan, seal_funds_yuan,
                first_seal_time, blown_count, consecutive_boards, is_st, st_source,
                sector, concept, label_next_2board, source_quality, rule_version,
                input_hash, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(trade_date, code) DO UPDATE SET
                name=excluded.name,
                price_yuan=excluded.price_yuan,
                change_pct=excluded.change_pct,
                turnover_pct=excluded.turnover_pct,
                float_mcap_yuan=excluded.float_mcap_yuan,
                seal_funds_yuan=excluded.seal_funds_yuan,
                first_seal_time=excluded.first_seal_time,
                blown_count=excluded.blown_count,
                consecutive_boards=excluded.consecutive_boards,
                is_st=excluded.is_st,
                st_source=excluded.st_source,
                sector=excluded.sector,
                concept=excluded.concept,
                label_next_2board=excluded.label_next_2board,
                source_quality=excluded.source_quality,
                rule_version=excluded.rule_version,
                input_hash=excluded.input_hash
            """,
            (
                str(record.get("trade_date", "")),
                str(record["code"]),
                record.get("name"),
                float(record.get("price", 0.0)) if record.get("price") is not None else None,
                float(record.get("change_pct")) if record.get("change_pct") is not None else None,
                float(record.get("turnover_pct")) if record.get("turnover_pct") is not None else None,
                float(record.get("float_mcap_yuan")) if record.get("float_mcap_yuan") is not None else None,
                float(record.get("seal_funds_yuan")) if record.get("seal_funds_yuan") is not None else None,
                str(record.get("first_seal_time")) if record.get("first_seal_time") is not None else None,
                int(record.get("blown_count")) if record.get("blown_count") is not None else None,
                int(record.get("consecutive_boards")) if record.get("consecutive_boards") is not None else None,
                1 if record.get("is_st") else 0,
                record.get("st_source"),
                record.get("sector"),
                record.get("concept"),
                label_next_2board,
                source_quality,
                rv,
                input_hash or _input_hash(record),
                _utc_now(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


# --- candidate_decisions ---


def persist_decision(db_path: str, decision: CandidateDecision) -> None:
    """写入一条决策记录(UPSERT on trade_date, code, rule_version)。"""
    _persist_decision_clean(db_path, decision)


def _persist_decision_clean(db_path: str, decision: CandidateDecision) -> None:
    """清晰版本的决策写入。"""
    eligible_val = decision.eligible.value if hasattr(decision.eligible, "value") else str(decision.eligible)
    publication_val = (
        decision.publication_status.value
        if hasattr(decision.publication_status, "value")
        else str(decision.publication_status)
    )
    conn = connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO candidate_decisions (
                trade_date, code, rule_version, eligible, publication_status,
                published_rank, base_score, adjusted_score, pred_prob,
                personality_score, personality_grade, reason_codes_json,
                signals_json, feature_snapshot_json, input_hash, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(trade_date, code, rule_version) DO UPDATE SET
                eligible=excluded.eligible,
                publication_status=excluded.publication_status,
                published_rank=excluded.published_rank,
                base_score=excluded.base_score,
                adjusted_score=excluded.adjusted_score,
                pred_prob=excluded.pred_prob,
                personality_score=excluded.personality_score,
                personality_grade=excluded.personality_grade,
                reason_codes_json=excluded.reason_codes_json,
                signals_json=excluded.signals_json,
                feature_snapshot_json=excluded.feature_snapshot_json,
                input_hash=excluded.input_hash
            """,
            (
                decision.trade_date,
                decision.code,
                decision.rule_version,
                1 if eligible_val == "ELIGIBLE" else 0,
                publication_val,
                decision.published_rank,
                decision.base_score,
                decision.adjusted_score,
                decision.pred_prob,
                decision.personality_score,
                decision.personality_grade,
                json.dumps(decision.reason_codes, ensure_ascii=False),
                json.dumps(decision.signals, ensure_ascii=False, default=str),
                json.dumps(
                    {
                        "base_score": decision.base_score,
                        "adjusted_score": decision.adjusted_score,
                        "pred_prob": decision.pred_prob,
                    },
                    ensure_ascii=False,
                ),
                decision.input_hash,
                _utc_now(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


# --- candidates 兼容表(只写 Top 5) ---


def persist_decisions_and_top5(
    db_path: str,
    ranked_decisions: list[CandidateDecision],
    *,
    score_by_code: dict[str, int],
    name_by_code: dict[str, str] | None = None,
    extra_fields_by_code: dict[str, dict[str, Any]] | None = None,
) -> None:
    """Write all decisions and publish only Top 5 rows into candidates."""

    def _first_not_none(*values: Any) -> Any:
        for value in values:
            if value is None:
                continue
            try:
                if pd.isna(value):
                    continue
            except Exception:
                pass
            return value
        return None

    def _json_text(value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False)

    for d in ranked_decisions:
        _persist_decision_clean(db_path, d)

    if not ranked_decisions:
        return

    trade_date = ranked_decisions[0].trade_date
    name_by_code = name_by_code or {}
    extra_fields_by_code = extra_fields_by_code or {}

    conn = connect(db_path)
    try:
        conn.execute("DELETE FROM candidates WHERE date = ?", (trade_date,))
        for d in ranked_decisions:
            if d.publication_status != PublicationStatus.PUBLISHED_TOP5:
                continue

            score = int(score_by_code.get(d.code, d.base_score))
            score = max(0, min(150, score))
            extra = extra_fields_by_code.get(d.code, {})
            signals = d.signals or {}

            float_mcap_yuan = _first_not_none(signals.get("float_mcap_yuan"), extra.get("float_mcap_yuan"))
            seal_funds_yuan = _first_not_none(signals.get("seal_funds_yuan"), extra.get("seal_funds_yuan"))
            float_mcap_yi = (
                round(float(float_mcap_yuan) / 1e8, 2)
                if float_mcap_yuan is not None
                else extra.get("float_mcap")
            )
            seal_funds_wan = (
                round(float(seal_funds_yuan) / 1e4, 2)
                if seal_funds_yuan is not None
                else extra.get("seal_funds")
            )
            personality_grade = _first_not_none(
                signals.get("personality_grade"),
                extra.get("personality_grade"),
            )
            personality_dims = _json_text(
                _first_not_none(signals.get("personality_dims"), extra.get("personality_dims"))
            )

            conn.execute(
                """
                INSERT INTO candidates (
                    date, code, name, price, change_pct, turnover, float_mcap, seal_funds,
                    seal_ratio, first_seal_time, blown_count, consecutive_boards, sector,
                    concept, score, playbook, pred_prob,
                    personality_grade, personality_dims, lhb_gold_net, lhb_death_net, lhb_inst_net,
                    block_f16, block_f17, block_f18, block_f19
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                          ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trade_date,
                    d.code,
                    name_by_code.get(d.code, ""),
                    extra.get("price"),
                    extra.get("change_pct"),
                    extra.get("turnover"),
                    float_mcap_yi,
                    seal_funds_wan,
                    extra.get("seal_ratio"),
                    signals.get("first_seal_time"),
                    signals.get("blown_count"),
                    signals.get("consecutive_boards", 1),
                    extra.get("sector"),
                    extra.get("concept"),
                    score,
                    extra.get("playbook"),
                    d.pred_prob,
                    personality_grade,
                    personality_dims,
                    _first_not_none(signals.get("lhb_gold_net"), extra.get("lhb_gold_net")),
                    _first_not_none(signals.get("lhb_death_net"), extra.get("lhb_death_net")),
                    _first_not_none(signals.get("lhb_inst_net"), extra.get("lhb_inst_net")),
                    _first_not_none(signals.get("block_f16"), extra.get("block_f16")),
                    _first_not_none(signals.get("block_f17"), extra.get("block_f17")),
                    _first_not_none(signals.get("block_f18"), extra.get("block_f18")),
                    _first_not_none(signals.get("block_f19"), extra.get("block_f19")),
                ),
            )
        conn.commit()
    finally:
        conn.close()


# --- ML 训练读取(方案 16.1:从 observations,不是 Top 5) ---


def fetch_observations_for_training(db_path: str, *, end_date: str) -> pd.DataFrame:
    """读取 end_date(含)之前的全部首板观察,供 ML 训练。

    方案 16.1:不能用过滤后的 Top 5;此处返回全部 observations。
    方案 16.2:严格排除未来数据(WHERE trade_date <= end_date)。
    缺失特征保持 NULL(Pandas 读出为 NaN),不用 0 填充。
    """
    conn = connect(db_path, read_only=True)
    try:
        df = pd.read_sql_query(
            """
            SELECT trade_date, code, name, price_yuan AS price, change_pct, turnover_pct,
                   float_mcap_yuan AS float_mcap, seal_funds_yuan AS seal_funds,
                   first_seal_time, blown_count, consecutive_boards, is_st, sector,
                   concept, label_next_2board, source_quality, rule_version, input_hash
              FROM candidate_observations
             WHERE trade_date <= ?
             ORDER BY trade_date ASC, code ASC
            """,
            conn,
            params=(end_date,),
        )
    finally:
        conn.close()
    return df
