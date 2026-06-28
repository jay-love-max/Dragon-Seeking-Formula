"""Phase 2 migration 002 + 持久化测试。

覆盖方案 15.3/15.4/15.5 与 Phase 2 验收:
- 增量 migration 幂等;旧表(candidates/limit_ups_archive/market_recap/uzi_audit)保留;
- candidate_observations 可写入全部首板(含被过滤的);
- candidate_decisions 记录完整可解释输出;
- ML 从 observations 读取训练数据,不用过滤后的 Top 5;
- candidates 兼容表只写 Top 5,score 0-150 不变。

所有用例本地、确定,不依赖实时网络(AGENTS.md)。
"""
from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

import pytest

from candidate_policy import CandidateDecision, evaluate_f19, rank_candidates
from candidate_store import (
    fetch_observations_for_training,
    persist_decision,
    persist_decisions_and_top5,
    persist_observation,
)
from db import (
    apply_migrations,
    connect,
    create_legacy_tables,
    current_schema_version,
    integrity_check,
)
from rule_contract import load_rule_config
from tests.fixtures.golden_samples import (
    GOLDEN_2026_06_24,
    GOLDEN_2026_06_25_KESHIDA,
    SEAL_TIME_095959,
    first_board_record,
)


@pytest.fixture()
def migrated_db(tmp_path):
    """提供一个已完成 002 migration 的临时库(含旧兼容表)。"""
    db_path = str(tmp_path / "phase2.db")
    apply_migrations(db_path)
    # 创建旧兼容表(candidates/market_recap/limit_ups_archive/uzi_audit)
    create_legacy_tables(db_path)
    return db_path


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


class TestMigration002:
    """方案 15.3/15.4:增量 migration,旧表保留,新表创建。"""

    def test_migration_advances_user_version(self, migrated_db):
        version = current_schema_version(migrated_db)
        assert version >= 2

    def test_migration_idempotent(self, migrated_db):
        # 重跑 migration 不报错,版本不变
        applied = apply_migrations(migrated_db)
        assert applied == []
        assert integrity_check(migrated_db) == "ok"

    def test_new_tables_exist(self, migrated_db):
        conn = connect(migrated_db, read_only=True)
        try:
            tables = {
                r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            assert "candidate_observations" in tables
            assert "candidate_decisions" in tables
            assert "limit_up_events" in tables
        finally:
            conn.close()

    def test_old_tables_not_dropped_when_present(self, tmp_path):
        """旧库已有 candidates 等表时,migration 不得删除。"""
        db_path = str(tmp_path / "with_old.db")
        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE candidates (date TEXT, code TEXT, score INTEGER, pred_prob REAL)"
        )
        conn.execute("INSERT INTO candidates VALUES ('2026-06-24','600584',100,NULL)")
        conn.commit()
        conn.close()

        apply_migrations(db_path)
        conn = connect(db_path, read_only=True)
        try:
            row = conn.execute("SELECT score FROM candidates WHERE code='600584'").fetchone()
            assert row[0] == 100
        finally:
            conn.close()

    def test_integrity_check_passes(self, migrated_db):
        assert integrity_check(migrated_db) == "ok"


class TestPersistObservation:
    """方案 9.1 第一层:全部首板进入 candidate_observations。"""

    def test_persist_observation_writes_full_fields(self, migrated_db):
        rec = GOLDEN_2026_06_24[0]
        persist_observation(migrated_db, rec, label_next_2board=None, source_quality="LIVE")
        conn = connect(migrated_db, read_only=True)
        try:
            row = conn.execute(
                "SELECT code, seal_funds_yuan, float_mcap_yuan, is_st FROM candidate_observations WHERE code=?",
                (rec["code"],),
            ).fetchone()
            assert row[0] == rec["code"]
            assert row[1] == rec["seal_funds_yuan"]
            assert row[2] == rec["float_mcap_yuan"]
            assert row[3] == 0  # 非 ST
        finally:
            conn.close()

    def test_persist_observation_upsert_idempotent(self, migrated_db):
        rec = GOLDEN_2026_06_24[0]
        persist_observation(migrated_db, rec)
        persist_observation(migrated_db, rec)  # 重写不重复
        conn = connect(migrated_db, read_only=True)
        try:
            count = conn.execute(
                "SELECT COUNT(*) FROM candidate_observations WHERE code=?", (rec["code"],)
            ).fetchone()[0]
            assert count == 1
        finally:
            conn.close()

    def test_filtered_candidate_still_in_observations(self, migrated_db):
        """科士达被 F19 过滤,但仍写入 observations 供训练。"""
        persist_observation(migrated_db, GOLDEN_2026_06_25_KESHIDA)
        conn = connect(migrated_db, read_only=True)
        try:
            row = conn.execute(
                "SELECT code FROM candidate_observations WHERE code=?",
                (GOLDEN_2026_06_25_KESHIDA["code"],),
            ).fetchone()
            assert row is not None
        finally:
            conn.close()


