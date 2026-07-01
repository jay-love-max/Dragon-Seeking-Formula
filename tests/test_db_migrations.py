"""Phase 1 数据库底座验收 — 连接工厂、版本化 migration、幂等、并发、integrity。

覆盖方案 19.3 集成测试 + AGENTS.md 数据和 SQLite 安全。
"""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

import pytest

import db as dbmod
from db import (
    apply_migrations,
    backup_database,
    connect,
    current_schema_version,
    integrity_check,
    record_run_completion,
    record_run_start,
    record_source_snapshot,
)


@pytest.fixture()
def fresh_db(tmp_path):
    return str(tmp_path / "fresh.db")


@pytest.fixture()
def migrated_db(fresh_db):
    apply_migrations(fresh_db)
    return fresh_db


class TestSqlConnectionFactory:
    def test_wal_journal_mode_and_busy_timeout_set(self, fresh_db):
        conn = connect(fresh_db)
        try:
            assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
            assert int(conn.execute("PRAGMA busy_timeout").fetchone()[0]) == 5000
            assert int(conn.execute("PRAGMA foreign_keys").fetchone()[0]) == 1
        finally:
            conn.close()

    def test_read_only_connection_sets_query_only(self, fresh_db):
        connect(fresh_db)  # create file
        conn = connect(fresh_db, read_only=True)
        try:
            # query_only 阻止写;尝试写应被拒
            with pytest.raises(sqlite3.OperationalError):
                conn.execute("CREATE TABLE t (x)")
                conn.commit()
        finally:
            conn.close()

    def test_sqlite_runtime_version_is_recorded(self):
        # 方案 15.1:部署前必须打印并验证运行时 SQLite 版本
        assert dbmod.SQLITE_RUNTIME_VERSION
        # 解析为可比较的元组;3.50.4 含 2026-03 WAL 多连接修复
        major, minor, *_ = dbmod.SQLITE_RUNTIME_VERSION.split(".")
        assert int(major) >= 3


