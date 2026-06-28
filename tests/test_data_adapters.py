import os
import sys
import unittest
from pathlib import Path

import pandas as pd

# Add src to python path
SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from data_adapters import get_adapter
from data_adapters.a_stock_adapter import AStockDataAdapter
from data_adapters.base_adapter import BaseStockAdapter
from data_adapters.global_stock_adapter import GlobalStockAdapter


class TestDataAdapters(unittest.TestCase):
    def test_adapter_factory(self):
        # Default should be a-stock-data
        if "DATA_PROVIDER" in os.environ:
            del os.environ["DATA_PROVIDER"]

        adapter = get_adapter()
        self.assertIsInstance(adapter, AStockDataAdapter)

        # Set to global
        os.environ["DATA_PROVIDER"] = "global"
        adapter_global = get_adapter()
        self.assertIsInstance(adapter_global, GlobalStockAdapter)

    def test_a_stock_adapter_calendar(self):
        adapter = AStockDataAdapter()
        result = adapter.get_trading_days(offset=10)
        # 适配器返回 FetchResult(方案 7.1);离线网络下可能 UNAVAILABLE,
        # 但不得退化为伪装的工作日列表(方案 8.2)
        from contracts import FetchResult
        self.assertIsInstance(result, FetchResult)
        self.assertEqual(result.dataset_name, "trading_days")
        if result.is_ok:
            self.assertFalse(result.payload.empty)
            self.assertIn("trade_date", result.payload.columns)
            for d in result.payload["trade_date"].tolist():
                self.assertRegex(d, r"\d{4}-\d{2}-\d{2}")

    def test_global_adapter_calendar(self):
        adapter = GlobalStockAdapter()
        # Mock index chart request to prevent network flake, or test basic instantiation
        self.assertIsInstance(adapter, BaseStockAdapter)
        from contracts import FetchResult
        result = adapter.get_trading_days(offset=5)
        self.assertIsInstance(result, FetchResult)
        self.assertEqual(result.dataset_name, "trading_days")

    def test_a_stock_adapter_finance_fields(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fin_dir = root / "financials"
            (fin_dir / "metrics").mkdir(parents=True, exist_ok=True)
            (fin_dir / "income").mkdir(parents=True, exist_ok=True)
            (fin_dir / "balance_sheet").mkdir(parents=True, exist_ok=True)

            pd.DataFrame(
                {
                    "symbol": ["600519.SH"],
                    "roe_waa": [18.5],
                    "eps_basic": [2.45],
                }
            ).to_parquet(str(fin_dir / "metrics" / "part.parquet"), engine="pyarrow")

            pd.DataFrame(
                {
                    "symbol": ["600519.SH"],
                    "net_profit": [185.0],
                    "revenue": [1000.0],
                }
            ).to_parquet(str(fin_dir / "income" / "part.parquet"), engine="pyarrow")

            pd.DataFrame(
                {
                    "symbol": ["600519.SH"],
                    "total_equity": [1000.0],
                    "shares_total": [100.0],
                    "current_liability": [200.0],
                    "noncurrent_liability": [100.0],
                    "total_assets": [1500.0],
                    "goodwill": [60.0],
                    "accounts_receivable": [150.0],
                }
            ).to_parquet(str(fin_dir / "balance_sheet" / "part.parquet"), engine="pyarrow")

            original_data_dir = os.environ.get("DATA_DIR")
            os.environ["DATA_DIR"] = str(root)
            try:
                adapter = AStockDataAdapter()
                res = adapter.get_finance_data("600519")
            finally:
                if original_data_dir is None:
                    os.environ.pop("DATA_DIR", None)
                else:
                    os.environ["DATA_DIR"] = original_data_dir

            self.assertEqual(res["jinglirun"], 185.0)
            self.assertEqual(res["jingzichan"], 1000.0)
            self.assertEqual(res["zhuyingshouru"], 1000.0)
            self.assertEqual(res["zongguben"], 100.0)
            self.assertEqual(res["liudongfuzhai"], 200.0)
            self.assertEqual(res["changqifuzhai"], 100.0)
            self.assertEqual(res["zongzichan"], 1500.0)
            self.assertEqual(res["goodwill"], 60.0)
            self.assertEqual(res["accounts_receivable"], 150.0)
            self.assertEqual(res["asset_liability_ratio"], 20.0)
            self.assertEqual(res["goodwill_ratio"], 6.0)
            self.assertEqual(res["receivable_ratio"], 10.0)
if __name__ == '__main__':
    unittest.main()
