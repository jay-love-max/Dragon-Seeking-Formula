-- 004: 候选股新增个性/龙虎榜/挡板字段 — Phase 3/4 前端展示
-- 增量 migration:不删除旧表/旧列(AGENTS.md 数据和 SQLite 安全)。
-- 新字段可为 NULL,后端 SELECT * 透传,读端无害(ADR 0002)。
-- CREATE TABLE IF NOT EXISTS 确保新库也能跑(legacy 表不由 migration 创建)。

CREATE TABLE IF NOT EXISTS candidates (
    date TEXT, code TEXT, name TEXT,
    price REAL, change_pct REAL, turnover REAL,
    float_mcap REAL, seal_funds REAL, seal_ratio REAL,
    first_seal_time TEXT, blown_count INTEGER, consecutive_boards INTEGER,
    sector TEXT, concept TEXT, score INTEGER, playbook TEXT,
    pred_prob REAL,
    PRIMARY KEY (date, code)
);

-- 新字段由 Python migration runner 以幂等方式补齐,避免 SQLite 版本差异。
