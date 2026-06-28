"""Trading calendar service — Phase 1.

主日历为 exchange_calendars 的 XSHG(A 股上海),替代手写节假日表与周一至周五回退。
所有时间先转 Asia/Shanghai 再判定。盘后 (recap_engine) 与盘中 (data_pipeline)
必须消费同一服务,禁止各自复制交易日逻辑。

方案 8.2:AKShare tool_trade_date_hist_sina 静态范围可能滞后,只作校验源;
mootdx 指数日期用于运行后佐证,失败时不再退化为普通工作日。
发现主日历与真实指数交易日不一致时,任务进入 BLOCKED 并记录 CALENDAR_CONFLICT。
"""
from __future__ import annotations

from datetime import date, datetime
from functools import lru_cache
from typing import Any
from zoneinfo import ZoneInfo

import exchange_calendars as xcals

from rule_contract import ReasonCode

SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
XSHG_CALENDAR_NAME = "XSHG"


class CalendarConflict(Exception):
    """主日历与佐证来源交易日判定不一致(方案 8.2)。"""

    reason_code = ReasonCode.CALENDAR_CONFLICT


_cache_date: date | None = None


def _maybe_refresh_calendar() -> None:
    """若上海日期变化则清除缓存(长期运行进程跨日刷新)。

    仅适用于单线程 / GIL 保护的 cron 场景;多线程环境应替换为 threading.Lock。
    """
    global _cache_date
    today = datetime.now(SHANGHAI_TZ).date()
    if _cache_date is None:
        _cache_date = today
    elif _cache_date != today:
        _calendar.cache_clear()
        _cache_date = today


@lru_cache(maxsize=1)
def _calendar() -> Any:
    """加载并缓存 XSHG 日历(含当前年份前后各一年 sessions)。"""
    return xcals.get_calendar(XSHG_CALENDAR_NAME)


def _to_date(value: str | date | datetime) -> date:
    """接受 'YYYY-MM-DD' / date / datetime,统一为 date。

    datetime 先转 Asia/Shanghai 再取日期,避免跨时区错位。
    """
    if isinstance(value, datetime):
        return value.astimezone(SHANGHAI_TZ).date()
    if isinstance(value, date):
        return value
    # str
    text = str(value).strip()
    # 兼容 '20260619'
    if len(text) == 8 and text.isdigit():
        return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
    return datetime.fromisoformat(text).astimezone(SHANGHAI_TZ).date()


def is_trading_day(value: str | date | datetime) -> bool:
    """只调用 XSHG is_session。非交易日返回 False。"""
    _maybe_refresh_calendar()
    d = _to_date(value)
    return bool(_calendar().is_session(d))


def previous_trading_day(value: str | date | datetime) -> date:
    """返回严格早于 value 的最近一个交易日。

    value 本身是否为交易日不影响结果;返回其前一个交易日。
    用于 F18 计算 T-1(方案 11.1:必须通过交易日历寻找 T-1)。
    """
    d = _to_date(value)
    cal = _calendar()
    if cal.is_session(d):
        return cal.previous_session(d).date()
    # value 非交易日:映射到最近的过往交易日即答案(该日严格早于 value)
    return cal.date_to_session(d, direction="previous").date()


def next_trading_day(value: str | date | datetime) -> date:
    """返回严格晚于 value 的最近一个交易日。"""
    d = _to_date(value)
    cal = _calendar()
    if cal.is_session(d):
        return cal.next_session(d).date()
    # value 非交易日:映射到最近的未来交易日即答案(该日严格晚于 value)
    return cal.date_to_session(d, direction="next").date()


def sessions_in_range(start: str | date, end: str | date) -> list[date]:
    """闭区间 [start, end] 内的全部交易日。"""
    s = _to_date(start)
    e = _to_date(end)
    return [ts.date() for ts in _calendar().sessions_in_range(s, e)]


def calendar_metadata() -> dict[str, Any]:
    """交易日历版本与覆盖区间,写入运行记录(方案 8.1)。"""
    cal = _calendar()
    return {
        "calendar_name": XSHG_CALENDAR_NAME,
        "exchange_calendars_version": xcals.__version__,
        "first_session": str(cal.first_session),
        "last_session": str(cal.last_session),
    }


def assert_corroborates(
    value: str | date | datetime, index_dates: list[str] | None
) -> None:
    """用真实指数交易日列表佐证主日历(方案 8.2)。

    index_dates: 真实指数数据里出现的交易日列表('YYYY-MM-DD')。
    若主日历判定 value 为交易日但佐证列表不含它,抛 CalendarConflict,
    而非自动选择某一来源继续发布。
    """
    if not is_trading_day(value):
        return
    if not index_dates:  # None 或空列表均视为佐证源不可用
        return
    d = _to_date(value)
    iso = d.isoformat()
    if iso not in set(index_dates):
        raise CalendarConflict(
            f"主日历判定 {iso} 为交易日,但指数佐证列表不含该日期"
        )


def now_shanghai() -> datetime:
    """当前 Asia/Shanghai 时间(用于新鲜度与发布时间判断)。"""
    return datetime.now(SHANGHAI_TZ)
