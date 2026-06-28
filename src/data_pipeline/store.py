import logging

import pandas as pd

from db import connect

logger = logging.getLogger("data_pipeline.store")

SNAPSHOT_SCHEMA = """
CREATE TABLE IF NOT EXISTS realtime_snapshot (
    code TEXT PRIMARY KEY,
    name TEXT,
    price REAL,
    change_pct REAL,
    turnover REAL,
    seal_funds REAL,
    seal_ratio_instant REAL,
    first_seal_time TEXT,
    blown_count INTEGER DEFAULT 0,
    consecutive_boards INTEGER DEFAULT 0,
    sector TEXT,
    float_mcap REAL,
    sector_limit_ups INTEGER DEFAULT 0,
    score_intraday INTEGER,
    score_intraday_prev INTEGER,
    quality_state TEXT,
    missing_fields TEXT,
    ts TEXT,
    source_tag TEXT,
    quote_source_tag TEXT,
    limit_up_source_tag TEXT
);
"""


class Store:
    """SQLite persistence for realtime snapshot data."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn = connect(db_path)
        self.conn.execute("PRAGMA busy_timeout = 10000")

        self.conn.executescript(SNAPSHOT_SCHEMA)
        self._ensure_columns([
            "score_intraday_prev",
            "quality_state",
            "missing_fields",
            "consecutive_boards",
            "sector_limit_ups",
            "quote_source_tag",
            "limit_up_source_tag",
        ])
        self.conn.commit()

    def _ensure_columns(self, columns: list[str]):
        cursor = self.conn.execute("PRAGMA table_info(realtime_snapshot)")
        existing = {row[1] for row in cursor.fetchall()}
        for col in columns:
            if col not in existing:
                col_type = "TEXT" if col in {
                    "quality_state",
                    "missing_fields",
                    "quote_source_tag",
                    "limit_up_source_tag",
                } else "INTEGER"
                if col in {"score_intraday_prev", "consecutive_boards", "sector_limit_ups"}:
                    col_type = "INTEGER"
                self.conn.execute(f'ALTER TABLE realtime_snapshot ADD COLUMN "{col}" {col_type}')

    def write_snapshot(self, df: pd.DataFrame):
        if df.empty:
            return
        df = df.copy()
        if "seal_funds" in df.columns and "float_mcap" in df.columns:
            mask = df["seal_funds"].notna() & df["float_mcap"].notna() & (df["float_mcap"] > 0)
            df.loc[mask, "seal_ratio_instant"] = (
                df.loc[mask, "seal_funds"] / df.loc[mask, "float_mcap"] * 100
            )

        table_columns = {
            row[1] for row in self.conn.execute("PRAGMA table_info(realtime_snapshot)").fetchall()
        }
        unknown_columns = sorted(set(df.columns) - table_columns)
        if unknown_columns:
            raise ValueError(f"unsupported realtime_snapshot columns: {', '.join(unknown_columns)}")

        cols = [c for c in df.columns if c != "code"]
        placeholders = ", ".join([f'"{c}"=excluded."{c}"' for c in cols])
        col_names = ", ".join(['"code"'] + [f'"{c}"' for c in cols])
        col_qs = ", ".join(["?" for _ in range(len(cols) + 1)])

        sql = (
            f"INSERT INTO realtime_snapshot ({col_names}) "
            f"VALUES ({col_qs}) "
            f"ON CONFLICT(code) DO UPDATE SET {placeholders}"
        )

        rows = df.to_dict("records")
        try:
            for row in rows:
                vals = [row.get(c) for c in ["code"] + cols]
                vals = [None if (isinstance(v, float) and pd.isna(v)) else v for v in vals]
                self.conn.execute(sql, vals)
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            logger.exception("snapshot batch write failed")
    def get_snapshot(self) -> dict[str, dict]:
        columns = [row[1] for row in self.conn.execute("PRAGMA table_info(realtime_snapshot)").fetchall()]
        cursor = self.conn.execute("SELECT * FROM realtime_snapshot")
        rows = cursor.fetchall()
        result = {}
        for row in rows:
            record = dict(zip(columns, row))
            code = record.pop("code", "")
            result[code] = record
        return result

    def cleanup(self):
        self.conn.execute("DELETE FROM realtime_snapshot")
        self.conn.commit()
        logger.info("realtime_snapshot cleared")

    def close(self):
        self.conn.close()
