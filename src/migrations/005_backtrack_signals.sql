CREATE TABLE IF NOT EXISTS backtrack_signals (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_date      TEXT NOT NULL,
    code            TEXT NOT NULL,
    name            TEXT,
    pattern         TEXT NOT NULL,
    score           REAL NOT NULL,
    evidence        TEXT NOT NULL,
    candidate_date  TEXT NOT NULL,
    candidate_score INTEGER,
    current_price   REAL,
    change_pct      REAL,
    created_at      TEXT NOT NULL,
    UNIQUE (trade_date, code, pattern)
);

CREATE INDEX IF NOT EXISTS idx_bt_trade_date ON backtrack_signals(trade_date);
CREATE INDEX IF NOT EXISTS idx_bt_pattern ON backtrack_signals(pattern);
