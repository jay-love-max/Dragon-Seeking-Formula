"""回归测试:observation-only 回放时不得写入发布产物。

根因(2026-06-29 诊断):run_recap() 在 observation_only 判定之前
就调用了 persist_market_recap / persist_limit_up_archive,导致非交易日
--force-non-trading-day 回放留下"有 market_recap、无 candidates"的半写
脏记录,前端默认选中该日期显示空白页。

AGENTS.md 约束:
- 全量首板观察样本(candidate_observations)与最终发布的 Top 5 分开保存;
- 数据缺失/非交易日禁止填成看似有效的 0 后继续发布。

本测试锁定:observation_only=True 时
- market_recap 不写入(发布产物);
- limit_ups_archive 不写入(发布产物,被校准/二板标签消费);
- candidate_observations 仍写入(ML 观察样本,UPSERT 语义);
- recap_runs 标记为 BLOCKED / non-publishable;
- 对照 observation_only=False 时 market_recap 正常写入,确保未改坏正常路径。
"""
import os
import sqlite3
import sys
import tempfile
from contextlib import ExitStack
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

import pandas as pd

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import recap_engine  # noqa: E402
from contracts import FetchResult  # noqa: E402
from tests.fixtures.golden_samples import GOLDEN_2026_06_24  # noqa: E402


def _build_offline_fetches(date_str: str):
    """构造离线 limit_up_pool + index_recap FetchResult,无需网络。"""
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
    return df_pool, limit_up_fetch, index_fetch


def _patch_adapter(stack: ExitStack, df_pool: pd.DataFrame, limit_up_fetch, index_fetch):
    """monkeypatch 所有外部数据源,使 run_recap 离线运行。"""
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
    stack.enter_context(patch.object(recap_engine.ADAPTER, "get_lhb_statistics", return_value=pd.DataFrame(columns=["code"])))
    stack.enter_context(patch.object(recap_engine.ADAPTER, "get_lhb_details", return_value=pd.DataFrame(columns=["code"])))
    stack.enter_context(patch.object(recap_engine, "prefetch_volume_features", return_value={}))


class TestObservationOnlyWrites(TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp_dir.name) / "test_obs.db"
        os.environ["RECAP_DB_PATH"] = str(self.db_path)
        recap_engine.DB_PATH = str(self.db_path)
        recap_engine.init_db()

    def tearDown(self):
        if "RECAP_DB_PATH" in os.environ:
            del os.environ["RECAP_DB_PATH"]
        self.tmp_dir.cleanup()

    def _run(self, observation_only: bool, date_str: str = "2026-06-27"):
        trade_dates = ["2026-06-24", "2026-06-25", "2026-06-26"]
        if date_str not in trade_dates:
            trade_dates.append(date_str)
        df_pool, limit_up_fetch, index_fetch = _build_offline_fetches(date_str)
        with ExitStack() as stack:
            _patch_adapter(stack, df_pool, limit_up_fetch, index_fetch)
            return recap_engine.run_recap(date_str, trade_dates, observation_only=observation_only)

    def _count(self, table, date_col, date_str):
        conn = sqlite3.connect(str(self.db_path))
        try:
            return conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE {date_col}=?", (date_str,)
            ).fetchone()[0]
        finally:
            conn.close()

    def test_observation_only_skips_market_recap(self):
        """observation_only=True 时 market_recap 不得写入(发布产物)。"""
        self._run(observation_only=True)
        self.assertEqual(self._count("market_recap", "date", "2026-06-27"), 0)

    def test_observation_only_skips_limit_ups_archive(self):
        """observation_only=True 时 limit_ups_archive 不得写入(发布产物)。"""
        self._run(observation_only=True)
        self.assertEqual(self._count("limit_ups_archive", "date", "2026-06-27"), 0)

    def test_observation_only_writes_candidate_observations(self):
        """observation_only=True 时 candidate_observations 仍写入(ML 观察样本)。"""
        self._run(observation_only=True)
        self.assertGreater(self._count("candidate_observations", "trade_date", "2026-06-27"), 0)

    def test_observation_only_marks_run_blocked(self):
        """observation_only=True 时 recap_runs 标记 BLOCKED / non-publishable。"""
        self._run(observation_only=True)
        conn = sqlite3.connect(str(self.db_path))
        try:
            row = conn.execute(
                "SELECT status, publishable, failure_code FROM recap_runs "
                "WHERE trade_date=? ORDER BY started_at DESC LIMIT 1",
                ("2026-06-27",),
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(row, ("BLOCKED", 0, "TRADING_DAY_INVALID"))

    def test_observation_only_does_not_write_candidates(self):
        """observation_only=True 时 candidates(Top5 发布表)不得写入。"""
        self._run(observation_only=True)
        self.assertEqual(self._count("candidates", "date", "2026-06-27"), 0)

    def test_normal_recap_writes_market_recap(self):
        """对照:observation_only=False 在交易日时 market_recap 正常写入,确保未改坏正常路径。

        candidates(Top5)的完整写入已由 test_recap_pipeline.test_run_recap_offline_end_to_end
        覆盖(含 UZI monkeypatch);此处只验证 market_recap 发布产物在正常路径下仍被写入。
        """
        # 用交易日 2026-06-26,publish_gate 不阻断,完整写入发布产物。
        self._run(observation_only=False, date_str="2026-06-26")
        self.assertGreater(self._count("market_recap", "date", "2026-06-26"), 0)


if __name__ == "__main__":
    import unittest

    unittest.main()
