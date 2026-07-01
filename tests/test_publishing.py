"""Tests for publishing gate and data quality modules."""
from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from contracts import FetchResult
from data_quality import check_source_freshness, index_majority_available
from publishing import evaluate_publishable
from rule_contract import DataStatus


def _ok_source(dataset: str, as_of: str | None = None) -> FetchResult:
    return FetchResult.ok(
        dataset_name=dataset,
        provider="test",
        requested_trade_date="2026-07-01",
        as_of=as_of or "2026-07-01",
        payload=pd.DataFrame(),
        schema_version=1,
    )


def _invalid_source(dataset: str) -> FetchResult:
    return FetchResult.invalid(
        dataset_name=dataset,
        provider="test",
        requested_trade_date="2026-07-01",
        error_message="simulated failure",
        schema_version=1,
    )


def _unavailable_source(dataset: str) -> FetchResult:
    return FetchResult.unavailable(
        dataset_name=dataset,
        provider="test",
        requested_trade_date="2026-07-01",
        error_code="SIMULATED",
        error_message="unavailable",
        schema_version=1,
    )


# --- evaluate_publishable ---


class TestEvaluatePublishable:
    def test_all_ok_publishable(self):
        result = evaluate_publishable(
            is_trading_day=True,
            rule_config_valid=True,
            migration_ok=True,
            sources={
                "limit_up_pool": _ok_source("limit_up_pool"),
                "sh_index": _ok_source("sh_index"),
                "sz_index": _ok_source("sz_index"),
                "cy_index": _ok_source("cy_index"),
            },
        )
        assert result.publishable
        assert result.reason_codes == []

    def test_non_trading_day_blocks(self):
        result = evaluate_publishable(
            is_trading_day=False, rule_config_valid=True, migration_ok=True,
            sources={},
        )
        assert not result.publishable
        assert "TRADING_DAY_INVALID" in result.reason_codes

    def test_non_trading_day_ok_when_require_false(self):
        result = evaluate_publishable(
            is_trading_day=False, rule_config_valid=True, migration_ok=True,
            sources={
                "limit_up_pool": _ok_source("limit_up_pool"),
                "sh_index": _ok_source("sh_index"),
                "sz_index": _ok_source("sz_index"),
                "cy_index": _ok_source("cy_index"),
            },
            require_trading_day=False,
        )
        assert result.publishable

    def test_invalid_limit_up_pool_blocks(self):
        result = evaluate_publishable(
            is_trading_day=True, rule_config_valid=True, migration_ok=True,
            sources={
                "limit_up_pool": _invalid_source("limit_up_pool"),
                "sh_index": _ok_source("sh_index"),
                "sz_index": _ok_source("sz_index"),
                "cy_index": _ok_source("cy_index"),
            },
        )
        assert not result.publishable
        assert "LIMIT_UP_POOL_UNAVAILABLE" in result.reason_codes

    def test_limit_up_pool_not_required_when_flag_false(self):
        result = evaluate_publishable(
            is_trading_day=True, rule_config_valid=True, migration_ok=True,
            sources={
                "limit_up_pool": _invalid_source("limit_up_pool"),
                "sh_index": _ok_source("sh_index"),
                "sz_index": _ok_source("sz_index"),
                "cy_index": _ok_source("cy_index"),
            },
            require_limit_up_pool_valid=False,
        )
        assert result.publishable

    def test_missing_indices_blocks(self):
        result = evaluate_publishable(
            is_trading_day=True, rule_config_valid=True, migration_ok=True,
            sources={},
        )
        assert not result.publishable
        assert "INDEX_MAJORITY_UNAVAILABLE" in result.reason_codes

    def test_index_minority_failure_still_ok(self):
        result = evaluate_publishable(
            is_trading_day=True, rule_config_valid=True, migration_ok=True,
            sources={
                "sh_index": _ok_source("sh_index"),
                "sz_index": _ok_source("sz_index"),
                "cy_index": _invalid_source("cy_index"),
            },
        )
        assert result.publishable

    def test_invalid_config_blocks(self):
        result = evaluate_publishable(
            is_trading_day=True, rule_config_valid=False, migration_ok=True,
            sources={},
        )
        assert not result.publishable
        assert "RULE_CONFIG_INVALID" in result.reason_codes

    def test_migration_failure_blocks(self):
        result = evaluate_publishable(
            is_trading_day=True, rule_config_valid=True, migration_ok=False,
            sources={},
        )
        assert not result.publishable
        assert "MIGRATION_FAILED" in result.reason_codes

    def test_multiple_failures_all_recorded(self):
        result = evaluate_publishable(
            is_trading_day=False, rule_config_valid=False, migration_ok=False,
            sources={"limit_up_pool": _invalid_source("limit_up_pool")},
        )
        assert len(result.reason_codes) == 5  # TRADING_DAY + RULE_CONFIG + MIGRATION + LIMIT_UP + INDEX

    def test_index_majority_unavailable_when_all_indices_missing(self):
        assert not index_majority_available({}, require_majority=True)


class TestIndexMajorityAvailable:
    def test_no_indices_allowed_when_not_required(self):
        assert index_majority_available({}, require_majority=False)

    def test_all_ok_passes(self):
        sources = {
            "sh_index": _ok_source("sh_index"),
            "sz_index": _ok_source("sz_index"),
            "cy_index": _ok_source("cy_index"),
        }
        assert index_majority_available(sources, require_majority=True)

    def test_one_failure_still_passes(self):
        sources = {
            "sh_index": _ok_source("sh_index"),
            "sz_index": _ok_source("sz_index"),
            "cy_index": _invalid_source("cy_index"),
        }
        assert index_majority_available(sources, require_majority=True)

    def test_two_failures_fails(self):
        sources = {
            "sh_index": _ok_source("sh_index"),
            "sz_index": _invalid_source("sz_index"),
            "cy_index": _invalid_source("cy_index"),
        }
        assert not index_majority_available(sources, require_majority=True)

    def test_non_index_sources_ignored(self):
        sources = {
            "limit_up_pool": _ok_source("limit_up_pool"),
            "sz_index": _invalid_source("sz_index"),
            "cy_index": _invalid_source("cy_index"),
        }
        assert not index_majority_available(sources, require_majority=True)


class TestCheckSourceFreshness:
    def test_no_stale_sources(self):
        srcs = {"pool": _ok_source("pool")}
        assert check_source_freshness(srcs, max_age_seconds=99999) == []

    def test_stale_source_detected(self):
        from datetime import UTC
        old_fetched = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        src = FetchResult(
            dataset_name="pool", provider="test",
            requested_trade_date="2026-07-01",
            as_of=old_fetched, fetched_at=old_fetched,
            status=DataStatus.OK, row_count=1, schema_version=1,
            payload=pd.DataFrame(),
        )
        warnings = check_source_freshness({"pool": src}, max_age_seconds=10)
        assert len(warnings) == 1
        assert "stale" in warnings[0]

    def test_non_ok_sources_skipped(self):
        srcs = {"pool": _unavailable_source("pool")}
        assert check_source_freshness(srcs, max_age_seconds=10) == []

    def test_unparsable_fetched_at_warns(self):
        src = FetchResult(
            dataset_name="pool", provider="test",
            requested_trade_date="2026-07-01",
            as_of="2026-07-01", fetched_at="not-a-date",
            status=DataStatus.OK, row_count=1, schema_version=1,
            payload=pd.DataFrame(),
        )
        warnings = check_source_freshness({"pool": src}, max_age_seconds=10)
        assert len(warnings) == 1
        assert "unparsable" in warnings[0]
