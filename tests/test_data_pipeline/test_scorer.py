import sys

sys.path.insert(0, "src")

from scorer import compute_relay_score


def test_compute_relay_score_one_word_board():
    row = {
        "first_seal_time": "092500",
        "blown_count": 0,
        "float_mcap": 3_000_000_000,
        "seal_funds": 500_000_000,
        "turnover": 3.0,
    }
    score = compute_relay_score(row, sector_limit_ups=5)
    assert 120 <= score <= 150, f"一字板 score={score} out of range"


def test_compute_relay_score_late_blown():
    row = {
        "first_seal_time": "145500",
        "blown_count": 3,
        "float_mcap": 50_000_000_000,
        "seal_funds": 100_000_000,
        "turnover": 25.0,
    }
    score = compute_relay_score(row, sector_limit_ups=1)
    assert score == 0, f"烂板 score={score} should be fully capped"


def test_compute_relay_score_caps():
    row_high = {
        "first_seal_time": "092500",
        "blown_count": 0,
        "float_mcap": 500_000_000,
        "seal_funds": 500_000_000,
        "turnover": 5.0,
    }
    row_low = {
        "first_seal_time": "150000",
        "blown_count": 10,
        "float_mcap": 500_000_000_000,
        "seal_funds": 0,
        "turnover": 50.0,
    }
    assert compute_relay_score(row_high, sector_limit_ups=10) <= 150
    assert compute_relay_score(row_low, sector_limit_ups=1) >= 0


def test_compute_relay_score_handles_missing_time_and_values():
    row = {
        "first_seal_time": None,
        "blown_count": "",
        "float_mcap": None,
        "seal_funds": None,
        "turnover": None,
    }
    score = compute_relay_score(row, sector_limit_ups=0)
    assert 0 <= score <= 150


def test_compute_relay_score_caps_noisy_low_consensus():
    row = {
        "first_seal_time": "145500",
        "blown_count": 2,
        "float_mcap": 400_000_000_000,
        "seal_funds": 1_000_000,
        "turnover": 22.0,
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

    assert compute_relay_score(canonical_row, 5) == 125
