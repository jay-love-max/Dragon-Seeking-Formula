from datetime import datetime
from typing import Any

import pandas as pd
import requests

from contracts import FetchResult

from .base_adapter import BaseStockAdapter


class GlobalStockAdapter(BaseStockAdapter):
    """Adapter for global stock markets (US/HK).
    Implements Yahoo Finance or specialized HTTP providers.
    """
    def __init__(self):
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }

    def get_trading_days(self, offset: int = 200) -> FetchResult:
        # Fetching S&P 500 calendar daily dates
        url = "https://query1.finance.yahoo.com/v8/finance/chart/%5EGSPC"
        try:
            r = requests.get(url, params={"range": "1y", "interval": "1d"}, headers=self.headers, timeout=10)
            data = r.json()
            timestamps = data["chart"]["result"][0]["timestamp"]
            dates = [pd.to_datetime(t, unit='s').strftime('%Y-%m-%d') for t in timestamps]
            dates = dates[-offset:]
            payload = pd.DataFrame({"trade_date": dates})
            return FetchResult.ok(
                dataset_name="trading_days",
                provider="yahoo",
                requested_trade_date=datetime.now().strftime("%Y-%m-%d"),
                as_of=dates[-1] if dates else None,
                payload=payload,
                schema_version=1,
            )
        except Exception as e:
            print(f"[global-stock-data] Failed to load trading calendar: {e}")
            return FetchResult.unavailable(
                dataset_name="trading_days",
                provider="yahoo",
                requested_trade_date=datetime.now().strftime("%Y-%m-%d"),
                error_code="TRADING_DAYS_UNAVAILABLE",
                error_message=str(e),
                schema_version=1,
            )

    def get_index_recap(self, date_str: str) -> FetchResult:
        # Indexes: ^GSPC (S&P 500), ^IXIC (Nasdaq Composite), ^HSI (Hang Seng Index)
        rows: list[dict[str, Any]] = []
        for key, symbol in [("us_sp", "^GSPC"), ("us_nas", "^IXIC"), ("hk_hsi", "^HSI")]:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
            try:
                r = requests.get(url, params={"range": "5d", "interval": "1d"}, headers=self.headers, timeout=10)
                data = r.json()
                timestamps = data["chart"]["result"][0]["timestamp"]
                quotes = data["chart"]["result"][0]["indicators"]["quote"][0]
                close_prices = quotes["close"]

                # Align with date_str
                dates = [pd.to_datetime(t, unit='s').strftime('%Y-%m-%d') for t in timestamps]
                if date_str in dates:
                    idx = dates.index(date_str)
                    price = close_prices[idx]
                    prev_price = close_prices[idx - 1] if idx > 0 else quotes["open"][idx]
                    change = ((price - prev_price) / prev_price) * 100 if prev_price > 0 else 0.0
                    rows.append({
                        "index": key,
                        "price": round(price, 2),
                        "change_pct": round(change, 2),
                        "amount_yuan": 0.0,
                    })
                # date not present: skip, do not write 0 (方案 7.1)
            except Exception as e:
                print(f"[global-stock-data] Index {symbol} failed: {e}")
                continue

        if not rows:
            return FetchResult.unavailable(
                dataset_name="index_recap",
                provider="yahoo",
                requested_trade_date=date_str,
                error_code="INDEX_UNAVAILABLE",
                error_message=f"all indices unavailable for {date_str}",
                schema_version=1,
            )
        payload = pd.DataFrame(rows)
        return FetchResult.ok(
            dataset_name="index_recap",
            provider="yahoo",
            requested_trade_date=date_str,
            as_of=date_str,
            payload=payload,
            schema_version=1,
        )

    def get_limit_up_pool(self, date_str: str) -> FetchResult:
        # Global markets do not have strict limit-up pool rules.
        return FetchResult.unavailable(
            dataset_name="limit_up_pool",
            provider="global",
            requested_trade_date=date_str,
            error_code="LIMIT_UP_POOL_NOT_SUPPORTED",
            error_message="global markets do not expose a limit-up pool",
            schema_version=1,
        )

    def get_limit_down_pool(self, date_str: str) -> pd.DataFrame:
        return pd.DataFrame()

    def get_concept_reasons(self, date_str: str) -> dict[str, str]:
        return {}

    def get_northbound_flow(self, date_str: str) -> tuple[float, float]:
        return 0.0, 0.0

    def get_finance_data(self, code: str) -> dict[str, Any]:
        return {}

    def get_stock_comments(self) -> pd.DataFrame:
        return pd.DataFrame()

    def get_lhb_statistics(self) -> pd.DataFrame:
        return pd.DataFrame()

    def get_lhb_details(self, start_date: str, end_date: str) -> pd.DataFrame:
        return pd.DataFrame()
