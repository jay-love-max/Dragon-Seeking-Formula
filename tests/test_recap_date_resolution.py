import sys
from datetime import datetime
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import recap_engine


def test_default_date_rolls_back_on_non_trading_day():
    date_str, observation_only, defaulted = recap_engine.resolve_recap_date(
        None,
        ["2026-06-24", "2026-06-25", "2026-06-26"],
        now=datetime(2026, 6, 27, 12, 0),
    )

    assert date_str == "2026-06-26"
    assert observation_only is False
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
