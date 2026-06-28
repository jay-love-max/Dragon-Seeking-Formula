from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from datetime import date, datetime

import akshare as ak
import pandas as pd

from .ashare import get_realtime_quotes

logger = logging.getLogger("data_pipeline.collector")


def _normalize_code(value) -> str:
    text = str(value or "").strip().upper()
    text = text.replace(".SH", "").replace(".SZ", "").replace(".BJ", "")
    digits = "".join(ch for ch in text if ch.isdigit())
    return digits[:6].zfill(6) if digits else ""


def _normalize_time(value) -> str:
    text = "".join(ch for ch in str(value or "") if ch.isdigit())
    if not text:
        return ""
    if len(text) >= 6:
        return text[:6]
    if len(text) == 4:
        return f"{text}00"
    return text.zfill(6)


def _normalize_numeric_columns(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    for col in columns:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def _finalize_frame(df: pd.DataFrame, source: str, columns: list[str]) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=columns)
    keep = [c for c in columns if c in df.columns]
    out = df[keep].copy()
    out["source_tag"] = source
    out["ts"] = datetime.now().isoformat(timespec="seconds")
    return out


class Collector(ABC):
    """Base class for all data source collectors."""

    source: str = "unknown"

    def __init__(self, interval: float = 5.0, retry_delay: float = 5.0):
        self.interval = interval
        self.retry_delay = retry_delay
        self._last_poll: datetime | None = None

    def due(self) -> bool:
        now = datetime.now()
        if self._last_poll is None:
            self._last_poll = now
            return True
        elapsed = (now - self._last_poll).total_seconds()
        return elapsed >= self.interval

    @abstractmethod
    async def poll(self) -> pd.DataFrame:
        ...


class AshareCollector(Collector):
    """Real-time quotes via Ashare (Tencent)."""

    source = "ashare"

    def __init__(self, watchlist: list[str] | None = None, interval: float = 3.0):
        super().__init__(interval=interval)
        self._watchlist = watchlist or []

    def update_watchlist(self, codes: list[str]):
        self._watchlist = list(set(codes))

    async def poll(self) -> pd.DataFrame:
        if not self._watchlist:
            return pd.DataFrame()
        try:
            loop = asyncio.get_running_loop()
            df = await loop.run_in_executor(None, get_realtime_quotes, self._watchlist)
            if df is None or df.empty:
                return pd.DataFrame()
            df = df.rename(columns={
                "代码": "code",
                "名称": "name",
                "最新价": "price",
                "涨跌幅": "change_pct",
                "换手率": "turnover",
                "流通市值": "float_mcap",
            })
            df["code"] = df["code"].apply(_normalize_code)
            df = df[df["code"] != ""]
            df = _normalize_numeric_columns(df, ["price", "change_pct", "turnover", "float_mcap"])
            self._last_poll = datetime.now()
            cols = ["code", "name", "price", "change_pct", "turnover", "float_mcap"]
            return _finalize_frame(df, self.source, cols)
        except Exception as e:
            logger.warning("AshareCollector poll failed: %s", e)
            return pd.DataFrame()


class ZTPoolCollector(Collector):
    """Limit-up pool via akshare."""

    source = "zt_pool"

    def __init__(self, interval: float = 5.0):
        super().__init__(interval=interval)

    async def poll(self) -> pd.DataFrame:
        try:
            date_str = date.today().strftime("%Y%m%d")
            loop = asyncio.get_running_loop()
            df = await loop.run_in_executor(None, ak.stock_zt_pool_em, date_str)
            if df is None or df.empty:
                return pd.DataFrame()
            df = df.rename(columns={
                "代码": "code",
                "名称": "name",
                "最新价": "price",
                "涨跌幅": "change_pct",
                "换手率": "turnover",
                "流通市值": "float_mcap",
                "封板资金": "seal_funds",
                "首次封板时间": "first_seal_time",
                "炸板次数": "blown_count",
                "连板数": "consecutive_boards",
                "所属行业": "sector",
            })
            df["code"] = df["code"].apply(_normalize_code)
            df = df[df["code"] != ""]
            df = _normalize_numeric_columns(
                df,
                ["price", "change_pct", "turnover", "float_mcap", "seal_funds", "blown_count", "consecutive_boards"],
            )
            if "blown_count" in df.columns:
                df["blown_count"] = df["blown_count"].fillna(0).astype(int)
            if "consecutive_boards" in df.columns:
                df["consecutive_boards"] = df["consecutive_boards"].fillna(0).astype(int)
            if "first_seal_time" in df.columns:
                df["first_seal_time"] = df["first_seal_time"].apply(_normalize_time)
            self._last_poll = datetime.now()
            cols = ["code", "name", "price", "change_pct", "turnover", "float_mcap",
                    "seal_funds", "first_seal_time", "blown_count", "consecutive_boards", "sector"]
            return _finalize_frame(df, self.source, cols)
        except Exception as e:
            logger.warning("ZTPoolCollector poll failed: %s", e)
            return pd.DataFrame()


class NewsCollector(Collector):
    """Financial news via akshare."""

    source = "news"

    def __init__(self, interval: float = 30.0):
        super().__init__(interval=interval)

    async def poll(self) -> pd.DataFrame:
        try:
            loop = asyncio.get_running_loop()
            df = await loop.run_in_executor(None, ak.stock_news_em)
            if df is None or df.empty:
                return pd.DataFrame()
            df = df.rename(columns={
                "code": "code",
                "title": "title",
                "content": "content",
                "datetime": "ts",
            })
            if "code" in df.columns:
                df["code"] = df["code"].apply(_normalize_code)
                df = df[df["code"] != ""]
            self._last_poll = datetime.now()
            cols = [c for c in ["code", "title", "content", "ts"] if c in df.columns]
            return _finalize_frame(df, self.source, cols)
        except Exception as e:
            logger.warning("NewsCollector poll failed: %s", e)
            return pd.DataFrame()
