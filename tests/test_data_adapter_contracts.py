"""Phase 1 数据契约测试 — 适配器返回 FetchResult,禁止写零伪装失败。

覆盖方案 7.1/7.4 与 Phase 1 验收:
- 指数请求失败不再写成 {"price": 0.0, "change": 0.0};
- 交易日历失败不再退化为工作日;
- 错日期涨停池被拒绝(as_of 不等于请求交易日);
- 关键来源不可用时整体发布闸门 publishable=False。

所有用例本地、确定,不依赖实时网络(AGENTS.md)。
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

from contracts import FetchResult
from data_adapters.a_stock_adapter import AStockDataAdapter
from rule_contract import DataStatus


def _ok_index_recap() -> FetchResult:
    """构造一个合法的指数 FetchResult(供消费侧解包测试)。"""
    payload = pd.DataFrame(
        [
            {"index": "sh", "price": 3200.0, "change_pct": 1.2, "amount_yuan": 4.0e11},
            {"index": "sz", "price": 10500.0, "change_pct": 0.8, "amount_yuan": 5.0e11},
            {"index": "cy", "price": 2100.0, "change_pct": -0.3, "amount_yuan": 2.0e11},
        ]
    )
    return FetchResult.ok(
        dataset_name="index_recap",
        provider="mootdx",
        requested_trade_date="2026-06-24",
        as_of="2026-06-24",
        payload=payload,
        schema_version=1,
    )


class TestIndexRecapNoWriteZero(unittest.TestCase):
    """方案 7.4.7:关键输入使用了"默认 0"代替缺失 -> publishable=False。

    旧实现 `get_index_recap` 在异常分支写 `{"price": 0.0, "change": 0.0}`,
    把"请求失败"伪装成"平收平盘",违反 AGENTS.md
    "数据缺失、过期或请求失败时,禁止填成看似有效的 0 后继续发布"。
    """

    def test_index_client_raises_returns_unavailable_not_zeros(self):
        adapter = AStockDataAdapter()
        # mootdx Quotes.factory 在指数查询时抛异常
        with patch("data_adapters.a_stock_adapter.Quotes") as mock_quotes:
            mock_quotes.factory.side_effect = RuntimeError("mootdx unreachable")
            result = adapter.get_index_recap("2026-06-24")

        self.assertIsInstance(result, FetchResult)
        self.assertEqual(result.status, DataStatus.UNAVAILABLE)
        self.assertEqual(result.row_count, 0)
        self.assertTrue(result.payload.empty)
        self.assertIsNotNone(result.error_code)
        self.assertNotEqual(result.error_code, "")

    def test_index_no_rows_for_date_returns_unavailable_not_zeros(self):
        """旧代码在 `matching_rows.empty` 时写 0.0;必须改为 UNAVAILABLE。"""
        adapter = AStockDataAdapter()
        bars = pd.DataFrame(
            {"close": [3200.0, 3180.0], "amount": [1e11, 9e10], "open": [3190.0, 3170.0]},
            index=pd.to_datetime(["2026-06-23", "2026-06-24"]),
        )
        client = MagicMock()
        client.index.return_value = bars
        with patch("data_adapters.a_stock_adapter.Quotes") as mock_quotes:
            mock_quotes.factory.return_value = client
            result = adapter.get_index_recap("2026-06-19")  # 请求日历中不存在

        self.assertIsInstance(result, FetchResult)
        self.assertEqual(result.status, DataStatus.UNAVAILABLE)
        self.assertTrue(result.payload.empty)

    def test_index_success_returns_ok_with_payload(self):
        adapter = AStockDataAdapter()
        bars = pd.DataFrame(
            {"close": [3180.0, 3200.0], "amount": [9e10, 1.2e11], "open": [3170.0, 3190.0]},
            index=pd.to_datetime(["2026-06-23", "2026-06-24"]),
        )
        client = MagicMock()
        client.index.return_value = bars
        with patch("data_adapters.a_stock_adapter.Quotes") as mock_quotes:
            mock_quotes.factory.return_value = client
            result = adapter.get_index_recap("2026-06-24")

        self.assertIsInstance(result, FetchResult)
        self.assertEqual(result.status, DataStatus.OK)
        self.assertEqual(result.as_of, "2026-06-24")
        self.assertGreater(result.row_count, 0)
        self.assertFalse(result.payload.empty)


class TestTradingDaysNoWeekdayFallback(unittest.TestCase):
    """方案 8.2:mootdx 指数日期用于运行后佐证,不再在失败时退化为普通工作日。

    旧实现 `get_trading_days` 在异常分支用 `weekday() < 5` 生成日历,
    把"交易日历不可用"伪装成"工作日列表",会在休市工作日(如 2026-06-19 端午)
    误判为可发布。失败必须返回 UNAVAILABLE。
    """

    def test_trading_days_client_raises_returns_unavailable(self):
        adapter = AStockDataAdapter()
        with patch("data_adapters.a_stock_adapter.Quotes") as mock_quotes:
            mock_quotes.factory.side_effect = RuntimeError("mootdx unreachable")
            result = adapter.get_trading_days(offset=10)

        self.assertIsInstance(result, FetchResult)
        self.assertEqual(result.status, DataStatus.UNAVAILABLE)
        self.assertTrue(result.payload.empty)
        # 关键:不得返回伪装的工作日列表
        self.assertNotIn("weekday", (result.error_message or "").lower() + (result.error_code or "").lower())

    def test_trading_days_success_returns_ok_sorted(self):
        adapter = AStockDataAdapter()
        bars = pd.DataFrame(
            {"close": [1.0, 1.0, 1.0]},
            index=pd.to_datetime(["2026-06-22", "2026-06-23", "2026-06-24"]),
        )
        client = MagicMock()
        client.index.return_value = bars
        with patch("data_adapters.a_stock_adapter.Quotes") as mock_quotes:
            mock_quotes.factory.return_value = client
            result = adapter.get_trading_days(offset=10)

        self.assertIsInstance(result, FetchResult)
        self.assertEqual(result.status, DataStatus.OK)
        self.assertEqual(result.row_count, 3)
        dates = result.payload["trade_date"].tolist()
        self.assertEqual(dates, sorted(dates))


class TestPublishGate(unittest.TestCase):
    """方案 7.4 发布闸门:关键来源不可用 -> publishable=False。"""

    def test_publish_gate_blocks_when_all_indices_unavailable(self):
        from publish_gate import PublicationGateResult, evaluate_publishable

        sources = {
            "limit_up_pool": FetchResult.ok(
                dataset_name="limit_up_pool",
                provider="akshare",
                requested_trade_date="2026-06-24",
                as_of="2026-06-24",
                payload=pd.DataFrame([{"code": "000001"}]),
                schema_version=1,
            ),
            "index_recap": FetchResult.unavailable(
                dataset_name="index_recap",
                provider="mootdx",
                requested_trade_date="2026-06-24",
                error_code="INDEX_UNAVAILABLE",
                error_message="all three indices unavailable",
                schema_version=1,
            ),
        }
        result = evaluate_publishable("2026-06-24", is_trading_day=True, sources=sources)
        self.assertIsInstance(result, PublicationGateResult)
        self.assertFalse(result.publishable)
        self.assertIn("CRITICAL_SOURCE_UNAVAILABLE", result.reason_codes)

    def test_publish_gate_blocks_wrong_date_pool(self):
        """方案 7.3.2:涨停池 as_of 必须等于请求交易日。"""
        from publish_gate import evaluate_publishable

        wrong_date_pool = FetchResult.ok(
            dataset_name="limit_up_pool",
            provider="akshare",
            requested_trade_date="2026-06-24",
            as_of="2026-06-23",  # 错日期
            payload=pd.DataFrame([{"code": "000001"}]),
            schema_version=1,
        )
        sources = {
            "limit_up_pool": wrong_date_pool,
            "index_recap": _ok_index_recap(),
        }
        result = evaluate_publishable("2026-06-24", is_trading_day=True, sources=sources)
        self.assertFalse(result.publishable)
        self.assertIn("SOURCE_SCHEMA_INVALID", result.reason_codes)

    def test_publish_gate_blocks_non_trading_day(self):
        from publish_gate import evaluate_publishable

        sources = {
            "limit_up_pool": FetchResult.ok(
                dataset_name="limit_up_pool",
                provider="akshare",
                requested_trade_date="2026-06-19",
                as_of="2026-06-19",
                payload=pd.DataFrame([{"code": "000001"}]),
                schema_version=1,
            ),
            "index_recap": _ok_index_recap(),
        }
        result = evaluate_publishable("2026-06-19", is_trading_day=False, sources=sources)
        self.assertFalse(result.publishable)
        self.assertIn("TRADING_DAY_INVALID", result.reason_codes)

    def test_publish_gate_allows_when_ok(self):
        from publish_gate import evaluate_publishable

        sources = {
            "limit_up_pool": FetchResult.ok(
                dataset_name="limit_up_pool",
                provider="akshare",
                requested_trade_date="2026-06-24",
                as_of="2026-06-24",
                payload=pd.DataFrame([{"code": "000001"}]),
                schema_version=1,
            ),
            "index_recap": _ok_index_recap(),
        }
        result = evaluate_publishable("2026-06-24", is_trading_day=True, sources=sources)
        self.assertTrue(result.publishable)

    def test_publish_gate_blocks_when_index_majority_missing(self):
        from publish_gate import evaluate_publishable

        sources = {
            "limit_up_pool": FetchResult.ok(
                dataset_name="limit_up_pool",
                provider="akshare",
                requested_trade_date="2026-06-24",
                as_of="2026-06-24",
                payload=pd.DataFrame([{"code": "000001"}]),
                schema_version=1,
            ),
            "index_recap": FetchResult.ok(
                dataset_name="index_recap",
                provider="mootdx",
                requested_trade_date="2026-06-24",
                as_of="2026-06-24",
                payload=pd.DataFrame(
                    [{"index": "sh", "price": 3200.0, "change_pct": 1.2, "amount_yuan": 4.0e11}]
                ),
                schema_version=1,
            ),
        }
        result = evaluate_publishable("2026-06-24", is_trading_day=True, sources=sources)
        self.assertFalse(result.publishable)
        self.assertIn("CRITICAL_SOURCE_UNAVAILABLE", result.reason_codes)

if __name__ == "__main__":
    unittest.main()
