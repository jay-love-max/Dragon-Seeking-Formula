import pandas as pd

import data_pipeline.engine as engine
from data_pipeline.merger import merge
from data_pipeline.normalizer import normalize


def test_score_snapshot_uses_complete_sector_counts_and_persists_them():
    snapshot = pd.DataFrame(
        [
            {
                "code": f"00000{i}",
                "sector": "计算机",
                "seal_funds": 100_000_000.0,
                "float_mcap": 2_000_000_000.0,
                "first_seal_time": "093000",
                "blown_count": 0,
                "turnover": 8.0,
            }
            for i in range(1, 6)
        ]
    )

    score_snapshot = getattr(engine, "score_snapshot", lambda _: pd.DataFrame())
    result = score_snapshot(snapshot)

    assert result["sector_limit_ups"].tolist() == [5, 5, 5, 5, 5]
    assert result["score_intraday"].notna().all()


def test_raw_provider_data_flows_through_normalize_merge_and_score():
    raw_zt_pool = pd.DataFrame(
        [
            {
                "代码": code,
                "名称": name,
                "最新价": price,
                "涨跌幅": 10.0,
                "换手率": 8.0,
                "流通市值": 2_000_000_000.0,
                "封板资金": 100_000_000.0,
                "首次封板时间": "09:30:00",
                "炸板次数": 0,
                "连板数": 1,
                "所属行业": "计算机",
            }
            for code, name, price in [
                ("000001", "测试一", 10.0),
                ("000002", "测试二", 20.0),
            ]
        ]
    )
    initial = engine.score_snapshot(merge("zt_pool", normalize("zt_pool", raw_zt_pool), {}))
    snapshot = initial.set_index("code").to_dict("index")

    raw_quote = pd.DataFrame(
        [{"代码": "000001", "最新价": 10.5, "涨跌幅": 10.2, "换手率": 8.5, "流通市值": 2_100_000_000.0}]
    )
    refreshed = engine.score_snapshot(
        merge("ashare", normalize("ashare", raw_quote), snapshot)
    ).set_index("code")

    assert set(refreshed.index) == {"000001", "000002"}
    assert refreshed.loc["000001", "price"] == 10.5
    assert refreshed["sector_limit_ups"].tolist() == [2, 2]
    assert refreshed["score_intraday"].notna().all()


def test_is_trading_day_uses_xshg_calendar_not_weekday():
    # 2026-06-19 是周五但属于 A 股休市(端午节);旧 weekday() 回退会误判为交易日。
    from datetime import datetime

    assert engine.is_trading_day(datetime(2026, 6, 19)) is False
    assert engine.is_trading_day(datetime(2026, 6, 24)) is True
