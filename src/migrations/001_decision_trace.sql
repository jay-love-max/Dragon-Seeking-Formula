-- 001: recap_runs + source_snapshots — 发布链路与数据真伪证据(Phase 1)
-- 冲突裁决见 docs/adr/0003-rule-contract-and-conflict-adjudication.md
-- 增量 migration:不删除旧表/旧列(AGENTS.md 数据和 SQLite 安全)。

-- recap_runs:每次复盘运行的确定性骨架(方案 15.3)
CREATE TABLE IF NOT EXISTS recap_runs (
    run_id          TEXT PRIMARY KEY,
    trade_date      TEXT NOT NULL,
    run_type        TEXT NOT NULL,
    rule_version    TEXT NOT NULL,
    schema_version  INTEGER NOT NULL,
    status          TEXT NOT NULL,
    publishable     INTEGER NOT NULL,
    started_at      TEXT NOT NULL,
    completed_at    TEXT,
    calendar_source TEXT,
    failure_code    TEXT,
    failure_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_recap_runs_trade_date ON recap_runs(trade_date);

-- source_snapshots:数据真伪证据(方案 7.1 / 15.3)
CREATE TABLE IF NOT EXISTS source_snapshots (
    run_id          TEXT NOT NULL,
    dataset_name    TEXT NOT NULL,
    provider        TEXT NOT NULL,
    as_of           TEXT,
    fetched_at      TEXT NOT NULL,
    status          TEXT NOT NULL,
    row_count       INTEGER NOT NULL,
    schema_version  INTEGER NOT NULL,
    checksum        TEXT,
    error           TEXT,
    FOREIGN KEY (run_id) REFERENCES recap_runs(run_id)
);

CREATE INDEX IF NOT EXISTS idx_source_snapshots_run ON source_snapshots(run_id);
