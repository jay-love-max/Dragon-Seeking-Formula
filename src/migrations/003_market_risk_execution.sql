-- 003: market_risk + execution_plans — Phase 3/6
-- 方案 11.2/12.1/14.2/15.3。
-- 增量 migration:不删除旧表/旧列(AGENTS.md 数据和 SQLite 安全)。

-- market_risk:每日市场级风险状态(方案 11.2/12.1)
CREATE TABLE IF NOT EXISTS market_risk (
    trade_date              TEXT PRIMARY KEY,
    max_consecutive_boards  INTEGER,
    market_regime           TEXT NOT NULL,
    one_to_two_numerator    INTEGER,
    one_to_two_denominator  INTEGER,
    one_to_two_rate         REAL,
    two_to_three_numerator  INTEGER,
    two_to_three_denominator INTEGER,
    two_to_three_rate       REAL,
    f18_policy              TEXT,
    f18_risk_budget         REAL,
    f18_low_sample          INTEGER NOT NULL DEFAULT 0,
    rule_version            TEXT NOT NULL,
    created_at              TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_market_risk_date ON market_risk(trade_date);

-- execution_plans:结构化买入/卖出/防守建议(方案 14.2/14.3/14.4)
CREATE TABLE IF NOT EXISTS execution_plans (
    plan_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_date           TEXT NOT NULL,
    code                 TEXT NOT NULL,
    action               TEXT NOT NULL,
    trigger_type         TEXT,
    trigger_price        REAL,
    reference_price      REAL,
    quantity_pct         REAL,
    valid_from           TEXT,
    valid_until          TEXT,
    precondition         TEXT,
    rule_version         TEXT NOT NULL,
    created_at           TEXT NOT NULL,
    UNIQUE (trade_date, code, action)
);

CREATE INDEX IF NOT EXISTS idx_exec_plans_date ON execution_plans(trade_date);
CREATE INDEX IF NOT EXISTS idx_exec_plans_code ON execution_plans(code);
