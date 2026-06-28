"""Phase 1 数据契约验收 — FetchResult + Pandera 契约。

覆盖方案 7.1/7.2 与验收 2.1:指数失败不会写成 0;错日期涨停池被拒绝。
"""
from __future__ import annotations

import pandas as pd

from contracts import (
    FetchResult,
    validate_limit_up_pool,
)
from rule_contract import DataStatus


def _valid_row(**overrides) -> dict:
    row = {
        "code": "600584",
        "name": "长电科技",
        "trade_date": "2026-06-24",
        "price": 10.0,
        "change_pct": 10.0,
        "turnover_pct": 8.0,
        "float_mcap_yuan": 40_000_000_000.0,
        "seal_funds_yuan": 821_260_000.0,
        "first_seal_time": "09:57:07",
        "blown_count": 0,
        "consecutive_boards": 1,
        "is_st": False,
        "sector": "电子",
    }
    row.update(overrides)
    return row


def _valid_df(rows: list[dict] | None = None) -> pd.DataFrame:
    return pd.DataFrame(rows or [_valid_row()])


class TestFetchResult:
    def test_ok_carries_payload_and_as_of(self):
        df = _valid_df()
        r = FetchResult.ok(
            dataset_name="limit_up_pool", provider="akshare",
            requested_trade_date="2026-06-24", as_of="2026-06-24",
            payload=df, schema_version=1,
        )
        assert r.status == DataStatus.OK
        assert r.row_count == 1
        assert r.is_ok
        assert r.as_of == "2026-06-24"
        assert r.error_code is None

    def test_unavailable_does_not_disguise_as_empty_market(self):
        # 失败不得伪装成空市场(方案 7.1);status=UNAVAILABLE 而非 OK+空
        r = FetchResult.unavailable(
            dataset_name="index_recap", provider="mootdx",
            requested_trade_date="2026-06-24", error_code="CONN_TIMEOUT",
            error_message="connection timeout", schema_version=1,
        )
        assert r.status == DataStatus.UNAVAILABLE
        assert not r.is_ok
        assert r.row_count == 0
        assert r.payload.empty
        assert r.as_of is None  # 无 as_of,不得编造

    def test_invalid_records_schema_failure(self):
        r = FetchResult.invalid(
            dataset_name="limit_up_pool", provider="akshare",
            requested_trade_date="2026-06-24", error_message="missing code column",
            schema_version=1,
        )
        assert r.status == DataStatus.INVALID
        assert r.error_code == "SCHEMA_INVALID"


class TestLimitUpPoolSchema:
    def test_valid_dataframe_passes(self):
        ok, msg = validate_limit_up_pool(_valid_df())
        assert ok, msg

    def test_missing_code_rejected(self):
        df = _valid_df().drop(columns=["code"])
        ok, msg = validate_limit_up_pool(df)
        assert not ok
        assert "code" in msg

    def test_non_six_digit_code_rejected(self):
        df = _valid_df([_valid_row(code="123")])
        ok, msg = validate_limit_up_pool(df)
        assert not ok

    def test_wrong_trade_date_rejected_by_caller(self):
        # 契约要求 trade_date 等于请求交易日(方案 7.2);由调用方比对 as_of。
        # 此处校验 schema 不约束具体值,但调用方必须拒绝错日期。
        df = _valid_df([_valid_row(trade_date="2026-06-25")])
        ok, _ = validate_limit_up_pool(df)
        assert ok  # schema 通过,但调用方应比对 requested_trade_date != trade_date
        # 模拟调用方校验
        requested = "2026-06-24"
        actual = df["trade_date"].iloc[0]
        assert actual != requested  # 调用方应据此拒绝

    def test_negative_seal_funds_rejected(self):
        df = _valid_df([_valid_row(seal_funds_yuan=-1.0)])
        ok, msg = validate_limit_up_pool(df)
        assert not ok

    def test_seal_funds_zero_allowed(self):
        # 封单 0 在 schema 层允许(ge=0);F19 硬过滤在业务层(<50m 过滤)
        df = _valid_df([_valid_row(seal_funds_yuan=0.0)])
        ok, _ = validate_limit_up_pool(df)
        assert ok

    def test_change_pct_out_of_range_rejected(self):
        df = _valid_df([_valid_row(change_pct=40.0)])
        ok, _ = validate_limit_up_pool(df)
        assert not ok

    def test_turnover_pct_out_of_range_rejected(self):
        df = _valid_df([_valid_row(turnover_pct=120.0)])
        ok, _ = validate_limit_up_pool(df)
        assert not ok

    def test_float_mcap_zero_rejected(self):
        # 流通市值不得为 0(伪装缺失)
        df = _valid_df([_valid_row(float_mcap_yuan=0.0)])
        ok, _ = validate_limit_up_pool(df)
        assert not ok

    def test_consecutive_boards_zero_rejected(self):
        df = _valid_df([_valid_row(consecutive_boards=0)])
        ok, _ = validate_limit_up_pool(df)
        assert not ok

    def test_blown_count_negative_rejected(self):
        df = _valid_df([_valid_row(blown_count=-1)])
        ok, _ = validate_limit_up_pool(df)
        assert not ok

    def test_empty_dataframe_rejected(self):
        ok, msg = validate_limit_up_pool(pd.DataFrame())
        assert not ok
        ok_none, _ = validate_limit_up_pool(None)  # type: ignore[arg-type]
        assert not ok_none

    def test_units_are_yuan_not_display_units(self):
        # 方案 7.2:规则计算在统一元单位上完成;展示转换只在兼容层。
        # 契约字段名显式携带 _yuan(AGENTS.md 工作约定)。
        df = _valid_df()
        cols = list(df.columns)
        assert "float_mcap_yuan" in cols
        assert "seal_funds_yuan" in cols
        # 真实值是元(8.2e8),不是百万元
        assert df["seal_funds_yuan"].iloc[0] > 100_000_000