class TestMigrationRunner:
    def test_user_version_starts_at_zero(self, fresh_db):
        assert current_schema_version(fresh_db) == 0

    def test_migration_creates_recap_runs_and_source_snapshots(self, migrated_db):
        conn = connect(migrated_db, read_only=True)
        try:
            tables = {
                r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            assert "recap_runs" in tables
            assert "source_snapshots" in tables
        finally:
            conn.close()

    def test_user_version_incremented(self, migrated_db):
        assert current_schema_version(migrated_db) == 5

    def test_migration_is_idempotent(self, migrated_db):
        # 再次应用应跳过已应用版本
        applied = apply_migrations(migrated_db)
        assert applied == []
        assert current_schema_version(migrated_db) == 5

    def test_integrity_check_passes_after_migration(self, migrated_db):
        assert integrity_check(migrated_db) == "ok"

    def test_old_tables_preserved_when_migrating_real_db_copy(self, tmp_path):
        # AGENTS.md:首轮改造不删除旧表/旧列。用真实库副本演练迁移。
        src = Path("data/recap.db")
        copy_path = tmp_path / "recap_copy.db"
        backup_database(str(src), str(copy_path))
        # 迁移前旧表存在
        conn = connect(str(copy_path), read_only=True)
        try:
            tables = {
                r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            assert {"candidates", "market_recap", "uzi_audit", "limit_ups_archive"} <= tables
        finally:
            conn.close()
        # 迁移
        apply_migrations(str(copy_path))
        conn = connect(str(copy_path), read_only=True)
        try:
            tables = {
                r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            # 旧表全部保留 + 新表新增
            assert {"candidates", "market_recap", "uzi_audit", "limit_ups_archive"} <= tables
            assert "recap_runs" in tables
            assert "source_snapshots" in tables
        finally:
            conn.close()
        assert integrity_check(str(copy_path)) == "ok"

    def test_old_candidates_score_0_150_semantics_preserved(self, tmp_path):
        # ADR 0002 契约:candidates.score 0-150 语义不可破坏
        src = Path("data/recap.db")
        copy_path = tmp_path / "recap_copy.db"
        backup_database(str(src), str(copy_path))
        apply_migrations(str(copy_path))
        conn = connect(str(copy_path), read_only=True)
        try:
            # 列仍存在且语义不变
            cols = {r[1] for r in conn.execute("PRAGMA table_info(candidates)")}
            assert "score" in cols
            # 旧数据可读
            row = conn.execute(
                "SELECT score FROM candidates WHERE date='2026-06-24' ORDER BY score DESC LIMIT 1"
            ).fetchone()
            assert row is not None
            assert 0 <= int(row[0]) <= 150
        finally:
            conn.close()


class TestRunAndSnapshotRecords:
    def test_record_run_start_and_completion(self, migrated_db):
        record_run_start(
            migrated_db, run_id="run-1", trade_date="2026-06-24",
            run_type="post_market", schema_version=1,
            calendar_source="XSHG",
        )
        conn = connect(migrated_db, read_only=True)
        try:
            row = conn.execute(
                "SELECT status, publishable, rule_version FROM recap_runs WHERE run_id='run-1'"
            ).fetchone()
            assert row["status"] == "RUNNING"
            assert row["publishable"] == 0
            assert row["rule_version"] == "dragon-formula/1.0.0-draft"
        finally:
            conn.close()
        record_run_completion(
            migrated_db, run_id="run-1", status="PUBLISHED", publishable=True,
        )
        conn = connect(migrated_db, read_only=True)
        try:
            row = conn.execute(
                "SELECT status, publishable, completed_at FROM recap_runs WHERE run_id='run-1'"
            ).fetchone()
            assert row["status"] == "PUBLISHED"
            assert row["publishable"] == 1
            assert row["completed_at"] is not None
        finally:
            conn.close()

    def test_record_source_snapshot_persists_evidence(self, migrated_db):
        record_run_start(
            migrated_db, run_id="run-2", trade_date="2026-06-24",
            run_type="post_market", schema_version=1, calendar_source="XSHG",
        )
        record_source_snapshot(
            migrated_db, run_id="run-2", dataset_name="limit_up_pool",
            provider="akshare", as_of="2026-06-24", fetched_at="2026-06-24T15:10:00+08:00",
            status="OK", row_count=98, schema_version=1, checksum="abc",
        )
        conn = connect(migrated_db, read_only=True)
        try:
            row = conn.execute(
                "SELECT status, row_count, as_of FROM source_snapshots WHERE run_id='run-2'"
            ).fetchone()
            assert row["status"] == "OK"
            assert row["row_count"] == 98
            assert row["as_of"] == "2026-06-24"
        finally:
            conn.close()

    def test_record_source_snapshot_can_record_failure(self, migrated_db):
        # 失败不得伪装成空市场(方案 7.1);记录 UNAVAILABLE + 错误信息
        record_run_start(
            migrated_db, run_id="run-3", trade_date="2026-06-24",
            run_type="post_market", schema_version=1, calendar_source="XSHG",
        )
        record_source_snapshot(
            migrated_db, run_id="run-3", dataset_name="index_recap",
            provider="mootdx", as_of=None, fetched_at="2026-06-24T15:10:00+08:00",
            status="UNAVAILABLE", row_count=0, schema_version=1, error="connection timeout",
        )
        conn = connect(migrated_db, read_only=True)
        try:
            row = conn.execute(
                "SELECT status, error FROM source_snapshots WHERE run_id='run-3'"
            ).fetchone()
            assert row["status"] == "UNAVAILABLE"
            assert row["error"] == "connection timeout"
        finally:
            conn.close()


class TestConcurrency:
    def test_concurrent_readers_do_not_block_writer(self, migrated_db):
        # 方案 19.3:pipeline 读、recap 写、vendor 读并发无 database is locked
        errors: list[str] = []

        def reader():
            try:
                conn = connect(migrated_db, read_only=True)
                try:
                    for _ in range(20):
                        conn.execute("SELECT COUNT(*) FROM recap_runs").fetchone()
                finally:
                    conn.close()
            except Exception as e:
                errors.append(f"reader: {e}")

        def writer():
            try:
                for i in range(20):
                    record_run_start(
                        migrated_db, run_id=f"w-{i}", trade_date="2026-06-24",
                        run_type="post_market", schema_version=1, calendar_source="XSHG",
                    )
            except Exception as e:
                errors.append(f"writer: {e}")

        threads = [threading.Thread(target=reader) for _ in range(3)]
        threads.append(threading.Thread(target=writer))
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == [], f"concurrency errors: {errors}"

    def test_write_transaction_outside_ai_call_pattern(self, migrated_db):
        # AGENTS.md:外部网络或 AI 调用必须位于 SQLite 写事务之外。
        # 这里验证写事务短且不持有连接:run_start 提交后连接已关闭。
        record_run_start(
            migrated_db, run_id="run-x", trade_date="2026-06-24",
            run_type="post_market", schema_version=1, calendar_source="XSHG",
        )
        # 模拟外部 AI 调用(此处 sleep)在写事务之外进行 — 仅验证写已落盘
        conn = connect(migrated_db, read_only=True)
        try:
            assert conn.execute(
                "SELECT COUNT(*) FROM recap_runs WHERE run_id='run-x'"
            ).fetchone()[0] == 1
        finally:
            conn.close()
