import sys

sys.path.insert(0, "src")

from scorer import compute_relay_score


def test_compute_relay_score_one_word_board():
    row = {
        "首次封板时间": "092500",
        "炸板次数": 0,
        "所属行业": "计算机",
        "流通市值": 3_000_000_000,
        "封板资金": 500_000_000,
        "换手率": 3.0,
    }
    score = compute_relay_score(row, sector_limit_ups=5)
    assert 100 <= score <= 150, f"一字板 score={score} out of range"


def test_compute_relay_score_late_blown():
    row = {
        "首次封板时间": "145500",
        "炸板次数": 3,
        "所属行业": "纺织",
        "流通市值": 50_000_000_000,
        "封板资金": 100_000_000,
        "换手率": 25.0,
    }
    score = compute_relay_score(row, sector_limit_ups=1)
    assert 0 <= score <= 50, f"烂板 score={score} out of range"


def test_compute_relay_score_caps():
    row_high = {
        "首次封板时间": "092500",
        "炸板次数": 0,
        "所属行业": "计算机",
        "流通市值": 500_000_000,
        "封板资金": 500_000_000,
        "换手率": 5.0,
    }
    row_low = {
        "首次封板时间": "150000",
        "炸板次数": 10,
        "所属行业": "纺织",
        "流通市值": 500_000_000_000,
        "封板资金": 0,
        "换手率": 50.0,
    }
    assert compute_relay_score(row_high, sector_limit_ups=10) <= 150
    assert compute_relay_score(row_low, sector_limit_ups=1) >= 0


def test_compute_relay_score_handles_missing_time_and_values():
    row = {
        "首次封板时间": None,
        "炸板次数": "",
        "所属行业": "计算机",
        "流通市值": None,
        "封板资金": None,
        "换手率": None,
    }
    score = compute_relay_score(row, sector_limit_ups=0)
    assert 0 <= score <= 150


def test_compute_relay_score_caps_noisy_low_consensus():
    row = {
        "首次封板时间": "145500",
        "炸板次数": 2,
        "所属行业": "纺织",
        "流通市值": 400_000_000_000,
        "封板资金": 1_000_000,
        "换手率": 22.0,
    }
    score = compute_relay_score(row, sector_limit_ups=1)
    assert score <= 80


def test_compute_relay_score_accepts_canonical_normalized_fields():
    canonical_row = {
        "first_seal_time": "093500",
        "blown_count": 1,
        "sector": "计算机",
        "float_mcap": 5_000_000_000,
        "seal_funds": 250_000_000,
        "turnover": 8.0,
    }
    source_row = {
        "首次封板时间": "093500",
        "炸板次数": 1,
        "所属行业": "计算机",
        "流通市值": 5_000_000_000,
        "封板资金": 250_000_000,
        "换手率": 8.0,
    }

    assert compute_relay_score(canonical_row, 5) == compute_relay_score(source_row, 5)
