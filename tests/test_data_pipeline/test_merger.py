import pandas as pd

from data_pipeline.merger import merge


def test_merge_preserves_existing_values_when_new_row_is_sparser():
    snapshot = {
        "600519": {
            "code": "600519",
            "name": "茅台",
            "price": 1500.0,
            "change_pct": 1.0,
            "turnover": 1.5,
            "seal_funds": 50000000.0,
            "first_seal_time": "092500",
            "blown_count": 0,
            "sector": "白酒",
            "float_mcap": 250000000000.0,
            "score_intraday": 88,
            "score_intraday_prev": 0,
            "quality_state": "complete",
            "missing_fields": "",
            "ts": "2026-06-27T09:30:00",
            "source_tag": "ashare",
        }
    }
    new_df = pd.DataFrame(
        [
            {
                "code": "600519.SH",
                "name": "茅台",
                "price": None,
                "change_pct": None,
                "turnover": None,
                "seal_funds": 60000000.0,
                "first_seal_time": "09:31:00",
                "blown_count": 1,
                "sector": "白酒",
                "float_mcap": 250000000000.0,
                "ts": "2026-06-27T09:31:00",
                "source_tag": "ashare",
                "quality_state": "degraded",
                "missing_fields": "price,change_pct,turnover",
            }
        ]
    )

    result = merge("ashare", new_df, snapshot)
    row = result.iloc[0]
    assert row["code"] == "600519"
    assert row["price"] == 1500.0
    assert row["change_pct"] == 1.0
    assert row["seal_funds"] == 60000000.0
    assert row["first_seal_time"] == "09:31:00"
    assert row["source_tag"] == "ashare"
    assert row["quality_state"] == "degraded"
    assert row["missing_fields"] == "price,change_pct,turnover"


def test_merge_allows_realtime_quotes_to_refresh_zt_pool_record():
    snapshot = {
        "000001": {
            "code": "000001",
            "name": "平安银行",
            "price": 10.0,
            "change_pct": 9.8,
            "turnover": 4.0,
            "float_mcap": 100_000_000_000.0,
            "seal_funds": 500_000_000.0,
            "first_seal_time": "093000",
            "blown_count": 0,
            "sector": "银行",
            "source_tag": "zt_pool",
        }
    }
    realtime = pd.DataFrame(
        [{
            "code": "000001",
            "name": "平安银行",
            "price": 10.5,
            "change_pct": 10.1,
            "turnover": 5.2,
            "float_mcap": 101_000_000_000.0,
            "source_tag": "ashare",
            "ts": "2026-06-27T10:00:00",
        }]
    )

    row = merge("ashare", realtime, snapshot).set_index("code").loc["000001"]

    assert row["price"] == 10.5
    assert row["change_pct"] == 10.1
    assert row["turnover"] == 5.2
    assert row["float_mcap"] == 101_000_000_000.0
    assert row["seal_funds"] == 500_000_000.0
    assert row["first_seal_time"] == "093000"
    assert row["source_tag"] == "zt_pool"


def test_merge_returns_complete_snapshot_including_untouched_rows():
    snapshot = {
        "000001": {"code": "000001", "name": "平安银行", "sector": "银行"},
        "600000": {"code": "600000", "name": "浦发银行", "sector": "银行"},
    }
    update = pd.DataFrame([{"code": "000001", "price": 10.5, "source_tag": "ashare"}])

    result = merge("ashare", update, snapshot)

    assert set(result["code"]) == {"000001", "600000"}


def test_merge_keeps_realtime_quote_when_zt_pool_refreshes_later():
    snapshot = {
        "000001": {
            "code": "000001",
            "price": 10.5,
            "seal_funds": 500_000_000.0,
            "source_tag": "zt_pool",
            "quote_source_tag": "ashare",
            "limit_up_source_tag": "zt_pool",
        }
    }
    zt_refresh = pd.DataFrame(
        [{
            "code": "000001",
            "price": 10.2,
            "seal_funds": 600_000_000.0,
            "source_tag": "zt_pool",
        }]
    )

    row = merge("zt_pool", zt_refresh, snapshot).set_index("code").loc["000001"]

    assert row["price"] == 10.5
    assert row["seal_funds"] == 600_000_000.0