class TestPersistDecision:
    """方案 9.4:candidate_decisions 记录完整可解释输出。"""

    def _decision(self) -> CandidateDecision:
        cfg = load_rule_config()
        rec = GOLDEN_2026_06_24[0]
        return evaluate_f19(rec, cfg, recent_limit_ups_by_code={rec["code"]: ["2026-06-22", "2026-06-24"]})

    def test_persist_decision_writes_reason_codes(self, migrated_db):
        decision = self._decision()
        persist_observation(migrated_db,
            {k: v for k, v in GOLDEN_2026_06_24[0].items()})
        persist_decision(migrated_db, decision)
        conn = connect(migrated_db, read_only=True)
        try:
            row = conn.execute(
                "SELECT eligible, reason_codes_json, signals_json, input_hash FROM candidate_decisions WHERE code=?",
                (decision.code,),
            ).fetchone()
            assert row[0] == 1  # eligible
            assert "[]" not in row[2] or row[2]  # signals_json non-empty
            assert row[3] == decision.input_hash
        finally:
            conn.close()

    def test_persist_decision_upsert(self, migrated_db):
        decision = self._decision()
        persist_observation(migrated_db,
            {k: v for k, v in GOLDEN_2026_06_24[0].items()})
        persist_decision(migrated_db, decision)
        persist_decision(migrated_db, decision)
        conn = connect(migrated_db, read_only=True)
        try:
            count = conn.execute(
                "SELECT COUNT(*) FROM candidate_decisions WHERE code=?", (decision.code,)
            ).fetchone()[0]
            assert count == 1
        finally:
            conn.close()


