import os
import re
from datetime import datetime
from typing import Any

import pandas as pd

from contracts import FetchResult, validate_limit_up_pool

from .base_adapter import (
    BaseStockAdapter,
    normalize_lhb_details,
    normalize_lhb_statistics,
    normalize_stock_comments,
)


class ThsdkAdapter(BaseStockAdapter):
    def __init__(self):
        try:
            from thsdk import THS
            self.THS = THS
        except ImportError:
            raise ImportError(
                "thsdk library is not installed. Please run `pip install thsdk` "
                "or choose DATA_PROVIDER=a-stock-data in your environment."
            )

        username = os.getenv("THS_USERNAME", "")
        password = os.getenv("THS_PASSWORD", "")
        mac = os.getenv("THS_MAC", "")

        config = {}
        if username and password:
            config = {"username": username, "password": password, "mac": mac}

        self.ths_client = self.THS(config)
        self.ths_client.connect()

    def __del__(self):
        try:
            self.ths_client.disconnect()
        except Exception:
            pass

    def get_trading_days(self, offset: int = 200) -> FetchResult:
        # Fetch standard index (e.g. USHI000001 Shanghai Composite)
        res = self.ths_client.klines("USHI000001", count=offset)
        if res.success and res.data:
            dates = sorted(row["时间"][:10] for row in res.data)
            payload = pd.DataFrame({"trade_date": dates})
            return FetchResult.ok(
                dataset_name="trading_days",
                provider="thsdk",
                requested_trade_date=datetime.now().strftime("%Y-%m-%d"),
                as_of=dates[-1] if dates else None,
                payload=payload,
                schema_version=1,
            )
        return FetchResult.unavailable(
            dataset_name="trading_days",
            provider="thsdk",
            requested_trade_date=datetime.now().strftime("%Y-%m-%d"),
            error_code="TRADING_DAYS_UNAVAILABLE",
            error_message="thsdk klines returned no data",
            schema_version=1,
        )

    def get_index_recap(self, date_str: str) -> FetchResult:
        # Index symbol mapping
        # USHI000001 (SH), USZI399001 (SZ), USZI399006 (CY)
        rows: list[dict[str, Any]] = []
        sh_amount = 0.0
        sz_amount = 0.0

        for key, code in [("sh", "USHI000001"), ("sz", "USZI399001"), ("cy", "USZI399006")]:
            res = self.ths_client.klines(code, count=2)
            if not (res.success and res.data and len(res.data) >= 2):
                continue

            today_row = None
            prev_row = None
            for i in range(len(res.data)):
                row_date = res.data[i]["时间"][:10]
                if row_date == date_str:
                    today_row = res.data[i]
                    if i > 0:
                        prev_row = res.data[i - 1]
                    break

            if not today_row:
                # 该指数在请求日无记录:跳过,不写 0(方案 7.1)
                continue

            close_val = float(today_row.get("收盘价", 0.0))
            amount_val = float(today_row.get("总金额", 0.0))

            if key == "sh":
                sh_amount = amount_val
            elif key == "sz":
                sz_amount = amount_val

            if prev_row:
                prev_close = float(prev_row.get("收盘价", 0.0))
                change = ((close_val - prev_close) / prev_close) * 100 if prev_close > 0 else 0.0
            else:
                open_val = float(today_row.get("开盘价", 0.0))
                change = ((close_val - open_val) / open_val) * 100 if open_val > 0 else 0.0

            rows.append({
                "index": key,
                "price": round(close_val, 2),
                "change_pct": round(change, 2),
                "amount_yuan": amount_val,
            })

        if not rows:
            return FetchResult.unavailable(
                dataset_name="index_recap",
                provider="thsdk",
                requested_trade_date=date_str,
                error_code="INDEX_UNAVAILABLE",
                error_message=f"all indices unavailable for {date_str}",
                schema_version=1,
            )

        total_turnover = (sh_amount + sz_amount) / 1e9
        payload = pd.DataFrame(rows)
        if total_turnover > 0:
            payload.attrs["total_turnover_yi"] = round(total_turnover, 2)
        return FetchResult.ok(
            dataset_name="index_recap",
            provider="thsdk",
            requested_trade_date=date_str,
            as_of=date_str,
            payload=payload,
            schema_version=1,
        )

    def _map_wencai_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """Map highly dynamic Wencai column headers to standard recap_engine column headers"""
        if df.empty:
            return df

        mapped = pd.DataFrame()

        # 1. Helper to find columns containing keywords
        def find_col(keywords: list[str]):
            for col in df.columns:
                for kw in keywords:
                    if kw in col:
                        return col
            return None

        code_col = find_col(["代码", "code"])
        name_col = find_col(["简称", "名称", "name"])
        boards_col = find_col(["连板", "连续涨停", "涨停天数"])
        time_col = find_col(["首次封板", "封板时间"])
        blown_col = find_col(["炸板"])
        float_mcap_col = find_col(["流通市值", "流通A股市值"])
        seal_funds_col = find_col(["封板资金"])
        turnover_col = find_col(["换手率"])
        sector_col = find_col(["行业", "所属行业"])

        # Extract stock code
        if code_col:
            # Map code and clean suffixes like .SZ, .SH
            mapped["代码"] = df[code_col].astype(str).apply(lambda x: re.sub(r'\D', '', x)[:6].zfill(6))
        else:
            mapped["代码"] = []
            return mapped

        # Map other columns with fallbacks
        mapped["名称"] = df[name_col] if name_col else "未知"
        mapped["连板数"] = df[boards_col].fillna(1).astype(int) if boards_col else 1

        # Format time to HHMMSS
        if time_col:
            def format_time(t):
                s = re.sub(r'\D', '', str(t))
                if len(s) >= 6:
                    return s[:6]
                elif len(s) == 4:
                    return s + "00"
                return "093000"  # default opening
            mapped["首次封板时间"] = df[time_col].apply(format_time)
        else:
            mapped["首次封板时间"] = "093000"

        mapped["炸板次数"] = df[blown_col].fillna(0).astype(int) if blown_col else 0

        # Mcap in RMB (recap_engine.py calculates seal_funds / float_mcap * 100)
        # So seal_funds and float_mcap must share same scale (absolute value)
        mapped["流通市值"] = df[float_mcap_col].fillna(0.0).astype(float) if float_mcap_col else 0.0
        mapped["封板资金"] = df[seal_funds_col].fillna(0.0).astype(float) if seal_funds_col else 0.0
        mapped["换手率"] = df[turnover_col].fillna(0.0).astype(float) if turnover_col else 0.0
        mapped["所属行业"] = df[sector_col].fillna("未分类").astype(str) if sector_col else "未分类"

        return mapped

    def get_limit_up_pool(self, date_str: str) -> FetchResult:
        query = f"{date_str}涨停且非ST，包含首次封板时间，连续涨停天数，换手率，所属行业，流通市值，封板资金，炸板次数"
        res = self.ths_client.wencai_nlp(query)
        if not (res.success and res.data):
            return FetchResult.unavailable(
                dataset_name="limit_up_pool",
                provider="thsdk",
                requested_trade_date=date_str,
                error_code="LIMIT_UP_POOL_UNAVAILABLE",
                error_message="thsdk limit-up pool unavailable",
                schema_version=1,
            )
        mapped = self._map_wencai_columns(res.df)
        if mapped.empty:
            return FetchResult.unavailable(
                dataset_name="limit_up_pool",
                provider="thsdk",
                requested_trade_date=date_str,
                error_code="EMPTY_POOL",
                error_message="thsdk limit-up pool empty after mapping",
                schema_version=1,
            )

        rename_to_en = {
            "代码": "code",
            "名称": "name",
            "连板数": "consecutive_boards",
            "首次封板时间": "first_seal_time",
            "炸板次数": "blown_count",
            "流通市值": "float_mcap_yuan",
            "封板资金": "seal_funds_yuan",
            "换手率": "turnover_pct",
            "所属行业": "sector",
        }
        df = mapped.rename(columns={src: dst for src, dst in rename_to_en.items() if src in mapped.columns})

        required = [
            "code", "name", "consecutive_boards", "first_seal_time", "blown_count",
            "float_mcap_yuan", "seal_funds_yuan", "turnover_pct", "sector",
        ]
        missing = [col for col in required if col not in df.columns]
        if missing:
            return FetchResult.invalid(
                dataset_name="limit_up_pool",
                provider="thsdk",
                requested_trade_date=date_str,
                error_message=f"limit_up_pool missing columns: {missing}",
                schema_version=1,
                payload=df,
            )

        def _normalize_time(value):
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
        normalized["consecutive_boards"] = pd.to_numeric(df["consecutive_boards"], errors="coerce").fillna(1).astype(int)
        normalized["first_seal_time"] = df["first_seal_time"].map(_normalize_time)
        normalized["blown_count"] = pd.to_numeric(df["blown_count"], errors="coerce").fillna(0).astype(int)
        normalized["float_mcap_yuan"] = pd.to_numeric(df["float_mcap_yuan"], errors="coerce")
        normalized["seal_funds_yuan"] = pd.to_numeric(df["seal_funds_yuan"], errors="coerce")
        normalized["turnover_pct"] = pd.to_numeric(df["turnover_pct"], errors="coerce")
        normalized["sector"] = df["sector"].fillna("UNKNOWN").astype(str).str.strip().replace("", "UNKNOWN")
        normalized["price"] = 0.0  # wencai may not return price; placeholder used in downstream
        normalized["change_pct"] = 0.0
        normalized["is_st"] = normalized["name"].str.contains(r"^(\*?ST|S\*ST|退市)", regex=True)

        before = len(normalized)
        normalized = normalized[
            normalized["code"].str.fullmatch(r"\d{6}", na=False)
            & normalized["name"].ne("")
            & normalized["consecutive_boards"].notna()
            & normalized["blown_count"].notna()
            & normalized["float_mcap_yuan"].notna()
            & normalized["seal_funds_yuan"].notna()
            & normalized["turnover_pct"].notna()
            & normalized["sector"].ne("")
        ].copy()
        if normalized.empty:
            return FetchResult.invalid(
                dataset_name="limit_up_pool",
                provider="thsdk",
                requested_trade_date=date_str,
                error_message="thsdk limit-up pool contains no valid rows after normalization",
                schema_version=1,
                payload=df,
            )

        normalized["consecutive_boards"] = normalized["consecutive_boards"].astype(int)
        normalized["blown_count"] = normalized["blown_count"].astype(int)
        normalized["is_st"] = normalized["is_st"].astype(bool)
        normalized["trade_date"] = date_str

        valid, error = validate_limit_up_pool(normalized)
        if not valid:
            return FetchResult.invalid(
                dataset_name="limit_up_pool",
                provider="thsdk",
                requested_trade_date=date_str,
                error_message=error or "limit_up_pool invalid",
                schema_version=1,
                payload=normalized,
            )

        warnings = []
        if len(normalized) != before:
            warnings.append(f"dropped {before - len(normalized)} malformed limit-up rows")
        kwargs = dict(
            dataset_name="limit_up_pool",
            provider="thsdk",
            requested_trade_date=date_str,
            as_of=date_str,
            payload=normalized,
            schema_version=1,
        )
        if warnings:
            return FetchResult.degraded(**kwargs, warnings=warnings)
        return FetchResult.ok(**kwargs)

    def get_limit_down_pool(self, date_str: str) -> pd.DataFrame:
        query = f"{date_str}跌停且非ST"
        res = self.ths_client.wencai_nlp(query)
        if res.success and res.data:
            df = res.df.copy()
            df["代码"] = df.iloc[:, 0].astype(str).apply(lambda x: re.sub(r'\D', '', x)[:6].zfill(6))
            return df
        return pd.DataFrame()

    def get_concept_reasons(self, date_str: str) -> dict[str, str]:
        query = f"{date_str}涨停原因"
        res = self.ths_client.wencai_nlp(query)
        reasons = {}
        if res.success and res.data:
            df = res.df
            code_col = None
            reason_col = None
            for col in df.columns:
                if "代码" in col:
                    code_col = col
                elif "涨停原因" in col or "题材" in col or "概念" in col:
                    reason_col = col

            if code_col and reason_col:
                for _, row in df.iterrows():
                    raw_code = str(row[code_col])
                    code = re.sub(r'\D', '', raw_code)[:6].zfill(6)
                    reasons[code] = str(row[reason_col])
        return reasons

    def get_northbound_flow(self, date_str: str) -> tuple[float, float]:
        # Query northbound capital flow for date_str via NLP
        query = f"{date_str}北向资金净流入"
        res = self.ths_client.wencai_nlp(query)
        hgt = 0.0
        sgt = 0.0
        if res.success and res.data:
            df = res.df
            # Typically returns columns like '沪股通资金净流入', '深股通资金净流入'
            for col in df.columns:
                if "沪股通" in col:
                    try:
                        hgt = float(df[col].iloc[0])
                    except Exception:
                        pass
                elif "深股通" in col:
                    try:
                        sgt = float(df[col].iloc[0])
                    except Exception:
                        pass
        return hgt, sgt

    def get_finance_data(self, code: str) -> dict[str, Any]:
        # Query finance indicators via Wencai NLP
        query = f"{code} 净利润，净资产，主营业务收入，总股本"
        res = self.ths_client.wencai_nlp(query)
        finance_dict = {}
        if res.success and res.data:
            df = res.df
            if not df.empty:
                # Find matching columns
                def find_col(keywords):
                    for col in df.columns:
                        for kw in keywords:
                            if kw in col:
                                return col
                    return None

                lirun_col = find_col(["净利润"])
                zichan_col = find_col(["净资产"])
                shouru_col = find_col(["主营收入", "主营业务收入"])
                guben_col = find_col(["总股本"])

                def clean_val(val):
                    try:
                        return float(val)
                    except Exception:
                        return 0.0

                row = df.iloc[0]
                finance_dict = {
                    "jinglirun": clean_val(row[lirun_col]) if lirun_col else 0.0,
                    "jingzichan": clean_val(row[zichan_col]) if zichan_col else 0.0,
                    "zhuyingshouru": clean_val(row[shouru_col]) if shouru_col else 0.0,
                    "zongguben": clean_val(row[guben_col]) if guben_col else 0.0
                }
        return finance_dict

    def get_stock_comments(self) -> pd.DataFrame:
        import akshare as ak
        try:
            raw = ak.stock_comment_em()
            return normalize_stock_comments(raw)
        except Exception as e:
            print(f"[thsdk] Error fetching stock comments: {e}")
            return pd.DataFrame()

    def get_lhb_statistics(self) -> pd.DataFrame:
        import akshare as ak
        try:
            raw = ak.stock_lhb_stock_statistic_em(symbol="近一月")
            return normalize_lhb_statistics(raw)
        except Exception as e:
            print(f"[thsdk] Error fetching LHB statistics: {e}")
            return pd.DataFrame()

    def get_lhb_details(self, start_date: str, end_date: str) -> pd.DataFrame:
        import akshare as ak
        try:
            raw = ak.stock_lhb_detail_em(start_date=start_date, end_date=end_date)
            return normalize_lhb_details(raw)
        except Exception as e:
            print(f"[thsdk] Error fetching LHB details: {e}")
            return pd.DataFrame()
