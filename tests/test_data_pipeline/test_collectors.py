import pandas as pd
import pytest

from data_pipeline.collector import AshareCollector, NewsCollector, ZTPoolCollector


@pytest.mark.asyncio
async def test_ashare_collector_due():
    c = AshareCollector(watchlist=["600519", "000001"])
    assert c.due()
    c._last_poll = __import__("datetime").datetime.now()
    assert not c.due()


@pytest.mark.asyncio
async def test_collector_empty_on_empty_watchlist():
    c = AshareCollector(watchlist=[])
    df = await c.poll()
    assert isinstance(df, pd.DataFrame)
    assert df.empty


@pytest.mark.asyncio
async def test_ashare_collector_normalizes_rows(monkeypatch):
    monkeypatch.setattr(
        "data_pipeline.collector.get_realtime_quotes",
        lambda codes: pd.DataFrame(
            {
                "代码": ["600519.SH"],
                "名称": ["茅台"],
                "最新价": ["1500.2"],
                "涨跌幅": ["1.23"],
                "换手率": ["3.4"],
                "流通市值": ["123456789"],
            }
        ),
    )
    c = AshareCollector(watchlist=["600519"])
    df = await c.poll()
    assert df["code"].tolist() == ["600519"]
    assert df["price"].iloc[0] == 1500.2
    assert df["source_tag"].iloc[0] == "ashare"
    assert "ts" in df.columns


@pytest.mark.asyncio
async def test_zt_pool_collector_normalizes_rows(monkeypatch):
    monkeypatch.setattr(
        "data_pipeline.collector.ak.stock_zt_pool_em",
        lambda date_str: pd.DataFrame(
            {
                "代码": ["600519.SH"],
                "名称": ["茅台"],
                "最新价": ["1500.2"],
                "涨跌幅": ["9.9"],
                "换手率": ["3.4"],
                "流通市值": ["123456789"],
                "封板资金": ["50000000"],
                "首次封板时间": ["9:25:00"],
                "炸板次数": ["0"],
                "连板数": ["1"],
                "所属行业": ["白酒"],
            }
        ),
    )
    c = ZTPoolCollector()
    df = await c.poll()
    assert df["code"].tolist() == ["600519"]
    assert df["first_seal_time"].iloc[0] == "092500"
    assert df["blown_count"].iloc[0] == 0
    assert df["source_tag"].iloc[0] == "zt_pool"


@pytest.mark.asyncio
async def test_news_collector_interface():
    c = NewsCollector()
    assert c.interval == 30.0
    assert hasattr(c, "poll")
