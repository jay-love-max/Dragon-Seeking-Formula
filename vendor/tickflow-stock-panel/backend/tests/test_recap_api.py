from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.api import recap  # noqa: E402
from app.config import settings  # noqa: E402


def _create_recap_schema(db_path: Path) -> None:
    """创建复盘 DB 所需的最小表结构(仅 get_all_recap_data 涉及的列)。"""
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS market_recap (
            date TEXT PRIMARY KEY,
            sh_price REAL, sh_change REAL, sz_price REAL, sz_change REAL,
            cy_price REAL, cy_change REAL, total_turnover REAL,
            limit_ups INTEGER, limit_downs INTEGER, promotion_rate REAL,
            hgt_flow REAL, sgt_flow REAL, sentiment TEXT, sector_ranking TEXT
        );
        CREATE TABLE IF NOT EXISTS candidates (
            date TEXT, code TEXT, name TEXT, score INTEGER,
            price REAL, change_pct REAL, turnover REAL, float_mcap REAL,
            seal_funds REAL, seal_ratio REAL, first_seal_time TEXT,
            blown_count INTEGER, consecutive_boards INTEGER,
            sector TEXT, concept TEXT, playbook TEXT,
            pred_prob REAL, personality_grade TEXT, personality_dims TEXT,
            lhb_gold_net REAL, lhb_death_net REAL, lhb_inst_net REAL,
            block_f16 REAL, block_f17 REAL, block_f18 REAL, block_f19 REAL,
            PRIMARY KEY (date, code)
        );
        CREATE TABLE IF NOT EXISTS limit_ups_archive (
            date TEXT, code TEXT, name TEXT, consecutive_boards INTEGER,
            PRIMARY KEY (date, code)
        );
        CREATE TABLE IF NOT EXISTS uzi_audit (
            date TEXT, code TEXT, name TEXT, average_score REAL,
            val_vote TEXT, mom_vote TEXT, risk_level TEXT,
            summary TEXT, report_path TEXT, analysis_json TEXT,
            sector TEXT
        );
        """
    )
    conn.commit()
    conn.close()


class TestManualRecapRunEndpoint(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._orig_data_dir = settings.data_dir
        settings.data_dir = Path(self.tmp.name)

    def tearDown(self):
        settings.data_dir = self._orig_data_dir
        self.tmp.cleanup()

    def test_manual_run_is_disabled_by_default(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(recap.HTTPException) as ctx:
                recap.trigger_recap_run()
        self.assertEqual(ctx.exception.status_code, 403)

    def test_manual_run_rejects_when_lock_is_held(self):
        lock_path = Path(self.tmp.name) / ".recap_run.lock"
        lock_path.write_text(str(os.getpid()), encoding="utf-8")

        with patch.dict(os.environ, {"RECAP_MANUAL_RUN_ENABLED": "true"}):
            with patch.object(recap.subprocess, "run") as run_mock:
                result = recap.trigger_recap_run()

        run_mock.assert_not_called()
        self.assertFalse(result["ok"])
        self.assertEqual(result["returncode"], 409)
        self.assertIn("already running", result["stderr"])
        self.assertTrue(lock_path.exists())

    def test_manual_run_releases_stale_lock(self):
        lock_path = Path(self.tmp.name) / ".recap_run.lock"
        lock_path.write_text("999999", encoding="utf-8")

        with patch.dict(os.environ, {"RECAP_MANUAL_RUN_ENABLED": "true"}):
            with patch.object(
                recap.subprocess,
                "run",
                return_value=SimpleNamespace(returncode=0, stdout="done", stderr=""),
            ) as run_mock:
                result = recap.trigger_recap_run()

        run_mock.assert_called_once()
        self.assertTrue(result["ok"])
        self.assertEqual(result["returncode"], 0)
        self.assertEqual(result["stdout"], "done")
        self.assertFalse(lock_path.exists())


class TestGetAllRecapDataFiltering(unittest.TestCase):
    """验证 /api/recap/all 不返回空 candidates 的脏记录。

    根因:observation-only 回放会写入 market_recap 但不写 candidates,
    产生"有市场、无候选"的半写脏记录。前端默认选中最新(history[0])
    会显示空白页。API 必须过滤掉这类日期。
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "recap.db"
        _create_recap_schema(self.db_path)
        self._orig_get_path = recap.get_recap_db_path

        def _fake_path():
            return self.db_path

        recap.get_recap_db_path = _fake_path

    def tearDown(self):
        recap.get_recap_db_path = self._orig_get_path
        self.tmp.cleanup()

    def _insert_market_recap(self, date_str: str):
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT OR REPLACE INTO market_recap "
            "(date, sh_price, sh_change, sz_price, sz_change, cy_price, cy_change, "
            " total_turnover, limit_ups, limit_downs, promotion_rate, "
            " hgt_flow, sgt_flow, sentiment, sector_ranking) "
            "VALUES (?, 3000, 1.2, 9000, 2.3, 2100, 3.4, 3000, 80, 5, 5.0, 1.1, 0.3, '活跃', '[]')",
            (date_str,),
        )
        conn.commit()
        conn.close()

    def _insert_candidate(self, date_str: str, code: str):
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT OR REPLACE INTO candidates "
            "(date, code, name, score, price, first_seal_time) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (date_str, code, "测试股", 100, 10.0, "093100"),
        )
        conn.commit()
        conn.close()

    def test_excludes_date_with_empty_candidates(self):
        """有 market_recap 但无 candidates 的日期不应出现在 history。"""
        # 2026-06-26: 完整记录(有 market_recap + candidates)
        self._insert_market_recap("2026-06-26")
        self._insert_candidate("2026-06-26", "600001")
        # 2026-06-27: 脏记录(有 market_recap,无 candidates)— 非交易日 observation-only 残留
        self._insert_market_recap("2026-06-27")

        result = recap.get_all_recap_data()

        history_dates = [item["date"] for item in result["history"]]
        self.assertIn("2026-06-26", history_dates)
        self.assertNotIn("2026-06-27", history_dates)

    def test_returns_dates_desc_when_all_valid(self):
        """全部有效记录时按 date DESC 返回。"""
        self._insert_market_recap("2026-06-24")
        self._insert_candidate("2026-06-24", "600001")
        self._insert_market_recap("2026-06-25")
        self._insert_candidate("2026-06-25", "600002")
        self._insert_market_recap("2026-06-26")
        self._insert_candidate("2026-06-26", "600003")

        result = recap.get_all_recap_data()
        history_dates = [item["date"] for item in result["history"]]

        self.assertEqual(history_dates, ["2026-06-26", "2026-06-25", "2026-06-24"])
