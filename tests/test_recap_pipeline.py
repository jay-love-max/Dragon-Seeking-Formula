import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

# Add src to python path
SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import recap_engine


class TestRecapPipeline(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp_dir.name) / "test_recap.db"
        # Force recap_engine to use our temporary database via environment variable
        os.environ["RECAP_DB_PATH"] = str(self.db_path)
        # Reload DB_PATH in the module
        recap_engine.DB_PATH = str(self.db_path)

    def tearDown(self):
        if "RECAP_DB_PATH" in os.environ:
            del os.environ["RECAP_DB_PATH"]
        self.tmp_dir.cleanup()

    def test_database_initialization(self):
        # Run DB initialization
        recap_engine.init_db()

        # Check if the database file was created
        self.assertTrue(self.db_path.exists())

        # Verify tables
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        tables = ["market_recap", "candidates", "limit_ups_archive", "uzi_audit", "model_runs"]
        for table in tables:
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
            )
            row = cursor.fetchone()
            self.assertIsNotNone(row, f"Table {table} should exist")
            self.assertEqual(row[0], table)

        # Check columns on candidates table
        cursor.execute("PRAGMA table_info(candidates)")
        cols = [col[1] for col in cursor.fetchall()]
        self.assertIn("pred_prob", cols)

        # Check columns on uzi_audit table
        cursor.execute("PRAGMA table_info(uzi_audit)")
        uzi_cols = [col[1] for col in cursor.fetchall()]
        self.assertIn("analysis_json", uzi_cols)

        conn.close()

    def test_time_to_seconds(self):
        # 09:25:00 is reference (0 seconds)
        self.assertEqual(recap_engine.time_to_seconds("092500"), 0)
        # 09:30:00 is 5 mins (300 seconds)
        self.assertEqual(recap_engine.time_to_seconds("093000"), 300)
        # Invalid time should fallback to default (0)
        self.assertEqual(recap_engine.time_to_seconds("invalid"), 0)

    def test_local_finance_data_read(self):
        # Create mock financials metrics, income, and balance_sheet parquet files
        import pandas as pd

        fin_dir = Path(self.tmp_dir.name) / "financials"

        # 1. Metrics
        m_dir = fin_dir / "metrics"
        m_dir.mkdir(parents=True, exist_ok=True)
        pd.DataFrame({
            "symbol": ["600519.SH", "000001.SZ"],
            "roe_waa": [18.5, 12.3],
            "eps_basic": [2.45, 0.88]
        }).to_parquet(str(m_dir / "part.parquet"), engine="pyarrow")

        # 2. Income
        i_dir = fin_dir / "income"
        i_dir.mkdir(parents=True, exist_ok=True)
        pd.DataFrame({
            "symbol": ["600519.SH", "000001.SZ"],
            "net_profit": [185.0, 123.0],
            "revenue": [1000.0, 800.0]
        }).to_parquet(str(i_dir / "part.parquet"), engine="pyarrow")

        # 3. Balance Sheet
        b_dir = fin_dir / "balance_sheet"
        b_dir.mkdir(parents=True, exist_ok=True)
        pd.DataFrame({
            "symbol": ["600519.SH", "000001.SZ"],
            "total_equity": [1000.0, 1000.0],
            "shares_total": [100.0, 100.0],
            "current_liability": [200.0, 150.0],
            "noncurrent_liability": [100.0, 50.0],
            "total_assets": [1300.0, 1200.0]
        }).to_parquet(str(b_dir / "part.parquet"), engine="pyarrow")

        # Set env DATA_DIR
        os.environ["DATA_DIR"] = self.tmp_dir.name

        try:
            # Call ADAPTER.get_finance_data
            res_sh = recap_engine.ADAPTER.get_finance_data("600519")
            res_sz = recap_engine.ADAPTER.get_finance_data("000001")

            self.assertEqual(res_sh.get("jinglirun"), 185.0)
            self.assertEqual(res_sh.get("jingzichan"), 1000.0)
            self.assertEqual(res_sh.get("zhuyingshouru"), 1000.0)
            self.assertEqual(res_sh.get("zongguben"), 100.0)
            self.assertEqual(res_sh.get("liudongfuzhai"), 200.0)
            self.assertEqual(res_sh.get("changqifuzhai"), 100.0)
            self.assertEqual(res_sh.get("zongzichan"), 1300.0)
            self.assertEqual(res_sh.get("roe"), 18.5)
            self.assertEqual(res_sh.get("eps"), 2.45)

            self.assertEqual(res_sz.get("roe"), 12.3)
            self.assertEqual(res_sz.get("eps"), 0.88)
        finally:
            if "DATA_DIR" in os.environ:
                del os.environ["DATA_DIR"]

    def test_finance_trap_helper(self):
        safe = {
            "asset_liability_ratio": 20.0,
            "goodwill_ratio": 6.0,
            "receivable_ratio": 10.0,
            "jingzichan": 1000.0,
            "zongzichan": 1500.0,
            "goodwill": 60.0,
            "accounts_receivable": 150.0,
            "liudongfuzhai": 200.0,
            "changqifuzhai": 100.0,
        }
        safe_result = recap_engine._evaluate_finance_trap("贵州茅台", safe)
        self.assertEqual(safe_result["risk_level"], "安全")
        self.assertEqual(safe_result["risk_flags"], [])

        risky = {
            "jingzichan": 100.0,
            "zongzichan": 100.0,
            "goodwill": 40.0,
            "accounts_receivable": 60.0,
            "liudongfuzhai": 80.0,
            "changqifuzhai": 30.0,
        }
        risky_result = recap_engine._evaluate_finance_trap("某股", risky)
        self.assertEqual(risky_result["risk_level"], "极度危险")
        self.assertIn("high_liability", risky_result["risk_flags"])
        self.assertIn("high_goodwill", risky_result["risk_flags"])
        self.assertIn("high_receivable", risky_result["risk_flags"])

        st_result = recap_engine._evaluate_finance_trap("*ST测试", safe)
        self.assertEqual(st_result["risk_level"], "极度危险")
        self.assertIn("st", st_result["risk_flags"])

    def test_local_uzi_audit_mentions_trap_reasons(self):
        recap_engine.init_db()
        original_finance = recap_engine.ADAPTER.get_finance_data
        original_loader = recap_engine._load_shared_ai_settings
        recap_engine.ADAPTER.get_finance_data = lambda code: {
            "jinglirun": 50.0,
            "jingzichan": 100.0,
            "zongguben": 10.0,
            "liudongfuzhai": 80.0,
            "changqifuzhai": 30.0,
            "zongzichan": 100.0,
            "goodwill": 40.0,
            "accounts_receivable": 60.0,
        }
        recap_engine._load_shared_ai_settings = lambda: {
            "provider": "openai_compat",
            "base_url": "https://example.invalid/v1",
            "api_key": "",
            "model": "gpt-test",
            "user_agent": "UA/1.0",
        }
        conn = sqlite3.connect(str(self.db_path))
        try:
            results = recap_engine.run_real_uzi_audit(
                conn,
                "2026-06-26",
                [
                    {
                        "code": "600519",
                        "name": "测试股份",
                        "first_seal_time": "093000",
                        "turnover_pct": 6.2,
                        "sector": "白酒",
                    }
                ],
                uzi_path="/nonexistent/UZI-Skill",
            )

            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["risk_level"], "极度危险")
            self.assertIn("资产负债率", results[0]["summary"])
            self.assertIn("商誉", results[0]["summary"])
            self.assertIn("应收账款", results[0]["summary"])

            cursor = conn.cursor()
            cursor.execute(
                "SELECT summary, analysis_json FROM uzi_audit WHERE date = ? AND code = ?",
                ("2026-06-26", "600519"),
            )
            stored = cursor.fetchone()
            self.assertIsNotNone(stored)
            self.assertIn("资产负债率", stored[0])
            analysis = json.loads(stored[1])
            self.assertIn("18_trap", analysis["dim_commentary"])
            self.assertIn("资产负债率", analysis["dim_commentary"]["18_trap"])
        finally:
            conn.close()
            recap_engine.ADAPTER.get_finance_data = original_finance
            recap_engine._load_shared_ai_settings = original_loader

    def test_build_uzi_candidates_filters_to_published_top5(self):
        df_1b = recap_engine.pd.DataFrame([
            {
                "code": "000001",
                "name": "候选A",
                "first_seal_time": "093000",
                "turnover_pct": 1.2,
                "sector": "行业A",
            },
            {
                "code": "000002",
                "name": "候选B",
                "first_seal_time": "093100",
                "turnover_pct": 2.3,
                "sector": "行业B",
            },
        ])
        ranked = [
            SimpleNamespace(code="000002", publication_status="PUBLISHED_TOP5"),
            SimpleNamespace(code="000001", publication_status="RANKED_OUTSIDE_TOP5"),
        ]

        candidates = recap_engine._build_uzi_candidates(df_1b, ranked)

        self.assertEqual([c["code"] for c in candidates], ["000002"])
        self.assertEqual(candidates[0]["first_seal_time"], "09:31:00")

    def test_real_uzi_audit_falls_back_to_local_rules_without_api_key(self):
        recap_engine.init_db()
        conn = sqlite3.connect(str(self.db_path))
        try:
            results = recap_engine.run_real_uzi_audit(
                conn,
                "2026-06-26",
                [
                    {"code": "600519", "name": "贵州茅台", "first_seal_time": "093000", "turnover_pct": 6.2, "sector": "白酒"},
                ],
                uzi_path="/nonexistent/UZI-Skill",
            )

            self.assertEqual(len(results), 1)
            row = results[0]
            self.assertEqual(row["code"], "600519")
            self.assertIn(row["val_vote"], {"多头", "空头", "观望"})
            self.assertIn(row["mom_vote"], {"多头", "空头", "观望"})
            self.assertIn(row["risk_level"], {"安全", "危险", "极度危险"})

            cursor = conn.cursor()
            cursor.execute(
                "SELECT name, average_score, val_vote, mom_vote, risk_level, summary, analysis_json FROM uzi_audit WHERE date = ? AND code = ?",
                ("2026-06-26", "600519"),
            )
            stored = cursor.fetchone()
            self.assertIsNotNone(stored)
            self.assertEqual(stored[0], "贵州茅台")
            self.assertIsInstance(stored[1], float)
            self.assertIn("【巴菲特价值席位】", stored[5])
            analysis = json.loads(stored[6])
            self.assertIn("coverage", analysis)
            self.assertIn("dim_commentary", analysis)
        finally:
            conn.close()

    def test_shared_ai_uzi_audit_uses_openai_and_persists(self):
        recap_engine.init_db()
        import types

        calls = {}

        class DummyCompletions:
            def create(self, **kwargs):
                calls.update(kwargs)
                return types.SimpleNamespace(
                    choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=json.dumps({
                        "results": [{
                            "code": "600519",
                            "name": "贵州茅台",
                            "average_score": 91.5,
                            "val_vote": "多头",
                            "mom_vote": "观望",
                            "risk_level": "安全",
                            "summary": "【巴菲特价值席位】AAA\n【赵老哥游资席位】BBB\n【大空头排雷席位】CCC",
                            "analysis": {"core_conclusion": "ok", "highlights": [], "gaps_preview": [], "coverage": {"filled": 1, "total": 1, "label": "1/1"}},
                            "report_path": ""
                        }]
                    })))]
                )

        class DummyClient:
            def __init__(self, **kwargs):
                calls["client_kwargs"] = kwargs
                self.chat = types.SimpleNamespace(completions=DummyCompletions())

        original_client = recap_engine.OpenAI
        original_loader = recap_engine._load_shared_ai_settings
        try:
            recap_engine._load_shared_ai_settings = lambda: {
                "provider": "openai_compat",
                "base_url": "https://example.invalid/v1",
                "api_key": "test-key",
                "model": "gpt-test",
                "user_agent": "UA/1.0",
            }
            recap_engine.OpenAI = DummyClient

            conn = sqlite3.connect(str(self.db_path))
            try:
                results = recap_engine.run_real_uzi_audit(
                    conn,
                    "2026-06-26",
                    [{"code": "600519", "name": "贵州茅台", "first_seal_time": "093000", "turnover_pct": 6.2, "sector": "白酒"}],
                    uzi_path="/unused",
                )
                self.assertEqual(len(results), 1)
                self.assertEqual(results[0]["average_score"], 91.5)
                self.assertIn("response_format", calls)
                self.assertEqual(calls["client_kwargs"]["api_key"], "test-key")

                cur = conn.cursor()
                cur.execute(
                    "SELECT analysis_json FROM uzi_audit WHERE date = ? AND code = ?",
                    ("2026-06-26", "600519"),
                )
                stored = cur.fetchone()
                self.assertIsNotNone(stored)
                self.assertEqual(json.loads(stored[0])["core_conclusion"], "ok")
            finally:
                conn.close()
        finally:
            recap_engine.OpenAI = original_client
            recap_engine._load_shared_ai_settings = original_loader

    def test_uzi_ai_call_runs_outside_caller_write_transaction(self):
        recap_engine.init_db()
        conn = sqlite3.connect(str(self.db_path))
        observed = []
        original_loader = recap_engine._load_shared_ai_settings
        original_call = recap_engine._call_uzi_audit_model
        try:
            conn.execute("INSERT INTO market_recap (date) VALUES (?)", ("2026-06-26",))
            self.assertTrue(conn.in_transaction)
            recap_engine._load_shared_ai_settings = lambda: {
                "provider": "openai_compat",
                "base_url": "https://example.invalid/v1",
                "api_key": "test-key",
                "model": "gpt-test",
                "user_agent": "UA/1.0",
            }

            def fake_call(_payload):
                observed.append(conn.in_transaction)
                return {
                    "results": [{
                        "code": "600519",
                        "name": "贵州茅台",
                        "average_score": 80.0,
                        "val_vote": "多头",
                        "mom_vote": "观望",
                        "risk_level": "安全",
                        "summary": "审计完成",
                        "analysis": {},
                    }]
                }

            recap_engine._call_uzi_audit_model = fake_call
            recap_engine.run_real_uzi_audit(
                conn,
                "2026-06-26",
                [{"code": "600519", "name": "贵州茅台", "sector": "白酒"}],
                uzi_path="/unused",
            )

            self.assertEqual(observed, [False])
        finally:
            recap_engine._load_shared_ai_settings = original_loader
            recap_engine._call_uzi_audit_model = original_call
            conn.close()

    def test_model_run_metadata_is_persisted(self):
        recap_engine.init_db()
        persist = getattr(recap_engine, "persist_model_run", None)
        self.assertIsNotNone(persist)
        conn = sqlite3.connect(str(self.db_path))
        try:
            persist(
                conn,
                "2026-06-26",
                {
                    "model_version": "test-model",
                    "status": "evaluated",
                    "train_start": "2026-06-01",
                    "train_end": "2026-06-20",
                    "train_samples": 100,
                    "holdout_start": "2026-06-23",
                    "holdout_end": "2026-06-25",
                    "holdout_samples": 20,
                    "accuracy": 0.7,
                    "roc_auc": 0.75,
                },
            )
            row = conn.execute(
                "SELECT model_version, train_end, holdout_start, accuracy, roc_auc FROM model_runs WHERE date = ?",
                ("2026-06-26",),
            ).fetchone()
            self.assertEqual(row, ("test-model", "2026-06-20", "2026-06-23", 0.7, 0.75))
        finally:
            conn.close()

    def test_safe_helpers(self):
        self.assertEqual(recap_engine._safe_int("123"), 123)
        self.assertEqual(recap_engine._safe_int(None, default=9), 9)
        self.assertEqual(recap_engine._safe_float("1.23"), 1.23)
        self.assertEqual(recap_engine._safe_float(None), None)
        self.assertEqual(recap_engine._fmt_num("1.234"), "1.23")
        self.assertEqual(recap_engine._fmt_pct("0.123"), "0.1%")
        self.assertEqual(recap_engine._fmt_yi("123000000"), "1.23亿")

    def test_run_recap_offline_end_to_end(self):
        from contextlib import ExitStack
        from unittest.mock import patch

        import pandas as pd

        from contracts import FetchResult
        from tests.fixtures.golden_samples import GOLDEN_2026_06_24, first_board_record

        date_str = "2026-06-24"
        trade_dates = pd.bdate_range(end="2026-06-23", periods=20).strftime("%Y-%m-%d").tolist()
        trade_dates.append(date_str)
        recap_engine.init_db()

        recap_row = {
            "sh_price": 3000.0,
            "sh_change": 1.2,
            "sz_price": 9000.0,
            "sz_change": 2.3,
            "cy_price": 2100.0,
            "cy_change": 3.4,
            "total_turnover": 2.9,
            "limit_ups": 5,
            "limit_downs": 2,
            "promotion_rate": 0.5,
            "hgt_flow": 1.1e11,
            "sgt_flow": 3.3e10,
            "sentiment": "活跃",
            "sector_ranking": json.dumps([]),
        }

        for day_idx, trade_date in enumerate(trade_dates[:-1]):
            recap_engine.persist_market_recap(recap_engine.DB_PATH, {"date": trade_date, **recap_row})
            for row_idx in range(6):
                code = f"{600100 + day_idx * 10 + row_idx:06d}"
                seed_row = first_board_record(
                    code,
                    f"训练{code}",
                    seal_funds_yuan=60_000_000 + row_idx * 2_000_000,
                    blown_count=row_idx % 3,
                    first_seal_time=["09:31:00", "09:35:00", "09:40:00", "09:45:00", "09:50:00", "09:55:00"][row_idx],
                    float_mcap_yuan=8_000_000_000 + row_idx * 100_000_000,
                    turnover_pct=6.0 + row_idx,
                    change_pct=10.0,
                    sector="电子" if row_idx % 2 == 0 else "半导体",
                    trade_date=trade_date,
                )
                recap_engine.persist_observation(
                    recap_engine.DB_PATH,
                    seed_row,
                    label_next_2board=1 if (day_idx + row_idx) % 2 == 0 else 0,
                )

        df_pool = pd.DataFrame(
            [
                {
                    "code": r["code"],
                    "name": r["name"],
                    "trade_date": r["trade_date"],
                    "price": r["price"],
                    "change_pct": r["change_pct"],
                    "turnover_pct": r["turnover_pct"],
                    "float_mcap_yuan": r["float_mcap_yuan"],
                    "seal_funds_yuan": r["seal_funds_yuan"],
                    "first_seal_time": r["first_seal_time"],
                    "blown_count": r["blown_count"],
                    "consecutive_boards": r["consecutive_boards"],
                    "is_st": r["is_st"],
                    "sector": r["sector"],
                    "concept": f"题材{i + 1}",
                }
                for i, r in enumerate(GOLDEN_2026_06_24)
            ]
        )
        index_payload = pd.DataFrame(
            [
                {"index": "sh", "price": 3000.0, "change_pct": 1.2, "amount_yuan": 1.1e12},
                {"index": "sz", "price": 9000.0, "change_pct": 2.3, "amount_yuan": 1.4e12},
                {"index": "cy", "price": 2100.0, "change_pct": 3.4, "amount_yuan": 0.8e12},
            ]
        )
        limit_up_fetch = FetchResult.ok(
            dataset_name="limit_up_pool",
            provider="offline",
            requested_trade_date=date_str,
            as_of=date_str,
            payload=df_pool,
            schema_version=1,
        )
        index_fetch = FetchResult.ok(
            dataset_name="index_recap",
            provider="offline",
            requested_trade_date=date_str,
            as_of=date_str,
            payload=index_payload,
            schema_version=1,
        )

        def fake_run_real_uzi_audit(conn, audit_date, candidates, uzi_path):
            results = []
            for idx, cand in enumerate(candidates):
                summary = f"{cand['name']} offline audit"
                conn.execute(
                    """
                    INSERT INTO uzi_audit (
                        date, code, name, average_score, val_vote, mom_vote,
                        risk_level, summary, report_path, analysis_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        audit_date,
                        cand["code"],
                        cand["name"],
                        80.0 - idx,
                        "多头",
                        "观望",
                        "安全",
                        summary,
                        "",
                        json.dumps({"offline": True, "sector": cand.get("sector", "")}, ensure_ascii=False),
                    ),
                )
                results.append(
                    {
                        "code": cand["code"],
                        "name": cand["name"],
                        "average_score": 80.0 - idx,
                        "val_vote": "多头",
                        "mom_vote": "观望",
                        "risk_level": "安全",
                        "summary": summary,
                        "report_path": "",
                    }
                )
            conn.commit()
            return results


        with ExitStack() as stack:
            stack.enter_context(patch.object(recap_engine, "run_real_uzi_audit", side_effect=fake_run_real_uzi_audit))
            stack.enter_context(patch.object(recap_engine, "fetch_ths_reasons", return_value={}))
            stack.enter_context(patch.object(recap_engine, "get_index_recap_fetchresult", return_value=index_fetch))
            stack.enter_context(patch.object(recap_engine.ADAPTER, "get_limit_up_pool", return_value=limit_up_fetch))
            stack.enter_context(patch.object(recap_engine.ADAPTER, "get_limit_down_pool", return_value=pd.DataFrame()))
            stack.enter_context(
                patch.object(
                    recap_engine.ADAPTER,
                    "get_concept_reasons",
                    return_value={r["code"]: r["concept"] for r in df_pool.to_dict("records")},
                )
            )
            stack.enter_context(
                patch.object(recap_engine.ADAPTER, "get_lhb_statistics", return_value=pd.DataFrame(columns=["code"]))
            )
            stack.enter_context(
                patch.object(recap_engine.ADAPTER, "get_lhb_details", return_value=pd.DataFrame(columns=["code"]))
            )

            ok = recap_engine.run_recap(date_str, trade_dates)

        self.assertTrue(ok)

        conn = sqlite3.connect(str(self.db_path))
        try:
            run_row = conn.execute(
                "SELECT status, publishable, failure_code FROM recap_runs WHERE trade_date=? ORDER BY started_at DESC LIMIT 1",
                (date_str,),
            ).fetchone()
            self.assertEqual(run_row, ("COMPLETED", 1, None))
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM limit_ups_archive WHERE date=?", (date_str,)).fetchone()[0],
                len(df_pool),
            )
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM candidate_observations WHERE trade_date=?", (date_str,)).fetchone()[0],
                len(df_pool),
            )
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM candidates WHERE date=?", (date_str,)).fetchone()[0],
                len(df_pool),
            )
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM market_risk WHERE trade_date=?", (date_str,)).fetchone()[0],
                1,
            )
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM uzi_audit WHERE date=?", (date_str,)).fetchone()[0],
                len(df_pool),
            )
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM source_snapshots WHERE run_id IN (SELECT run_id FROM recap_runs WHERE trade_date=? )", (date_str,)).fetchone()[0] > 0,
                True,
            )
            candidate_row = conn.execute(
                """
                SELECT personality_grade, personality_dims, block_f16, block_f17, block_f18, block_f19, pred_prob, score
                  FROM candidates
                 WHERE date=?
                 ORDER BY score DESC
                 LIMIT 1
                """,
                (date_str,),
            ).fetchone()
            self.assertIsNotNone(candidate_row)
            self.assertIsNotNone(candidate_row[0])
            self.assertIsNotNone(candidate_row[1])
            self.assertTrue(all(v is not None for v in candidate_row[2:6]))
            self.assertGreaterEqual(candidate_row[7], 0)
            self.assertLessEqual(candidate_row[7], 150)
            self.assertIsNotNone(candidate_row[6])
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM execution_plans WHERE trade_date=?", (date_str,)).fetchone()[0],
                0,
            )
        finally:
            conn.close()



if __name__ == "__main__":
    unittest.main()


def test_preprocess_features_includes_execution_profile_columns():
    import pandas as pd

    df = pd.DataFrame(
        [
            {
                "first_seal_time": "093000",
                "blown_count": 1,
                "turnover": 6.2,
                "float_mcap": 12.0,
                "seal_funds": 1.2,
                "seal_ratio": 10.0,
                "price": 10.0,
                "change_pct": 9.9,
                "score": 88,
                "sh_change": 1.0,
                "sz_change": 1.0,
                "cy_change": 1.0,
                "total_turnover": 1000.0,
                "limit_ups": 50,
                "limit_downs": 5,
                "promotion_rate": 12.5,
                "sentiment": "活跃",
                "sector": "白酒",
            }
        ]
    )
    sector_encoding = {"means": {"白酒": 0.5}, "global_mean": 0.3}
    X = recap_engine.preprocess_features(df, sector_encoding)
    for col in ["execution_slippage_bp", "t1_tradeable", "execution_penalty"]:
        assert col in X.columns
    assert X["t1_tradeable"].iloc[0] == 1
def test_preprocess_features_invalid_first_seal_time_is_not_tradeable():
    import pandas as pd

    df = pd.DataFrame(
        [
            {
                "first_seal_time": "invalid",
                "blown_count": 0,
                "turnover": 6.2,
                "float_mcap": 12.0,
                "seal_funds": 1.2,
                "seal_ratio": 10.0,
                "price": 10.0,
                "change_pct": 9.9,
                "score": 88,
                "sh_change": 1.0,
                "sz_change": 1.0,
                "cy_change": 1.0,
                "total_turnover": 1000.0,
                "limit_ups": 50,
                "limit_downs": 5,
                "promotion_rate": 12.5,
                "sentiment": "活跃",
                "sector": "白酒",
            }
        ]
    )
    sector_encoding = {"means": {"白酒": 0.5}, "global_mean": 0.3}
    X = recap_engine.preprocess_features(df, sector_encoding)

    assert X["t1_tradeable"].iloc[0] == 0
    assert X["execution_slippage_bp"].iloc[0] == 26.0
    assert X["execution_penalty"].iloc[0] == 38.0


def test_recap_applies_realtime_snapshot_backfill():
    import pandas as pd

    df = pd.DataFrame(
        [
            {
                "code": "600519",
                "name": "茅台",
                "price": None,
                "change_pct": None,
                "turnover_pct": None,
                "float_mcap_yuan": None,
                "seal_funds_yuan": None,
                "first_seal_time": "",
                "blown_count": None,
                "sector": "",
                "consecutive_boards": 1,
            }
        ]
    )
    snapshot = {
        "600519": {
            "name": "贵州茅台",
            "price": 1500.0,
            "change_pct": 9.98,
            "turnover": 5.6,
            "seal_funds": 321.0,
            "first_seal_time": "093000",
            "blown_count": 0,
            "sector": "白酒",
            "float_mcap": 1800.0,
            "quality_state": "complete",
            "missing_fields": "",
        }
    }

    result = recap_engine._apply_realtime_snapshot(df, snapshot)
    row = result.iloc[0]

    assert row["name"] == "贵州茅台"
    assert row["price"] == 1500.0
    assert row["change_pct"] == 9.98
    assert row["turnover_pct"] == 5.6
    assert row["float_mcap_yuan"] == 1800.0
    assert row["seal_funds_yuan"] == 321.0
    assert row["first_seal_time"] == "093000"
    assert row["blown_count"] == 0
    assert row["sector"] == "白酒"


def test_expanding_sector_encoding_uses_only_earlier_dates():
    import pandas as pd

    rows = pd.DataFrame(
        {
            "date": ["2026-06-01", "2026-06-01", "2026-06-02", "2026-06-02", "2026-06-03"],
            "sector": ["A", "B", "A", "B", "A"],
            "target": [1, 0, 0, 1, 1],
        }
    )
    encoder = getattr(
        recap_engine,
        "build_expanding_sector_encoding",
        lambda frame: (pd.Series([-1.0] * len(frame)), {}),
    )

    encoded, inference_encoding = encoder(rows)

    assert encoded.tolist() == [0.5, 0.5, 1.0, 0.0, 0.5]
    assert inference_encoding["means"]["A"] == 2 / 3
    assert inference_encoding["means"]["B"] == 0.5
    assert inference_encoding["global_mean"] == 0.6


def test_model_evaluation_uses_latest_dates_as_holdout():
    import pandas as pd

    dates = pd.Series(
        [date for date in ["2026-06-01", "2026-06-02", "2026-06-03", "2026-06-04", "2026-06-05"] for _ in range(8)]
    )
    X = pd.DataFrame({"signal": list(range(40))})
    y = pd.Series([0, 1] * 20)
    evaluator = getattr(recap_engine, "evaluate_temporal_holdout", None)

    assert evaluator is not None
    metrics = evaluator(X, y, dates)

    assert metrics["status"] == "evaluated"
    assert metrics["train_end"] == "2026-06-04"
    assert metrics["holdout_start"] == "2026-06-05"
    assert metrics["holdout_samples"] == 8
    assert 0.0 <= metrics["accuracy"] <= 1.0
    assert 0.0 <= metrics["roc_auc"] <= 1.0


def test_holdout_sector_encoding_is_fitted_only_on_training_rows():
    import pandas as pd

    y = pd.Series([0, 0, 1, 1])
    sectors = pd.Series(["A", "B", "A", "A"])
    train_mask = pd.Series([True, True, False, False])
    builder = getattr(recap_engine, "build_training_sector_encoding", None)

    assert builder is not None
    encoding = builder(y, sectors, train_mask)

    assert encoding["means"] == {"A": 0.0, "B": 0.0}
    assert encoding["global_mean"] == 0.0
