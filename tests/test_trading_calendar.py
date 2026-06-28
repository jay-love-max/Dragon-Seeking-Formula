"""Phase 1 交易日历验收 — exchange_calendars XSHG 主日历。

覆盖方案 8.1/8.2 与验收 2.1:2026-06-19 等休市工作日不会运行或发布。
本地、确定,不依赖实时网络(AGENTS.md)。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

import trading_calendar as tc
from trading_calendar import CalendarConflict

SHANGHAI = ZoneInfo("Asia/Shanghai")


class TestGoldenTradingDays:
    """金样本交易日的确定性。"""

    def test_2026_06_19_is_non_trading(self):
        # 端午节假期区间 — 交易日闸门必须阻止发布
        assert tc.is_trading_day("2026-06-19") is False

    @pytest.mark.parametrize("d", ["2026-06-24", "2026-06-25", "2026-06-26"])
    def test_golden_dates_are_trading_days(self, d):
        assert tc.is_trading_day(d) is True

    @pytest.mark.parametrize("d,expected_prev", [
        ("2026-06-25", date(2026, 6, 24)),  # F18 金样本:25 的 T-1 = 24
        ("2026-06-24", date(2026, 6, 23)),
        ("2026-06-26", date(2026, 6, 25)),
    ])
    def test_previous_trading_day(self, d, expected_prev):
        assert tc.previous_trading_day(d) == expected_prev

    def test_previous_of_non_trading_day(self):
        # 2026-06-19 非交易日;其前一交易日为 06-18
        assert tc.previous_trading_day("2026-06-19") == date(2026, 6, 18)

    def test_next_trading_day(self):
        assert tc.next_trading_day("2026-06-19") == date(2026, 6, 22)


class TestInputFormats:
    def test_accepts_date_object(self):
        assert tc.is_trading_day(date(2026, 6, 24)) is True

    def test_accepts_compact_string(self):
        assert tc.is_trading_day("20260619") is False

    def test_accepts_datetime_converted_to_shanghai(self):
        # UTC 凌晨的 06-24 在上海时区仍是 06-24
        dt = datetime(2026, 6, 24, 1, 0, tzinfo=ZoneInfo("UTC"))
        assert tc.is_trading_day(dt) is True

    def test_datetime_just_before_midnight_shanghai(self):
        # UTC 16:00 = 上海次日 00:00 → 06-25
        dt = datetime(2026, 6, 24, 16, 0, tzinfo=ZoneInfo("UTC"))
        assert tc.is_trading_day(dt) is True
        assert tc._to_date(dt) == date(2026, 6, 25)


class TestSessionsInRange:
    def test_closed_interval_includes_endpoints(self):
        sessions = tc.sessions_in_range("2026-06-24", "2026-06-26")
        assert sessions == [date(2026, 6, 24), date(2026, 6, 25), date(2026, 6, 26)]

    def test_skips_non_trading_day_in_range(self):
        sessions = tc.sessions_in_range("2026-06-18", "2026-06-24")
        assert date(2026, 6, 19) not in sessions
        assert date(2026, 6, 20) not in sessions  # 周六
        assert date(2026, 6, 21) not in sessions  # 周日
        assert date(2026, 6, 22) in sessions


class TestCorroboration:
    def test_conflict_when_index_dates_lack_trading_day(self):
        with pytest.raises(CalendarConflict):
            tc.assert_corroborates("2026-06-24", index_dates=["2026-06-23", "2026-06-25"])

    def test_no_conflict_when_corroborates(self):
        tc.assert_corroborates("2026-06-24", index_dates=["2026-06-24", "2026-06-25"])

    def test_non_trading_day_never_conflicts(self):
        tc.assert_corroborates("2026-06-19", index_dates=["2026-06-18"])

    def test_none_index_dates_does_not_raise(self):
        tc.assert_corroborates("2026-06-24", index_dates=None)


class TestMetadata:
    def test_metadata_has_calendar_name_and_version(self):
        meta = tc.calendar_metadata()
        assert meta["calendar_name"] == "XSHG"
        assert "exchange_calendars_version" in meta
        assert "first_session" in meta
        assert "last_session" in meta


class TestCorroborationEdgeCases:
    """佐证边界场景 — 空列表视为不可用(方案 H-1 修复)。"""

    def test_empty_index_dates_on_trading_day_no_conflict(self):
        """空佐证列表在交易日不应触发冲突(视为不可用)。"""
        tc.assert_corroborates("2026-06-24", index_dates=[])

    def test_none_index_dates_on_trading_day_no_conflict(self):
        """佐证源不可用(None)时不阻断。"""
        tc.assert_corroborates("2026-06-24", index_dates=None)

    def test_empty_index_dates_on_non_trading_day_no_conflict(self):
        """非交易日+空佐证列表不应冲突(非交易日直接跳过)。"""
        tc.assert_corroborates("2026-06-19", index_dates=[])

    def test_conflict_when_dates_available_but_missing(self):
        """佐证列表非空但不含目标交易日时仍应冲突。"""
        with pytest.raises(CalendarConflict):
            tc.assert_corroborates("2026-06-24", index_dates=["2026-06-23", "2026-06-25"])


class TestHolidayBoundaries:
    """节假日边界场景。"""

    @pytest.mark.parametrize("d", [
        "2026-01-01",  # 元旦
        "2026-05-01",  # 劳动节
        "2026-10-01",  # 国庆节
    ])
    def test_known_holidays_are_non_trading(self, d):
        assert tc.is_trading_day(d) is False

    def test_sessions_across_year_boundary(self):
        """跨年区间应正确返回交易日,不含元旦。"""
        sessions = tc.sessions_in_range("2025-12-29", "2026-01-05")
        assert date(2026, 1, 1) not in sessions
        assert len(sessions) > 0


class TestCacheRefresh:
    """缓存跨日刷新(M-2 修复)。"""

    def test_maybe_refresh_sets_cache_date(self):
        """首次调用应设置 _cache_date。"""
        tc._cache_date = None  # 重置
        tc._maybe_refresh_calendar()
        assert tc._cache_date is not None

    def test_maybe_refresh_idempotent(self):
        """重复调用不报错,日期不变时缓存不被清除。"""
        tc._cache_date = None
        tc._maybe_refresh_calendar()
        first = tc._cache_date
        tc._maybe_refresh_calendar()
        assert tc._cache_date == first

    def test_maybe_refresh_clears_on_date_change(self):
        """日期变化时应清除 _calendar 缓存。"""
        from unittest.mock import patch

        import trading_calendar

        # 先正常初始化
        tc._cache_date = None
        tc._maybe_refresh_calendar()

        # mock 日期前进一天
        fake_tomorrow = tc._cache_date + timedelta(days=1)
        fake_dt = datetime(
            fake_tomorrow.year, fake_tomorrow.month, fake_tomorrow.day,
            12, 0, tzinfo=tc.SHANGHAI_TZ,
        )
        with patch.object(trading_calendar, "datetime", wraps=datetime) as mock_dt:
            mock_dt.now.return_value = fake_dt
            tc._maybe_refresh_calendar()

        assert tc._cache_date == fake_tomorrow
