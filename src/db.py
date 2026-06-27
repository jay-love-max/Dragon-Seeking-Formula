"""统一 SQLite 连接工厂与 migration runner。"""
from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Iterator, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import apsw

from rule_contract import RULE_VERSION

SQLITE_RUNTIME_VERSION = apsw.sqlitelibversion()
MIN_SQLITE_RUNTIME_VERSION = (3, 50, 4)
DEFAULT_PRAGMAS = {
    "foreign_keys": "ON",
    "journal_mode": "WAL",
    "busy_timeout": "5000",
    "synchronous": "NORMAL",
}
MIGRATIONS_DIR = Path(__file__).resolve().parents[0] / "migrations"


def _parse_version(value: str) -> tuple[int, int, int]:
    parts = []
    for chunk in str(value).split("."):
        try:
            parts.append(int(chunk))
        except Exception:
            parts.append(0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def ensure_sqlite_runtime() -> None:
    if _parse_version(SQLITE_RUNTIME_VERSION) < MIN_SQLITE_RUNTIME_VERSION:
        raise RuntimeError(
            f"SQLite runtime {SQLITE_RUNTIME_VERSION} is below minimum "
            f"{'.'.join(map(str, MIN_SQLITE_RUNTIME_VERSION))}"
        )


def _translate_sqlite_error(exc: Exception) -> Exception:
    if isinstance(exc, apsw.ReadOnlyError):
        return sqlite3.OperationalError(str(exc))
    return exc




class Row(Mapping[str, Any]):
    def __init__(self, description: tuple[tuple[Any, ...], ...], values: tuple[Any, ...]):
        self._columns = tuple(col[0] for col in description)
        self._values = tuple(values)
        self._index = {name: idx for idx, name in enumerate(self._columns)}

    def __getitem__(self, key: str | int | slice) -> Any:
        if isinstance(key, slice):
            return self._values[key]
        if isinstance(key, int):
            return self._values[key]
        return self._values[self._index[key]]

    def __iter__(self) -> Iterator[Any]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def keys(self):
        return self._columns

    def items(self):
        return tuple((name, self[name]) for name in self._columns)

    def get(self, key: str, default: Any = None) -> Any:
        return self[key] if key in self._index else default

    def __contains__(self, key: object) -> bool:
        return isinstance(key, str) and key in self._index

class CursorWrapper:
    def __init__(self, cursor: apsw.Cursor, row_factory: type[Row] | None):
        self._cursor = cursor
        self._row_factory = row_factory
        self._description = None

    def _capture_description(self) -> None:
        if self._description is not None:
            return
        try:
            self._description = self._cursor.description
        except Exception:
            self._description = None

    @property
    def description(self):
        self._capture_description()
        return self._description

    def _wrap(self, row: Any) -> Any:
        if row is None or self._row_factory is None:
            return row
        self._capture_description()
        return self._row_factory(self._description, tuple(row))

    def execute(self, sql: str, params: Iterable[Any] | None = None):
        try:
            if params is None:
                self._cursor.execute(sql)
            else:
                self._cursor.execute(sql, params)
            self._capture_description()
        except Exception as exc:
            raise _translate_sqlite_error(exc) from exc
        return self

    def fetchone(self):
        self._capture_description()
        row = self._cursor.fetchone()
        return self._wrap(row)

    def fetchall(self):
        self._capture_description()
        return [self._wrap(row) for row in self._cursor.fetchall()]

    def fetchmany(self, size: int | None = None):
        self._capture_description()
        rows = self._cursor.fetchmany() if size is None else self._cursor.fetchmany(size)
        return [self._wrap(row) for row in rows]

    def __iter__(self) -> Iterator[Any]:
        self._capture_description()
        for row in self._cursor:
            yield self._wrap(row)


    def close(self):
        return self._cursor.close()

    def __getattr__(self, name: str):
        return getattr(self._cursor, name)


class ConnectionWrapper:
    def __init__(self, db_path: str, *, read_only: bool = False):
        self.db_path = db_path
        self.read_only = read_only
        self._conn = apsw.Connection(str(db_path))
        self.row_factory = Row
        self._conn.setbusytimeout(5000)
        cur = self._conn.cursor()
        cur.execute("PRAGMA foreign_keys = ON;")
        cur.execute("PRAGMA busy_timeout = 5000;")
        if read_only:
            cur.execute("PRAGMA query_only = ON;")
        else:
            cur.execute("PRAGMA journal_mode = WAL;")
            cur.execute("PRAGMA synchronous = NORMAL;")

    def cursor(self) -> CursorWrapper:
        return CursorWrapper(self._conn.cursor(), self.row_factory)

    def execute(self, sql: str, params: Iterable[Any] | None = None) -> CursorWrapper:
        cur = self.cursor()
        return cur.execute(sql, params)

    def executescript(self, sql: str):
        self._conn.execute(sql)
        return None

    def commit(self):
        if self._conn.in_transaction:
            self._conn.execute("COMMIT")

    def rollback(self):
        if self._conn.in_transaction:
            self._conn.execute("ROLLBACK")

    def close(self):
        return self._conn.close()

    @property
    def in_transaction(self) -> bool:
        return bool(self._conn.in_transaction)

    def __getattr__(self, name: str):
        return getattr(self._conn, name)


def connect(db_path: str, *, read_only: bool = False) -> ConnectionWrapper:
    """统一连接工厂:WAL + busy_timeout + foreign_keys + synchronous=NORMAL。"""
    return ConnectionWrapper(db_path, read_only=read_only)


def current_schema_version(db_path: str) -> int:
    if not Path(db_path).exists():
        return 0
    conn = connect(db_path, read_only=True)
    try:
        return int(conn.execute("PRAGMA user_version").fetchone()[0])
    finally:
        conn.close()


def integrity_check(db_path: str) -> str:
    if not Path(db_path).exists():
        return "missing"
    conn = connect(db_path, read_only=True)
    try:
        return str(conn.execute("PRAGMA integrity_check").fetchone()[0])
    finally:
        conn.close()


def _migration_files() -> list[Path]:
    if not MIGRATIONS_DIR.exists():
        return []
    return sorted(MIGRATIONS_DIR.glob("*.sql"))


def _migration_version(path: Path) -> int:
    return int(path.stem.split("_", 1)[0])


def _ensure_candidate_columns(conn: ConnectionWrapper) -> None:
    existing = {
        row[1]
        for row in conn.execute("PRAGMA table_info(candidates)")
        if row is not None
    }
    for name, column_type in (
        ("personality_grade", "TEXT"),
        ("personality_dims", "TEXT"),
        ("lhb_gold_net", "REAL"),
        ("lhb_death_net", "REAL"),
        ("lhb_inst_net", "REAL"),
        ("block_f16", "INTEGER"),
        ("block_f17", "INTEGER"),
        ("block_f18", "INTEGER"),
        ("block_f19", "INTEGER"),
    ):
        if name not in existing:
            conn.execute(f"ALTER TABLE candidates ADD COLUMN {name} {column_type}")

def apply_migrations(db_path: str, *, target: int | None = None) -> list[int]:
    """串行执行未应用的 migration,每个在单事务中执行。"""
    applied_now: list[int] = []
    current = current_schema_version(db_path)
    for path in _migration_files():
        version = _migration_version(path)
        if version <= current:
            continue
        if target is not None and version > target:
            break
        sql = path.read_text(encoding="utf-8")
        conn = connect(db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.executescript(sql)
            if version == 4:
                _ensure_candidate_columns(conn)
            conn.execute(f"PRAGMA user_version = {version};")
            conn.commit()
            applied_now.append(version)

            current = version
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    return applied_now


def backup_database(src_path: str, dest_path: str) -> None:
    """使用 SQLite backup API 备份。"""
    Path(dest_path).parent.mkdir(parents=True, exist_ok=True)
    src = apsw.Connection(src_path)
    dst = apsw.Connection(dest_path)
    try:
        backup = dst.backup("main", src, "main")
        try:
            backup.step(-1)
        finally:
            backup.finish()
    finally:
        dst.close()
        src.close()


def record_run_start(
    db_path: str,
    *,
    run_id: str,
    trade_date: str,
    run_type: str,
    schema_version: int,
    calendar_source: str,
) -> None:
    conn = connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO recap_runs
                (run_id, trade_date, run_type, rule_version, schema_version,
                 status, publishable, started_at, completed_at, calendar_source,
                 failure_code, failure_message)
            VALUES (?, ?, ?, ?, ?, 'RUNNING', 0, ?, NULL, ?, NULL, NULL)
            """,
            (
                run_id,
                trade_date,
                run_type,
                RULE_VERSION,
                schema_version,
                _utc_now_iso(),
                calendar_source,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def record_run_completion(
    db_path: str,
    *,
    run_id: str,
    status: str,
    publishable: bool,
    failure_code: str | None = None,
    failure_message: str | None = None,
) -> None:
    conn = connect(db_path)
    try:
        conn.execute(
            """
            UPDATE recap_runs
               SET status = ?, publishable = ?, completed_at = ?,
                   failure_code = ?, failure_message = ?
             WHERE run_id = ?
            """,
            (
                status,
                1 if publishable else 0,
                _utc_now_iso(),
                failure_code,
                failure_message,
                run_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def record_source_snapshot(
    db_path: str,
    *,
    run_id: str,
    dataset_name: str,
    provider: str,
    as_of: str | None,
    fetched_at: str,
    status: str,
    row_count: int,
    schema_version: int,
    checksum: str | None = None,
    error: str | None = None,
) -> None:
    conn = connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO source_snapshots
                (run_id, dataset_name, provider, as_of, fetched_at, status,
                 row_count, schema_version, checksum, error)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                dataset_name,
                provider,
                as_of,
                fetched_at,
                status,
                row_count,
                schema_version,
                checksum,
                error,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def create_legacy_tables(db_path: str) -> None:
    """创建 recap_engine.init_db() 原有兼容表。"""
    conn = connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS market_recap (
                date TEXT PRIMARY KEY,
                sh_price REAL, sh_change REAL,
                sz_price REAL, sz_change REAL,
                cy_price REAL, cy_change REAL,
                total_turnover REAL,
                limit_ups INTEGER, limit_downs INTEGER,
                promotion_rate REAL,
                hgt_flow REAL, sgt_flow REAL,
                sentiment TEXT, sector_ranking TEXT
            );

            CREATE TABLE IF NOT EXISTS candidates (
                date TEXT, code TEXT, name TEXT,
                price REAL, change_pct REAL, turnover REAL,
                float_mcap REAL, seal_funds REAL, seal_ratio REAL,
                first_seal_time TEXT, blown_count INTEGER, consecutive_boards INTEGER,
                sector TEXT, concept TEXT, score INTEGER, playbook TEXT,
                pred_prob REAL,
                personality_grade TEXT,
                personality_dims TEXT,
                lhb_gold_net REAL,
                lhb_death_net REAL,
                lhb_inst_net REAL,
                block_f16 INTEGER,
                block_f17 INTEGER,
                block_f18 INTEGER,
                block_f19 INTEGER,
                PRIMARY KEY (date, code)
            );

            CREATE TABLE IF NOT EXISTS limit_ups_archive (
                date TEXT, code TEXT, name TEXT, consecutive_boards INTEGER,
                PRIMARY KEY (date, code)
            );

            CREATE TABLE IF NOT EXISTS uzi_audit (
                date TEXT, code TEXT, name TEXT,
                average_score REAL, val_vote TEXT, mom_vote TEXT, risk_level TEXT,
                summary TEXT, report_path TEXT, analysis_json TEXT
            );

            CREATE TABLE IF NOT EXISTS model_runs (
                date TEXT PRIMARY KEY,
                model_version TEXT NOT NULL,
                status TEXT NOT NULL,
                train_start TEXT,
                train_end TEXT,
                train_samples INTEGER NOT NULL,
                holdout_start TEXT,
                holdout_end TEXT,
                holdout_samples INTEGER NOT NULL,
                accuracy REAL,
                roc_auc REAL,
                created_at TEXT NOT NULL
            );
            """
        )
        conn.commit()
    finally:
        conn.close()


def persist_market_recap(db_path: str, recap: dict[str, Any]) -> None:
    conn = connect(db_path)
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO market_recap (
                date, sh_price, sh_change, sz_price, sz_change, cy_price, cy_change,
                total_turnover, limit_ups, limit_downs, promotion_rate, hgt_flow, sgt_flow,
                sentiment, sector_ranking
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                recap.get("date"),
                recap.get("sh_price"),
                recap.get("sh_change"),
                recap.get("sz_price"),
                recap.get("sz_change"),
                recap.get("cy_price"),
                recap.get("cy_change"),
                recap.get("total_turnover"),
                recap.get("limit_ups"),
                recap.get("limit_downs"),
                recap.get("promotion_rate"),
                recap.get("hgt_flow"),
                recap.get("sgt_flow"),
                recap.get("sentiment"),
                recap.get("sector_ranking"),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def persist_limit_up_archive(db_path: str, trade_date: str, rows: Iterable[dict[str, Any]]) -> None:
    conn = connect(db_path)
    try:
        conn.execute("DELETE FROM limit_ups_archive WHERE date = ?", (trade_date,))
        for row in rows:
            conn.execute(
                "INSERT OR REPLACE INTO limit_ups_archive (date, code, name, consecutive_boards) VALUES (?, ?, ?, ?)",
                (
                    trade_date,
                    str(row.get("代码") or row.get("code") or "").zfill(6),
                    row.get("名称") or row.get("name"),
                    int(row.get("连板数") or row.get("consecutive_boards") or 0),
                ),
            )
        conn.commit()
    finally:
        conn.close()


def persist_market_risk(db_path: str, risk: Any) -> None:
    conn = connect(db_path)
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO market_risk (
                trade_date, max_consecutive_boards, market_regime,
                one_to_two_numerator, one_to_two_denominator, one_to_two_rate,
                two_to_three_numerator, two_to_three_denominator, two_to_three_rate,
                f18_policy, f18_risk_budget, f18_low_sample,
                rule_version, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                getattr(risk, "trade_date", None),
                getattr(risk, "max_consecutive_boards", None),
                str(getattr(risk, "market_regime", None)),
                getattr(risk, "one_to_two_numerator", None),
                getattr(risk, "one_to_two_denominator", None),
                getattr(risk, "one_to_two_rate", None),
                getattr(risk, "two_to_three_numerator", None),
                getattr(risk, "two_to_three_denominator", None),
                getattr(risk, "two_to_three_rate", None),
                str(getattr(risk, "f18_policy", None)),
                getattr(risk, "f18_risk_budget", None),
                1 if getattr(risk, "f18_low_sample", False) else 0,
                getattr(risk, "rule_version", None),
                _utc_now_iso(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _obj_get(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(name, default)
    return getattr(obj, name, default)


def persist_execution_plans(db_path: str, plans: Iterable[Any]) -> None:
    deduped: dict[tuple[str, str, str], Any] = {}
    for plan in plans:
        trade_date = str(_obj_get(plan, "trade_date", ""))
        code = str(_obj_get(plan, "code", "")).zfill(6)
        action = str(_obj_get(plan, "action", ""))
        key = (trade_date, code, action)
        prev = deduped.get(key)
        if prev is None:
            deduped[key] = plan
            continue
        prev_price = _obj_get(prev, "trigger_price", None)
        new_price = _obj_get(plan, "trigger_price", None)
        if isinstance(prev_price, (int, float)) and isinstance(new_price, (int, float)):
            if float(new_price) >= float(prev_price):
                deduped[key] = plan
        else:
            deduped[key] = plan
    trade_dates = {trade_date for trade_date, _, _ in deduped}
    conn = connect(db_path)
    try:
        for trade_date in trade_dates:
            conn.execute("DELETE FROM execution_plans WHERE trade_date = ?", (trade_date,))
        for plan in deduped.values():
            conn.execute(
                """
                INSERT INTO execution_plans (
                    trade_date, code, action, trigger_type, trigger_price,
                    reference_price, quantity_pct, valid_from, valid_until,
                    precondition, rule_version, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _obj_get(plan, "trade_date"),
                    str(_obj_get(plan, "code", "")).zfill(6),
                    _obj_get(plan, "action"),
                    _obj_get(plan, "trigger_type"),
                    _obj_get(plan, "trigger_price"),
                    _obj_get(plan, "reference_price"),
                    _obj_get(plan, "quantity_pct"),
                    _obj_get(plan, "valid_from"),
                    _obj_get(plan, "valid_until"),
                    _obj_get(plan, "precondition"),
                    _obj_get(plan, "rule_version"),
                    _utc_now_iso(),
                ),
            )
        conn.commit()
    finally:
        conn.close()
