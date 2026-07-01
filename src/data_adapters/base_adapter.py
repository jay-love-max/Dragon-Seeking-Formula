from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

import pandas as pd

from contracts import FetchResult

LHB_FETCH_AFTER_HOUR = 20


def can_fetch_longhubang(now: datetime | None = None) -> bool:
    """F24: 龙虎榜采集时间约束。东方财富 20:00 后才发布完整席位数据。

    返回 True 当且仅当当前时间 >= 20:00 Asia/Shanghai。
    """
    dt = now if now is not None else datetime.now()
    return dt.hour >= LHB_FETCH_AFTER_HOUR

# Normalize raw akshare 龙虎榜 (dragon-tiger list) Chinese columns to the
# canonical English contract used downstream. The code column is zfilled to 6.
_LHB_STAT_RENAME = {
    "代码": "code",
    "上榜次数": "list_count",
    "龙虎榜净买额": "net_buy_yuan",
    "买方机构次数": "inst_buy_count",
}
_LHB_DETAIL_RENAME = {
    "代码": "code",
    "上榜日": "list_date",
    "龙虎榜净买额": "net_buy_yuan",
    "净买额": "net_buy_yuan",
    "买方机构次数": "inst_buy_count",
}


def normalize_lhb_statistics(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize raw akshare LHB statistics to the English column contract."""
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    out = out.rename(columns={k: v for k, v in _LHB_STAT_RENAME.items() if k in out.columns})
    if "code" in out.columns:
        out["code"] = out["code"].astype(str).str.extract(r"(\d{6})", expand=False).fillna("").str.zfill(6)
    return out


def normalize_lhb_details(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize raw akshare LHB details to the English column contract.

    When both 龙虎榜净买额 and 净买额 are present they map to the same
    ``net_buy_yuan``; the rename applies in declaration order so the provider's
    primary column wins.
    """
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    out = out.rename(columns={k: v for k, v in _LHB_DETAIL_RENAME.items() if k in out.columns})
    if "code" in out.columns:
        out["code"] = out["code"].astype(str).str.extract(r"(\d{6})", expand=False).fillna("").str.zfill(6)
    return out


# 千股千评 (stock comments) raw Chinese columns → English contract.
_COMMENT_RENAME = {
    "代码": "code",
    "名称": "name",
    "最新价": "price",
    "涨跌幅": "change_pct",
    "主力成本": "main_cost",
    "综合得分": "comment_score",
    "关注指数": "attention",
}


def normalize_stock_comments(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize raw akshare stock-comment (千股千评) rows to English columns."""
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    out = out.rename(columns={k: v for k, v in _COMMENT_RENAME.items() if k in out.columns})
    if "code" in out.columns:
        out["code"] = out["code"].astype(str).str.extract(r"(\d{6})", expand=False).fillna("").str.zfill(6)
    return out


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
    def get_limit_up_pool(self, date_str: str) -> FetchResult:
        """Fetch daily limit-up stock pool.

        Returns a FetchResult whose payload is the normalized limit-up pool.
        Network/provider failure must return status=UNAVAILABLE or INVALID,
        never a bare DataFrame or a zero-filled fallback.
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
        """Fetch stock comments and sentiment data (千股千评).

        Returns a DataFrame with English columns including ``code`` (6-digit
        string), ``main_cost`` (主力成本), ``comment_score`` (综合得分) and
        ``attention`` (关注指数). Chinese provider names are normalized at the
        adapter boundary.
        """
        pass

    @abstractmethod
    def get_lhb_statistics(self) -> pd.DataFrame:
        """Fetch dragon-tiger list (龙虎榜) stock statistics for the past month.

        Returns a DataFrame with English columns: ``code`` (6-digit string),
        ``list_count`` (上榜次数), ``net_buy_yuan`` (龙虎榜净买额) and
        ``inst_buy_count`` (买方机构次数). Chinese provider names are normalized
        at the adapter boundary; downstream code must not read Chinese columns.
        """
        pass

    @abstractmethod
    def get_lhb_details(self, start_date: str, end_date: str) -> pd.DataFrame:
        """Fetch dragon-tiger list details within the date range (YYYYMMDD).

        Returns a DataFrame with English columns: ``code`` (6-digit string),
        ``list_date`` (上榜日), ``net_buy_yuan`` (龙虎榜净买额) and
        ``inst_buy_count`` (买方机构次数). Chinese provider names are normalized
        at the adapter boundary.
        """
        pass
