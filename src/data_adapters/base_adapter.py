from abc import ABC, abstractmethod
from typing import Any

import pandas as pd

from contracts import FetchResult


class BaseStockAdapter(ABC):
    @abstractmethod
    def get_trading_days(self, offset: int = 200) -> FetchResult:
        """Fetch list of YYYY-MM-DD trading days.

        Returns FetchResult whose payload is a DataFrame with a ``trade_date``
        string column (sorted ascending). Network or provider failure must
        return status=UNAVAILABLE — never a disguised weekday fallback.
        """
        pass

    @abstractmethod
    def get_index_recap(self, date_str: str) -> FetchResult:
        """Fetch index close prices, changes and total turnover for ``date_str``.

        Returns FetchResult whose payload is a DataFrame with one row per
        index (``sh``/``sz``/``cy``) and columns ``index, price, change_pct,
        amount_yuan``. Missing data or request failure must return
        status=UNAVAILABLE — never ``{"price": 0.0, "change": 0.0}``.
        """
        pass

    @abstractmethod
    def get_limit_up_pool(self, date_str: str) -> pd.DataFrame:
        """Fetch daily limit-up stock pool.
        Must return columns: ['代码', '名称', '连板数', '首次封板时间', '炸板次数', '流通市值', '封板资金', '换手率', '所属行业']
        """
        pass

    @abstractmethod
    def get_limit_down_pool(self, date_str: str) -> pd.DataFrame:
        """Fetch daily limit-down stock pool"""
        pass

    @abstractmethod
    def get_concept_reasons(self, date_str: str) -> dict[str, str]:
        """Fetch concept/theme attributions for limit-up stocks.
        Returns dict of {code: reason}
        """
        pass

    @abstractmethod
    def get_northbound_flow(self, date_str: str) -> tuple[float, float]:
        """Fetch northbound capital flow (HGT, SGT) in hundred million RMB"""
        pass

    @abstractmethod
    def get_finance_data(self, code: str) -> dict[str, Any]:
        """Fetch financial data for the stock.
        Returns a dict containing fields like 'jinglirun', 'jingzichan', 'zhuyingshouru', 'zongguben'
        """
        pass

    @abstractmethod
    def get_stock_comments(self) -> pd.DataFrame:
        """Fetch stock comments and sentiment data"""
        pass

    @abstractmethod
    def get_lhb_statistics(self) -> pd.DataFrame:
        """Fetch dragon-tiger list (龙虎榜) stock statistics for the past month"""
        pass

    @abstractmethod
    def get_lhb_details(self, start_date: str, end_date: str) -> pd.DataFrame:
        """Fetch dragon-tiger list details within the date range (YYYYMMDD)"""
        pass
