import os
from datetime import datetime
from pathlib import Path
from typing import Any

import akshare as ak
import pandas as pd
import requests
from mootdx.quotes import Quotes

from contracts import FetchResult, validate_index_recap, validate_limit_up_pool

from .base_adapter import (
    BaseStockAdapter,
    normalize_lhb_details,
    normalize_lhb_statistics,
    normalize_stock_comments,
)

# schema versions for the FetchResult payloads produced by this adapter.
TRADING_DAYS_SCHEMA_VERSION = 1
INDEX_RECAP_SCHEMA_VERSION = 1


class AStockDataAdapter(BaseStockAdapter):
    def __init__(self):
        self.ths_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36"
        }

    def get_trading_days(self, offset: int = 200) -> FetchResult:
        """Fetch trading days from mootdx index calendar.

        方案 8.2:mootdx 指数日期用于运行后佐证,不再在失败时退化为普通工作日。
        失败返回 status=UNAVAILABLE,绝不返回伪装的工作日列表。
        """
        try:
            client = Quotes.factory(market='std')
            bars = client.index(symbol='000001', category=4, offset=offset)
            bars = bars.copy()
            dates = pd.to_datetime(bars.index).strftime('%Y-%m-%d').tolist()
            dates = sorted(set(dates))
            payload = pd.DataFrame({"trade_date": dates})
            return FetchResult.ok(
                dataset_name="trading_days",
                provider="mootdx",
                requested_trade_date=datetime.now().strftime("%Y-%m-%d"),
                as_of=dates[-1] if dates else None,
                payload=payload,
                schema_version=TRADING_DAYS_SCHEMA_VERSION,
            )
        except Exception as e:
            print(f"[a-stock-data] Error fetching trading days: {e}")
            return FetchResult.unavailable(
                dataset_name="trading_days",
                provider="mootdx",
                requested_trade_date=datetime.now().strftime("%Y-%m-%d"),
                error_code="TRADING_DAYS_UNAVAILABLE",
                error_message=str(e),
                schema_version=TRADING_DAYS_SCHEMA_VERSION,
            )

    def get_index_recap(self, date_str: str) -> FetchResult:
        """Fetch index close prices, changes and total turnover for ``date_str``.

        方案 7.1/7.4:缺失或失败不得写成 ``{"price": 0.0, "change": 0.0}``。
        指数三大关键记录全部不可用时返回 UNAVAILABLE;部分缺失在 payload 中
        只包含可用行,调用方据 publish_gate 判断是否阻断。
        """
        try:
            client = Quotes.factory(market='std')
        except Exception as e:
            print(f"[a-stock-data] Error creating mootdx client: {e}")
            return FetchResult.unavailable(
                dataset_name="index_recap",
                provider="mootdx",
                requested_trade_date=date_str,
                error_code="INDEX_CLIENT_UNAVAILABLE",
                error_message=str(e),
                schema_version=INDEX_RECAP_SCHEMA_VERSION,
            )

        indices = {"sh": "000001", "sz": "399001", "cy": "399006"}
        rows: list[dict[str, Any]] = []

        for name, sym in indices.items():
            try:
                bars = client.index(symbol=sym, category=4, offset=15)
                bars = bars.copy()
                bars['date_str'] = pd.to_datetime(bars.index).strftime('%Y-%m-%d')

                matching_rows = bars[bars['date_str'] == date_str]
                if matching_rows.empty:
                    # 该指数在请求交易日无记录:跳过,不写 0(方案 7.1)
                    continue
                idx = matching_rows.index[0]
                pos = bars.index.get_loc(idx)

                today_close = float(bars.iloc[pos]["close"])
                today_amount = float(bars.iloc[pos]["amount"])

                if pos > 0:
                    prev_close = float(bars.iloc[pos - 1]["close"])
                    change_pct = (today_close - prev_close) / prev_close * 100
                else:
                    today_open = float(bars.iloc[pos]["open"])
                    change_pct = (today_close - today_open) / today_open * 100

                rows.append({
                    "index": name,
                    "price": round(today_close, 2),
                    "change_pct": round(change_pct, 2),
                    "amount_yuan": today_amount,
                })
            except Exception as e:
                print(f"[a-stock-data] Error getting index {name} for {date_str}: {e}")
                # 单个指数失败不阻断整批;publish_gate 据可用行数判断
                continue

        if not rows:
            # 三大指数全部不可用:整体 UNAVAILABLE(方案 7.4.3)
            return FetchResult.unavailable(
                dataset_name="index_recap",
                provider="mootdx",
                requested_trade_date=date_str,
                error_code="INDEX_UNAVAILABLE",
                error_message=f"all three indices unavailable for {date_str}",
                schema_version=INDEX_RECAP_SCHEMA_VERSION,
            )

        payload = pd.DataFrame(rows)
        valid, err = validate_index_recap(payload)
        if not valid:
            return FetchResult.invalid(
                dataset_name="index_recap",
                provider="mootdx",
                requested_trade_date=date_str,
                payload=payload,
                error_message=err or "schema validation failed",
                schema_version=INDEX_RECAP_SCHEMA_VERSION,
            )
        return FetchResult.ok(
            dataset_name="index_recap",
            provider="mootdx",
            requested_trade_date=date_str,
            as_of=date_str,
            payload=payload,
            schema_version=INDEX_RECAP_SCHEMA_VERSION,
        )

    def get_limit_up_pool(self, date_str: str) -> FetchResult:
        date_compact = date_str.replace("-", "")
        try:
            raw = ak.stock_zt_pool_em(date=date_compact)
        except Exception as e:
            print(f"[a-stock-data] Error getting limit up pool: {e}")
            return FetchResult.unavailable(
                dataset_name="limit_up_pool",
                provider="akshare",
                requested_trade_date=date_str,
                error_code="LIMIT_UP_POOL_UNAVAILABLE",
                error_message=str(e),
                schema_version=1,
            )

        if raw is None or raw.empty:
            return FetchResult.unavailable(
                dataset_name="limit_up_pool",
                provider="akshare",
                requested_trade_date=date_str,
                error_code="EMPTY_POOL",
                error_message="limit_up_pool empty",
                schema_version=1,
            )

        df = raw.copy()
        rename_map = {
            "代码": "code",
            "名称": "name",
            "连板数": "consecutive_boards",
            "首次封板时间": "first_seal_time",
            "炸板次数": "blown_count",
            "流通市值": "float_mcap_yuan",
            "封板资金": "seal_funds_yuan",
            "换手率": "turnover_pct",
            "所属行业": "sector",
            "最新价": "price",
            "涨跌幅": "change_pct",
            "题材归因": "concept",
        }
        df = df.rename(columns={src: dst for src, dst in rename_map.items() if src in df.columns})

        required = [
            "code",
            "name",
            "consecutive_boards",
            "first_seal_time",
            "blown_count",
            "float_mcap_yuan",
            "seal_funds_yuan",
            "turnover_pct",
            "sector",
            "price",
            "change_pct",
        ]
        missing = [col for col in required if col not in df.columns]
        if missing:
            return FetchResult.invalid(
                dataset_name="limit_up_pool",
                provider="akshare",
                requested_trade_date=date_str,
                error_message=f"limit_up_pool missing columns: {missing}",
                schema_version=1,
                payload=df,
            )

        def _normalize_time(value: Any) -> str | None:
            text = "".join(ch for ch in str(value or "") if ch.isdigit())
            if not text:
                return None
            digits = text.zfill(6)[-6:]
            return f"{digits[:2]}:{digits[2:4]}:{digits[4:]}"

        normalized = pd.DataFrame()
        normalized["code"] = (
            df["code"].astype(str).str.extract(r"(\d{6})", expand=False).fillna("").str.zfill(6)
        )
        normalized["name"] = df["name"].astype(str).str.strip()
        normalized["trade_date"] = date_str
        normalized["price"] = pd.to_numeric(df["price"], errors="coerce")
        normalized["change_pct"] = pd.to_numeric(df["change_pct"], errors="coerce")
        normalized["turnover_pct"] = pd.to_numeric(df["turnover_pct"], errors="coerce")
        normalized["float_mcap_yuan"] = pd.to_numeric(df["float_mcap_yuan"], errors="coerce")
        normalized["seal_funds_yuan"] = pd.to_numeric(df["seal_funds_yuan"], errors="coerce")
        normalized["first_seal_time"] = df["first_seal_time"].map(_normalize_time)
        normalized["blown_count"] = pd.to_numeric(df["blown_count"], errors="coerce")
        normalized["consecutive_boards"] = pd.to_numeric(df["consecutive_boards"], errors="coerce")
        normalized["is_st"] = normalized["name"].str.contains(r"^(\*?ST|S\*ST|退市)", regex=True)
        normalized["sector"] = df["sector"].fillna("UNKNOWN").astype(str).str.strip().replace("", "UNKNOWN")
        if "concept" in df.columns:
            normalized["concept"] = df["concept"].fillna("").astype(str)

        before = len(normalized)
        normalized = normalized[
            normalized["code"].str.fullmatch(r"\d{6}", na=False)
            & normalized["name"].ne("")
            & normalized["price"].notna()
            & normalized["change_pct"].notna()
            & normalized["turnover_pct"].notna()
            & normalized["float_mcap_yuan"].notna()
            & normalized["seal_funds_yuan"].notna()
            & normalized["blown_count"].notna()
            & normalized["consecutive_boards"].notna()
            & normalized["sector"].ne("")
        ].copy()
        if normalized.empty:
            return FetchResult.invalid(
                dataset_name="limit_up_pool",
                provider="akshare",
                requested_trade_date=date_str,
                error_message="limit_up_pool contains no valid rows after normalization",
                schema_version=1,
                payload=df,
            )

        normalized["blown_count"] = normalized["blown_count"].astype(int)
        normalized["consecutive_boards"] = normalized["consecutive_boards"].astype(int)
        normalized["is_st"] = normalized["is_st"].astype(bool)
        normalized["trade_date"] = date_str

        valid, error = validate_limit_up_pool(normalized)
        if not valid:
            return FetchResult.invalid(
                dataset_name="limit_up_pool",
                provider="akshare",
                requested_trade_date=date_str,
                error_message=error or "limit_up_pool invalid",
                schema_version=1,
                payload=normalized,
            )

        warnings = []
        if len(normalized) != before:
            warnings.append(f"dropped {before - len(normalized)} malformed limit-up rows")

        if normalized["trade_date"].nunique() != 1 or normalized["trade_date"].iloc[0] != date_str:
            return FetchResult.invalid(
                dataset_name="limit_up_pool",
                provider="akshare",
                requested_trade_date=date_str,
                error_message="limit_up_pool trade_date mismatch",
                schema_version=1,
                payload=normalized,
            )

        if warnings:
            return FetchResult.degraded(
                dataset_name="limit_up_pool",
                provider="akshare",
                requested_trade_date=date_str,
                as_of=date_str,
                payload=normalized,
                schema_version=1,
                warnings=warnings,
            )

        return FetchResult.ok(
            dataset_name="limit_up_pool",
            provider="akshare",
            requested_trade_date=date_str,
            as_of=date_str,
            payload=normalized,
            schema_version=1,
        )

    def get_limit_down_pool(self, date_str: str) -> pd.DataFrame:
        date_compact = date_str.replace("-", "")
        try:
            df = ak.stock_zt_pool_dtgc_em(date=date_compact)
            if df is not None and not df.empty:
                return df.copy()
        except Exception as e:
            print(f"[a-stock-data] Error getting limit down pool: {e}")
        return pd.DataFrame()

    def get_concept_reasons(self, date_str: str) -> dict[str, str]:
        url = f"http://zx.10jqka.com.cn/event/api/getharden/date/{date_str}/orderby/date/orderway/desc/charset/GBK/"
        try:
            r = requests.get(url, headers=self.ths_headers, timeout=10)
            data = r.json()
            if data.get("errocode") == 0 or data.get("errocode") == "0":
                rows = data.get("data") or []
                reasons = {}
                for row in rows:
                    code = str(row.get("code", "")).zfill(6)
                    reasons[code] = row.get("reason", "")
                return reasons
        except Exception as e:
            print(f"[a-stock-data] Error fetching THS reasons: {e}")
        return {}

    def get_northbound_flow(self, date_str: str) -> tuple[float, float]:
        url = "https://data.hexin.cn/market/hsgtApi/method/dayChart/"
        try:
            r = requests.get(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Host": "data.hexin.cn",
                "Referer": "https://data.hexin.cn/"
            }, timeout=10)
            d = r.json()
            hgt = d.get("hgt", [])
            sgt = d.get("sgt", [])
            hgt_close = hgt[-1] if hgt else 0.0
            sgt_close = sgt[-1] if sgt else 0.0
            return float(hgt_close), float(sgt_close)
        except Exception as e:
            print(f"[a-stock-data] Error fetching northbound flow: {e}")
        return 0.0, 0.0

    def get_finance_data(self, code: str) -> dict[str, Any]:
        def _normalize_symbol(value: Any) -> str:
            text = str(value).strip().upper()
            if not text:
                return ""
            if "." in text:
                return text
            if text.isdigit():
                text = text.zfill(6)
                if text.startswith("6"):
                    return f"{text}.SH"
                if text.startswith(("8", "4")):
                    return f"{text}.BJ"
                return f"{text}.SZ"
            return text

        def _pick(row: dict[str, Any], *names: str):
            for name in names:
                if name not in row:
                    continue
                value = row.get(name)
                if value is None:
                    continue
                try:
                    if pd.isna(value):
                        continue
                except Exception:
                    pass
                return value
            return None

        def _load_local_row(data_root: Path, table: str, symbol: str) -> dict[str, Any]:
            path = data_root / "financials" / table / "part.parquet"
            if not path.exists():
                return {}
            try:
                df = pd.read_parquet(path)
            except Exception as e:
                print(f"[a-stock-data] Error reading local finance {table} for {code}: {e}")
                return {}
            if df is None or df.empty:
                return {}

            key_col = next((c for c in ("symbol", "code", "证券代码", "股票代码") if c in df.columns), None)
            if key_col is None:
                return {}

            key_series = df[key_col].astype(str).map(_normalize_symbol)
            row_df = df[key_series == symbol]
            if row_df.empty:
                base_code = symbol[:6]
                row_df = df[df[key_col].astype(str).str[:6] == base_code]
            if row_df.empty:
                return {}
            return row_df.iloc[0].to_dict()

        data_root = os.getenv("DATA_DIR")
        if data_root:
            root = Path(data_root)
        else:
            repo_root = Path(__file__).resolve().parents[2]
            for candidate in (
                repo_root / "vendor" / "tickflow-stock-panel" / "data",
                repo_root / "data",
            ):
                if candidate.exists():
                    root = candidate
                    break
            else:
                root = repo_root / "data"

        try:
            symbol = _normalize_symbol(code)
            finance_dict: dict[str, Any] = {}

            metrics = _load_local_row(root, "metrics", symbol)
            income = _load_local_row(root, "income", symbol)
            balance = _load_local_row(root, "balance_sheet", symbol)

            jinglirun = _pick(income, "jinglirun", "net_profit", "net_income", "净利润", "归母净利润", "net_income_attributable")
            jingzichan = _pick(balance, "jingzichan", "total_equity", "净资产", "equity", "owner_equity", "total_owner_equity")
            zhuyingshouru = _pick(income, "zhuyingshouru", "revenue", "营业收入", "营业总收入", "主营业务收入", "operating_revenue")
            zongguben = _pick(metrics, "zongguben", "shares_total", "total_shares", "share_total", "总股本")
            if zongguben is None:
                zongguben = _pick(balance, "zongguben", "shares_total", "total_shares", "share_total", "总股本")
            liudongfuzhai = _pick(balance, "liudongfuzhai", "current_liability", "流动负债", "current_liabilities", "total_current_liabilities", "流动负债合计")
            changqifuzhai = _pick(balance, "changqifuzhai", "noncurrent_liability", "非流动负债", "non_current_liabilities", "total_non_current_liabilities", "非流动负债合计")
            zongzichan = _pick(balance, "zongzichan", "total_assets", "总资产")
            goodwill = _pick(balance, "goodwill", "商誉", "goodwill_value")
            accounts_receivable = _pick(balance, "accounts_receivable", "应收账款", "ar", "receivable")
            roe = _pick(metrics, "roe", "roe_waa", "净资产收益率")
            eps = _pick(metrics, "eps", "eps_basic", "每股收益", "basic_eps")

            if roe is None and jinglirun not in (None, 0) and jingzichan not in (None, 0):
                roe = float(jinglirun) / float(jingzichan) * 100
            if eps is None and jinglirun not in (None, 0) and zongguben not in (None, 0):
                eps = float(jinglirun) / float(zongguben)

            asset_liability_ratio = None
            goodwill_ratio = None
            receivable_ratio = None
            if zongzichan not in (None, 0):
                liabilities = (float(liudongfuzhai) if liudongfuzhai is not None else 0.0) + (
                    float(changqifuzhai) if changqifuzhai is not None else 0.0
                )
                asset_liability_ratio = liabilities / float(zongzichan) * 100
                if accounts_receivable is not None:
                    receivable_ratio = float(accounts_receivable) / float(zongzichan) * 100
            if jingzichan not in (None, 0) and goodwill is not None:
                goodwill_ratio = float(goodwill) / float(jingzichan) * 100

            if jinglirun is not None:
                finance_dict["jinglirun"] = float(jinglirun)
            if jingzichan is not None:
                finance_dict["jingzichan"] = float(jingzichan)
            if zhuyingshouru is not None:
                finance_dict["zhuyingshouru"] = float(zhuyingshouru)
            if zongguben is not None:
                finance_dict["zongguben"] = float(zongguben)
            if liudongfuzhai is not None:
                finance_dict["liudongfuzhai"] = float(liudongfuzhai)
            if changqifuzhai is not None:
                finance_dict["changqifuzhai"] = float(changqifuzhai)
            if zongzichan is not None:
                finance_dict["zongzichan"] = float(zongzichan)
            if goodwill is not None:
                finance_dict["goodwill"] = float(goodwill)
            if accounts_receivable is not None:
                finance_dict["accounts_receivable"] = float(accounts_receivable)
            if asset_liability_ratio is not None:
                finance_dict["asset_liability_ratio"] = float(asset_liability_ratio)
            if goodwill_ratio is not None:
                finance_dict["goodwill_ratio"] = float(goodwill_ratio)
            if receivable_ratio is not None:
                finance_dict["receivable_ratio"] = float(receivable_ratio)
            if roe is not None:
                finance_dict["roe"] = float(roe)
            if eps is not None:
                finance_dict["eps"] = float(eps)

            if finance_dict:
                return finance_dict
        except Exception as e:
            print(f"[a-stock-data] Error loading local finance data for {code}: {e}")

        try:
            client = Quotes.factory(market='std')
            fin = client.finance(symbol=code)
            if fin is not None and not fin.empty:
                finance_dict = fin.head(1).to_dict("records")[0]
                jingzichan = _pick(finance_dict, "jingzichan", "total_equity", "净资产", "equity", "owner_equity", "total_owner_equity", "equity_attributable")
                zongzichan = _pick(finance_dict, "zongzichan", "total_assets", "总资产")
                goodwill = _pick(finance_dict, "goodwill", "商誉", "goodwill_value")
                accounts_receivable = _pick(finance_dict, "accounts_receivable", "应收账款", "ar", "receivable")
                liudongfuzhai = _pick(finance_dict, "liudongfuzhai", "current_liability", "流动负债", "current_liabilities", "total_current_liabilities", "流动负债合计")
                changqifuzhai = _pick(finance_dict, "changqifuzhai", "noncurrent_liability", "非流动负债", "non_current_liabilities", "total_non_current_liabilities", "非流动负债合计")

                asset_liability_ratio = None
                goodwill_ratio = None
                receivable_ratio = None
                if zongzichan not in (None, 0):
                    liabilities = (float(liudongfuzhai) if liudongfuzhai is not None else 0.0) + (
                        float(changqifuzhai) if changqifuzhai is not None else 0.0
                    )
                    asset_liability_ratio = liabilities / float(zongzichan) * 100
                    if accounts_receivable is not None:
                        receivable_ratio = float(accounts_receivable) / float(zongzichan) * 100
                if jingzichan not in (None, 0) and goodwill is not None:
                    goodwill_ratio = float(goodwill) / float(jingzichan) * 100

                if goodwill is not None:
                    finance_dict["goodwill"] = float(goodwill)
                if accounts_receivable is not None:
                    finance_dict["accounts_receivable"] = float(accounts_receivable)
                if asset_liability_ratio is not None:
                    finance_dict["asset_liability_ratio"] = float(asset_liability_ratio)
                if goodwill_ratio is not None:
                    finance_dict["goodwill_ratio"] = float(goodwill_ratio)
                if receivable_ratio is not None:
                    finance_dict["receivable_ratio"] = float(receivable_ratio)
                return finance_dict
        except Exception as e:
            print(f"[a-stock-data] Error fetching finance data for {code}: {e}")
        return {}

    def get_stock_comments(self) -> pd.DataFrame:
        try:
            raw = ak.stock_comment_em()
            return normalize_stock_comments(raw)
        except Exception as e:
            print(f"[a-stock-data] Error fetching stock comments: {e}")
            return pd.DataFrame()

    def get_lhb_statistics(self) -> pd.DataFrame:
        try:
            raw = ak.stock_lhb_stock_statistic_em(symbol="近一月")
            return normalize_lhb_statistics(raw)
        except Exception as e:
            print(f"[a-stock-data] Error fetching LHB statistics: {e}")
            return pd.DataFrame()

    def get_lhb_details(self, start_date: str, end_date: str) -> pd.DataFrame:
        try:
            raw = ak.stock_lhb_detail_em(start_date=start_date, end_date=end_date)
            return normalize_lhb_details(raw)
        except Exception as e:
            print(f"[a-stock-data] Error fetching LHB details: {e}")
            return pd.DataFrame()

