import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import recap_engine

SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


def test_default_date_rolls_back_on_non_trading_day():
    date_str, observation_only, defaulted = recap_engine.resolve_recap_date(
        None,
        ["2026-06-24", "2026-06-25", "2026-06-26"],
        now=datetime(2026, 6, 27, 12, 0),
    )

    assert date_str == "2026-06-26"
    assert observation_only is True
    assert defaulted is True


def test_force_non_trading_day_keeps_today_observation_only():
    date_str, observation_only, defaulted = recap_engine.resolve_recap_date(
        None,
        ["2026-06-24", "2026-06-25", "2026-06-26"],
        force_non_trading_day=True,
        now=datetime(2026, 6, 27, 12, 0),
    )

    assert date_str == "2026-06-27"
    assert observation_only is True
    assert defaulted is False


def test_explicit_date_is_preserved():
    date_str, observation_only, defaulted = recap_engine.resolve_recap_date(
        "2026-06-27",
        ["2026-06-24", "2026-06-25", "2026-06-26"],
        now=datetime(2026, 6, 27, 12, 0),
    )

    assert date_str == "2026-06-27"
    assert observation_only is False
    assert defaulted is False


def test_naive_now_is_treated_as_shanghai_time():
    """naive datetime（无 tzinfo）默认按 Asia/Shanghai 解释,避免容器 TZ=UTC 漂移。

    回归遗留问题A:resolve_recap_date 不应直接用 datetime.now(),而应通过
    now_shanghai()。这里用 UTC 时刻构造 naive 输入,验证 today 解析到上海日期。
    """
    # 2026-06-27 16:00 UTC == 2026-06-28 00:00 Asia/Shanghai (周日,非交易日)
    naive_utc = datetime(2026, 6, 27, 16, 0)
    date_str, observation_only, defaulted = recap_engine.resolve_recap_date(
        None,
        ["2026-06-24", "2026-06-25", "2026-06-26"],
        now=naive_utc,
    )

    assert date_str == "2026-06-26"
    assert observation_only is True
    assert defaulted is True


def test_aware_now_uses_shanghai_date():
    """带 tzinfo 的 UTC 时刻应正确映射到上海日期,而非沿用 UTC 日期。"""
    aware_utc = datetime(2026, 6, 27, 16, 0, tzinfo=ZoneInfo("UTC"))
    date_str, observation_only, defaulted = recap_engine.resolve_recap_date(
        None,
        ["2026-06-24", "2026-06-25", "2026-06-26"],
        now=aware_utc,
    )

    assert date_str == "2026-06-26"
    assert observation_only is True
    assert defaulted is True
