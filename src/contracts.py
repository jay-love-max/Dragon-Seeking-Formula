"""数据契约 — FetchResult/DataEnvelope 与 Pandera schema(Phase 1)。

方案 7.1:每次适配器调用返回结构化结果,禁止再使用"空 DataFrame=没有行情"
和"零值=请求失败"的混合语义。缺失或过期数据不得用 0 伪装(AGENTS.md)。
方案 7.2:涨停池关键字段做列、类型、范围和跨列校验;金额统一"元"单位。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

import pandas as pd
import pandera.pandas as pa
from pandera.typing import Series

from rule_contract import DataStatus


@dataclass
class FetchResult:
    """适配器调用结果。替代散落的 fillna、隐式类型转换和静默缺列。

    payload 为原始 DataFrame;失败时 payload 可为空 DataFrame,
    但 status 必须为 UNAVAILABLE/INVALID,不得把空当成"没有行情"。
    """

    dataset_name: str
    provider: str
    requested_trade_date: str
    as_of: str | None  # 数据本身所属交易日(失败时为 None)
    fetched_at: str  # ISO 时间
    status: DataStatus
    row_count: int
    schema_version: int
    payload: pd.DataFrame = field(default_factory=pd.DataFrame)
    warnings: list[str] = field(default_factory=list)
    error_code: str | None = None
    error_message: str | None = None

    @classmethod
    def ok(
        cls,
        *,
        dataset_name: str,
        provider: str,
        requested_trade_date: str,
        as_of: str,
        payload: pd.DataFrame,
        schema_version: int,
        warnings: list[str] | None = None,
    ) -> FetchResult:
        return cls(
            dataset_name=dataset_name, provider=provider,
            requested_trade_date=requested_trade_date, as_of=as_of,
            fetched_at=_utc_now(), status=DataStatus.OK,
            row_count=len(payload), schema_version=schema_version,
            payload=payload, warnings=warnings or [],
        )

    @classmethod
    def unavailable(
        cls,
        *,
        dataset_name: str,
        provider: str,
        requested_trade_date: str,
        error_code: str,
        error_message: str,
        schema_version: int,
    ) -> FetchResult:
        # 失败不得伪装成空市场;payload 为空 DataFrame,status=UNAVAILABLE
        return cls(
            dataset_name=dataset_name, provider=provider,
            requested_trade_date=requested_trade_date, as_of=None,
            fetched_at=_utc_now(), status=DataStatus.UNAVAILABLE,
            row_count=0, schema_version=schema_version,
            payload=pd.DataFrame(),
            error_code=error_code, error_message=error_message,
        )

    @classmethod
    def invalid(
        cls,
        *,
        dataset_name: str,
        provider: str,
        requested_trade_date: str,
        error_message: str,
        schema_version: int,
        payload: pd.DataFrame | None = None,
    ) -> FetchResult:
        return cls(
            dataset_name=dataset_name,
            provider=provider,
            requested_trade_date=requested_trade_date,
            as_of=None,
            fetched_at=_utc_now(),
            status=DataStatus.INVALID,
            row_count=0,
            schema_version=schema_version,
            payload=payload if payload is not None else pd.DataFrame(),
            error_code="SCHEMA_INVALID",
            error_message=error_message,
        )

    @property
    def is_ok(self) -> bool:
        return self.status == DataStatus.OK


# --- Pandera 契约(方案 7.2) ---

LIMIT_UP_POOL_SCHEMA_VERSION = 1


class LimitUpPoolSchema(pa.DataFrameModel):
    """涨停池契约。金额统一"元"单位;展示转换只发生在持久化兼容层/API 层。"""

    code: Series[str] = pa.Field(str_matches=r"^\d{6}$", nullable=False)
    name: Series[str] = pa.Field(nullable=False)
    trade_date: Series[str] = pa.Field(nullable=False)
    price: Series[float] = pa.Field(gt=0, nullable=False)
    change_pct: Series[float] = pa.Field(in_range={"min_value": -35, "max_value": 35})
    turnover_pct: Series[float] = pa.Field(in_range={"min_value": 0, "max_value": 100})
    float_mcap_yuan: Series[float] = pa.Field(gt=0, nullable=False)
    seal_funds_yuan: Series[float] = pa.Field(ge=0, nullable=False)
    first_seal_time: Series[str] = pa.Field(nullable=True)
    blown_count: Series[int] = pa.Field(ge=0, nullable=False)
    consecutive_boards: Series[int] = pa.Field(ge=1, nullable=False)
    is_st: Series[bool] = pa.Field(nullable=False)
    sector: Series[str] = pa.Field(nullable=False)

    class Config:
        coerce = True
        strict = False  # 允许额外列(concept 等),只校验关键字段


def validate_limit_up_pool(df: pd.DataFrame) -> tuple[bool, str | None]:
    """校验涨停池 DataFrame 是否符合契约。

    返回 (是否通过, 错误信息)。失败时调用方应构造 FetchResult.invalid,
    而非静默 fillna 后继续发布。
    """
    if df is None or df.empty:
        return False, "limit_up_pool is empty"
    try:
        LimitUpPoolSchema.validate(df, lazy=True)
    except pa.errors.SchemaErrors as e:
        return False, str(e)
    return True, None


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()
