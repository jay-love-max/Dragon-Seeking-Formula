import pandas as pd

from data_pipeline.normalizer import normalize


def test_normalize_code_cleanup():
    df = pd.DataFrame({"code": ["600519.SH", "000001", "300750.SZ"]})
    result = normalize("ashare", df)
    assert result["code"].tolist() == ["600519", "000001", "300750"]


def test_normalize_rename():
    df = pd.DataFrame({"代码": ["600519"], "最新价": [150.0], "换手率": [5.0]})
    result = normalize("zt_pool", df)
    assert "code" in result.columns
    assert result["code"].iloc[0] == "600519"
    assert result["price"].iloc[0] == 150.0


def test_normalize_drops_nan():
    df = pd.DataFrame({"code": ["600519", None, "000001"]})
    result = normalize("ashare", df)
    assert len(result) == 2


def test_normalize_timestamp():
    df = pd.DataFrame({"code": ["600519"]})
    result = normalize("ashare", df)
    assert "ts" in result.columns


def test_normalize_source_tag_and_numeric_cleanup():
    df = pd.DataFrame(
        {
            "code": ["600519.SH"],
            "最新价": ["1500.2"],
            "涨跌幅": ["1.23"],
            "换手率": ["3.4"],
            "流通市值": ["123456789"],
            "首次封板时间": ["9:25:00"],
            "source_tag": [None],
        }
    )
    result = normalize("ashare", df)
    row = result.iloc[0]
    assert row["code"] == "600519"
    assert row["price"] == 1500.2
    assert row["change_pct"] == 1.23
    assert row["turnover"] == 3.4
    assert row["float_mcap"] == 123456789
    assert row["first_seal_time"] == "092500"
    assert row["source_tag"] == "ashare"
    assert row["quality_state"] == "complete"
    assert row["missing_fields"] == ""
    assert "ts" in result.columns


def test_normalize_drops_missing_code_rows():
    df = pd.DataFrame({"code": ["", None, "600519"]})
    result = normalize("ashare", df)
    assert result["code"].tolist() == ["600519"]


def test_normalize_marks_degraded_zt_pool_rows():
    df = pd.DataFrame({"代码": ["600519"], "最新价": [150.0], "换手率": [5.0]})
    result = normalize("zt_pool", df)
    assert result["quality_state"].iloc[0] == "degraded"
    assert "seal_funds" in result["missing_fields"].iloc[0]
