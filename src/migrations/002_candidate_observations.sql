-- 002: candidate_observations + candidate_decisions + limit_up_events — Phase 2
-- 方案 15.3 / 9.1 / 10.1。
-- 增量 migration:不删除旧表/旧列(AGENTS.md 数据和 SQLite 安全)。
-- candidates 兼容表保持 score 0-150 语义不变,只写最终发布 Top 5(ADR 0002)。

-- candidate_observations:当日全部首板的统一字段、全量特征和标签。
-- ML 只从此表训练(方案 16.1:不能用过滤后的 Top 5)。
-- 缺失特征保持 NULL,不用 0 填充(方案 15.5 第 5 条)。
CREATE TABLE IF NOT EXISTS candidate_observations (
    observation_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_date          TEXT NOT NULL,
    code                TEXT NOT NULL,
    name                TEXT,
    -- 行情(元单位)
    price_yuan          REAL,
    change_pct          REAL,
    turnover_pct        REAL,
    float_mcap_yuan     REAL,
    seal_funds_yuan     REAL,
    first_seal_time     TEXT,
    blown_count         INTEGER,
    consecutive_boards  INTEGER,
    is_st               INTEGER,
    st_source           TEXT,
    sector              TEXT,
    concept             TEXT,
    -- ML 标签:T 日首板在下一交易日成为二板(1/0)
    label_next_2board   INTEGER,
    -- 数据来源质量(LEGACY_PARTIAL 历史回填 / LIVE 实采)
    source_quality      TEXT NOT NULL DEFAULT 'LIVE',
    rule_version        TEXT NOT NULL,
    input_hash          TEXT NOT NULL,
    created_at          TEXT NOT NULL,
    UNIQUE (trade_date, code)
);

CREATE INDEX IF NOT EXISTS idx_obs_trade_date ON candidate_observations(trade_date);
CREATE INDEX IF NOT EXISTS idx_obs_code ON candidate_observations(code);

-- candidate_decisions:每个候选的完整决策记录(方案 9.4 可解释输出)。
-- 主键 (trade_date, code, rule_version):同一日同一股票同一规则版本一条。
CREATE TABLE IF NOT EXISTS candidate_decisions (
    trade_date          TEXT NOT NULL,
    code                TEXT NOT NULL,
    rule_version        TEXT NOT NULL,
    eligible            INTEGER NOT NULL,
    publication_status  TEXT NOT NULL,
    published_rank      INTEGER,
    base_score          INTEGER NOT NULL,
    adjusted_score      INTEGER NOT NULL,
    pred_prob           REAL,
    personality_score   REAL,
    personality_grade   TEXT,
    reason_codes_json   TEXT NOT NULL,
    signals_json        TEXT NOT NULL,
    feature_snapshot_json TEXT NOT NULL,
    input_hash         TEXT NOT NULL,
    created_at          TEXT NOT NULL,
    PRIMARY KEY (trade_date, code, rule_version),
    FOREIGN KEY (trade_date, code) REFERENCES candidate_observations(trade_date, code)
);

CREATE INDEX IF NOT EXISTS idx_dec_trade_date ON candidate_decisions(trade_date);
CREATE INDEX IF NOT EXISTS idx_dec_publication ON candidate_decisions(publication_status);

-- limit_up_events:完整的涨停事件(方案 10.1),供股性评分使用。
-- limit_ups_archive 暂保留供旧面板;新逻辑逐步迁移到此表。
CREATE TABLE IF NOT EXISTS limit_up_events (
    event_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_date          TEXT NOT NULL,
    code                TEXT NOT NULL,
    name                TEXT,
    touched_limit       INTEGER NOT NULL DEFAULT 1,  -- 是否触及涨停
    closed_sealed       INTEGER NOT NULL DEFAULT 1,  -- 是否收盘封板
    blown_count         INTEGER NOT NULL DEFAULT 0,
    first_seal_time     TEXT,
    consecutive_boards  INTEGER NOT NULL DEFAULT 1,
    seal_funds_yuan     REAL,
    limit_pct           REAL,  -- 涨停幅度类型(10/20/30/5)
    lhb_status          TEXT,  -- LISTED / NOT_LISTED / UNKNOWN
    lhb_net_buy_yuan    REAL,
    source              TEXT,
    fetched_at          TEXT NOT NULL,
    quality_status      TEXT NOT NULL DEFAULT 'OK',
    UNIQUE (trade_date, code)
);

CREATE INDEX IF NOT EXISTS idx_lue_trade_date ON limit_up_events(trade_date);
CREATE INDEX IF NOT EXISTS idx_lue_code ON limit_up_events(code);
