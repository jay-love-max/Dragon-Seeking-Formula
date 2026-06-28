"""Tests for GET /api/recap/intraday-execution endpoint."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.api import recap  # noqa: E402


@pytest.fixture
def mock_db_path(tmp_path: Path) -> Path:
    db_path = tmp_path / "recap.db"
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE candidates (
            date TEXT, code TEXT, name TEXT, score INTEGER, price REAL,
            first_seal_time TEXT, blown_count INTEGER, sector TEXT,
            concept TEXT, playbook TEXT, seal_funds REAL,
            turnover REAL, float_mcap REAL, personality_grade TEXT,
            personality_dims TEXT, lhb_gold_net REAL, lhb_death_net REAL,
            lhb_inst_net REAL, block_f16 INTEGER, block_f17 INTEGER,
            block_f18 INTEGER, block_f19 INTEGER, pred_prob REAL,
            PRIMARY KEY (date, code)
        )
    """)
    conn.execute("""
        CREATE TABLE realtime_snapshot (
            code TEXT PRIMARY KEY, name TEXT, price REAL, change_pct REAL,
            turnover REAL, seal_funds REAL, seal_ratio_instant REAL,
            first_seal_time TEXT, blown_count INTEGER DEFAULT 0,
            consecutive_boards INTEGER DEFAULT 0, sector TEXT,
            float_mcap REAL, score_intraday INTEGER, ts TEXT
        )
    """)
    conn.execute("""
        INSERT INTO candidates (date, code, name, score, price, first_seal_time, blown_count, sector, playbook)
        VALUES ('2026-06-26', '000001', '平安银行', 118, 14.93, '093500', 0, '银行', '测试playbook')
    """)
    conn.execute("""
        INSERT INTO candidates (date, code, name, score, price, first_seal_time, blown_count, sector, playbook)
        VALUES ('2026-06-26', '600000', '浦发银行', 125, 18.50, '092500', 0, '银行', '测试playbook2')
    """)
    conn.execute("""
        INSERT INTO realtime_snapshot (code, name, price, change_pct, seal_funds, score_intraday, ts)
        VALUES ('000001', '平安银行', 15.91, 6.5, 120000000.0, 135, '2026-06-26T09:35:00')
    """)
    conn.execute("""
        INSERT INTO realtime_snapshot (code, name, price, change_pct, seal_funds, score_intraday, ts)
        VALUES ('600000', '浦发银行', 20.35, 10.0, 80000000.0, 128, '2026-06-26T09:35:00')
    """)
    conn.commit()
    conn.close()
    return db_path


def test_intraday_execution_returns_top5_with_realtime(monkeypatch, mock_db_path: Path):
    monkeypatch.setattr("app.api.recap.get_recap_db_path", lambda: mock_db_path)
    result = recap.get_intraday_execution()

    assert result["date"] == "2026-06-26"
    assert len(result["candidates"]) == 2
    c1 = next(c for c in result["candidates"] if c["code"] == "000001")
    assert c1["score_intraday"] == 135
    assert c1["change_pct"] == 6.5
    assert c1["price"] == 15.91
    assert c1["seal_funds"] == 120000000.0
    assert c1["score"] == 118
    assert c1["playbook"] == "测试playbook"
    assert "market_brief" in result
    assert result["snapshot_ts"] == "2026-06-26T09:35:00"


def test_intraday_execution_empty_candidates(monkeypatch, tmp_path: Path):
    db_path = tmp_path / "recap.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE candidates (date TEXT, code TEXT, score INTEGER, PRIMARY KEY (date, code))")
    conn.execute("CREATE TABLE realtime_snapshot (code TEXT PRIMARY KEY)")
    conn.commit()
    conn.close()
    monkeypatch.setattr("app.api.recap.get_recap_db_path", lambda: db_path)
    result = recap.get_intraday_execution()
    assert result["date"] is None
    assert result["candidates"] == []


def test_intraday_execution_no_realtime(monkeypatch, mock_db_path: Path):
    conn = sqlite3.connect(mock_db_path)
    conn.execute("DELETE FROM realtime_snapshot")
    conn.commit()
    conn.close()
    monkeypatch.setattr("app.api.recap.get_recap_db_path", lambda: mock_db_path)
    result = recap.get_intraday_execution()
    c1 = next(c for c in result["candidates"] if c["code"] == "000001")
    assert c1["score_intraday"] is None
    assert c1["change_pct"] is None
    assert result["snapshot_ts"] is None
    assert c1["score"] == 118
    assert c1["playbook"] == "测试playbook"


def test_recap_all_returns_without_error(monkeypatch, tmp_path: Path):
    db_path = tmp_path / "recap.db"
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE candidates (
            date TEXT, code TEXT, name TEXT, score INTEGER, price REAL,
            first_seal_time TEXT, blown_count INTEGER, sector TEXT,
            concept TEXT, playbook TEXT, seal_funds REAL,
            turnover REAL, float_mcap REAL, personality_grade TEXT,
            personality_dims TEXT, lhb_gold_net REAL, lhb_death_net REAL,
            lhb_inst_net REAL, block_f16 INTEGER, block_f17 INTEGER,
            block_f18 INTEGER, block_f19 INTEGER, pred_prob REAL,
            PRIMARY KEY (date, code)
        )
    """)
    conn.execute("""
        CREATE TABLE market_recap (
            date TEXT PRIMARY KEY, sentiment TEXT, sh_change REAL,
            sz_change REAL, cy_change REAL, limit_ups INTEGER,
            limit_downs INTEGER, total_turnover REAL, promotion_rate REAL,
            limited_rebound_pct REAL, hgt_flow REAL, sgt_flow REAL,
            sector_ranking TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE uzi_audit (
            date TEXT, code TEXT, name TEXT, average_score REAL,
            val_vote TEXT, mom_vote TEXT, risk_level TEXT,
            summary TEXT, report_path TEXT, analysis_json TEXT
        )
    """)
    conn.execute("""
        INSERT INTO candidates (date, code, name, score, first_seal_time, sector, playbook)
        VALUES ('2026-06-26', '000001', '平安银行', 118, '093500', '银行', '测试playbook')
    """)
    conn.execute("""
        INSERT INTO market_recap (date, sentiment, limit_ups, limit_downs, sector_ranking)
        VALUES ('2026-06-26', '一般', 50, 5, '[]')
    """)
    conn.execute("""
        INSERT INTO uzi_audit (date, code, name, analysis_json)
        VALUES ('2026-06-26', '000001', '平安银行', NULL)
    """)
    conn.commit()
    conn.close()
    monkeypatch.setattr("app.api.recap.get_recap_db_path", lambda: db_path)
    result = recap.get_all_recap_data()
    assert "history" in result
    assert "uzi_audit" in result
    assert "calibration" in result
    assert len(result["history"]) == 1