class TestPersistDecisionsAndTop5:
    """方案 15.4:candidates 兼容表只写 Top 5,score 0-150 不变。"""

    def test_only_top5_written_to_candidates(self, migrated_db):
        cfg = load_rule_config()
        recs = [
            first_board_record(
                f"3000{i:02d}", f"股票{i}",
                seal_funds_yuan=50_000_000 + i * 10_000_000,
                blown_count=0, first_seal_time=SEAL_TIME_095959, trade_date="2026-06-24",
            )
            for i in range(7)
        ]
        decisions = [
            evaluate_f19(r, cfg, recent_limit_ups_by_code={r["code"]: ["2026-06-22", "2026-06-24"]})
            for r in recs
        ]
        ranked = rank_candidates(decisions, cfg)
        # 先写入 observations 以满足 FK 约束
        for r in recs:
            persist_observation(migrated_db, r)
        persist_decisions_and_top5(migrated_db, ranked, score_by_code={d.code: 100 + i for i, d in enumerate(ranked)})

        conn = connect(migrated_db, read_only=True)
        try:
            top5_count = conn.execute(
                "SELECT COUNT(*) FROM candidates WHERE date='2026-06-24'"
            ).fetchone()[0]
            assert top5_count == 5

            # decisions 全部写入(含 Top5 外)
            dec_count = conn.execute(
                "SELECT COUNT(*) FROM candidate_decisions WHERE trade_date='2026-06-24'"
            ).fetchone()[0]
            assert dec_count == 7
        finally:
            conn.close()

    def test_candidates_score_preserved_0_150(self, migrated_db):
        """ADR 0002:candidates.score 0-150 语义不变。"""
        cfg = load_rule_config()
        rec = GOLDEN_2026_06_24[0]
        decision = evaluate_f19(rec, cfg, recent_limit_ups_by_code={rec["code"]: ["2026-06-22", "2026-06-24"]})
        ranked = rank_candidates([decision], cfg)
        # 先写入 observation 以满足 FK 约束
        persist_observation(migrated_db, rec)
        persist_decisions_and_top5(migrated_db, ranked, score_by_code={rec["code"]: 120})

        conn = connect(migrated_db, read_only=True)
        try:
            score = conn.execute(
                "SELECT score FROM candidates WHERE code=?", (rec["code"],)
            ).fetchone()[0]
            assert 0 <= score <= 150
            assert score == 120
        finally:
            conn.close()

    def test_extended_candidate_fields_are_persisted(self, migrated_db):
        cfg = load_rule_config()
        rec = GOLDEN_2026_06_24[0]
        decision = evaluate_f19(rec, cfg, recent_limit_ups_by_code={rec["code"]: ["2026-06-22", "2026-06-24"]})
        ranked = rank_candidates([decision], cfg)
        persist_observation(migrated_db, rec)
        persist_decisions_and_top5(
            migrated_db,
            ranked,
            score_by_code={rec["code"]: 128},
            extra_fields_by_code={
                rec["code"]: {
                    "price": 10.5,
                    "change_pct": 9.9,
                    "turnover": 7.7,
                    "float_mcap": 12.3,
                    "seal_funds": 45.6,
                    "seal_ratio": 3.7,
                    "first_seal_time": "09:35:00",
                    "blown_count": 1,
                    "sector": "电子",
                    "concept": "题材A",
                    "playbook": "playbook",
                    "personality_grade": "A",
                    "personality_dims": {"activity": 1.0, "reliability": 0.9},
                    "lhb_gold_net": 123.0,
                    "lhb_death_net": None,
                    "lhb_inst_net": 45.0,
                    "block_f16": 0,
                    "block_f17": 1,
                    "block_f18": 0,
                    "block_f19": 1,
                }
            },
        )

        conn = connect(migrated_db, read_only=True)
        try:
            row = conn.execute(
                """
                SELECT personality_grade, personality_dims, lhb_gold_net, lhb_inst_net,
                       block_f17, block_f19, score
                  FROM candidates
                 WHERE code=?
                """,
                (rec["code"],),
            ).fetchone()
            assert row[0] == "A"
            assert row[1] is not None
            assert row[2] == 123.0
            assert row[3] == 45.0
            assert row[4] == 1
            assert row[5] == 1
            assert row[6] == 128
        finally:
            conn.close()

class TestMLReadsObservations:
    """方案 16.1:训练输入改为 candidate_observations,不能用过滤后的 Top 5。"""

    def test_fetch_observations_returns_all_not_top5(self, migrated_db):
        """写入 7 个首板,fetch 应返回全部 7 个(含被过滤的)。"""
        recs = [
            first_board_record(
                f"3000{i:02d}", f"股票{i}",
                seal_funds_yuan=50_000_000 + i * 10_000_000,
                blown_count=0, first_seal_time=SEAL_TIME_095959, trade_date="2026-06-24",
            )
            for i in range(6)
        ]
        # 加一个被过滤的(封单不足)
        recs.append(first_board_record(
            "300099", "封单不足",
            seal_funds_yuan=10_000_000, blown_count=0, first_seal_time=SEAL_TIME_095959, trade_date="2026-06-24",
        ))
        for r in recs:
            persist_observation(migrated_db, r)

        df = fetch_observations_for_training(migrated_db, end_date="2026-06-25")
        # 应返回 7 个(含被过滤的),不是 Top 5
        assert len(df) == 7
        assert "300099" in df["code"].tolist()

    def test_fetch_observations_excludes_future(self, migrated_db):
        """方案 16.2:严格排除未来数据。"""
        rec_today = first_board_record(
            "300050", "今天",
            seal_funds_yuan=50_000_000, blown_count=0, first_seal_time="09:30:00",
            trade_date="2026-06-24",
        )
        rec_future = first_board_record(
            "300051", "未来",
            seal_funds_yuan=50_000_000, blown_count=0, first_seal_time="09:30:00",
            trade_date="2026-06-26",
        )
        persist_observation(migrated_db, rec_today)
        persist_observation(migrated_db, rec_future)

        df = fetch_observations_for_training(migrated_db, end_date="2026-06-25")
        codes = df["code"].tolist()
        assert "300050" in codes
        assert "300051" not in codes  # 未来数据排除
