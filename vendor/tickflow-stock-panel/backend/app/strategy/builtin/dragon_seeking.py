"""寻龙诀 1进2策略 — 首板标的筛选，打分评估接力潜力"""
import polars as pl

META = {
    "id": "dragon_seeking",
    "name": "寻龙诀 1进2",
    "description": "筛选昨日首次封板的强势个股，评估次日1进2接力潜力",
    "tags": ["涨停", "接力", "首板"],
    "params": [
        {"id": "min_turnover", "label": "最低换手率%", "type": "float",
         "default": 2.0, "min": 0.0, "max": 10.0, "step": 0.5},
        {"id": "max_turnover", "label": "最高换手率%", "type": "float",
         "default": 20.0, "min": 10.0, "max": 40.0, "step": 1.0},
        {"id": "max_float_mcap", "label": "最高流通市值(亿)", "type": "float",
         "default": 150.0, "min": 30.0, "max": 500.0, "step": 10.0},
    ],
    "scoring": {"amount": 0.6, "turnover_rate": 0.4},
    "order_by": "score",
    "descending": True,
    "limit": 50,
}

ENTRY_SIGNALS = ["signal_limit_up"]
EXIT_SIGNALS = []
STOP_LOSS = -0.05
MAX_HOLD_DAYS = 3
ALERTS = []


def filter(df: pl.DataFrame, params: dict) -> pl.Expr:
    min_turnover = params.get("min_turnover", 2.0)
    max_turnover = params.get("max_turnover", 20.0)
    max_mcap = params.get("max_float_mcap", 150.0) * 1e8

    return (
        pl.col("signal_limit_up").fill_null(False)
        & (pl.col("consecutive_limit_ups") == 1)
        & (pl.col("turnover_rate") >= min_turnover)
        & (pl.col("turnover_rate") <= max_turnover)
        & (pl.col("float_market_cap") <= max_mcap)
    )
