# 盘中实时数据管道 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) for syntax tracking.

**Goal:** Add an independent asyncio `src/data_pipeline/` service that collects, merges, and persists intraday A-stock data (prices, limit-up pool, news), computes a lightweight intraday relay score, and exposes the result to the vendor panel via the shared `recap.db`.

**Architecture:** The pipeline runs alongside the existing `recap_engine.py` as a separate PM2-managed process. APScheduler manages the lifecycle (09:15–15:00 trading days). Three collectors pull from Ashare/akshare/news sources, merge into per-stock wide records via a merger layer, compute intraday scores, and write to `realtime_snapshot` table. The vendor panel reads this table via a new read-only API endpoint.

**Tech Stack:** Python 3.11+, asyncio, aiohttp, APScheduler, pandas, akshare, SQLite (WAL mode)

---

### File Structure

```
# New files
src/data_pipeline/__init__.py       # Package marker + logging setup
src/data_pipeline/__main__.py       # CLI entry: python -m src.data_pipeline
src/data_pipeline/ashare.py         # Inlined mpquant/Ashare (MIT, single file)
src/data_pipeline/collector.py      # Base Collector + AshareCollector + ZTPoolCollector + NewsCollector
src/data_pipeline/normalizer.py     # Field name & code format normalization
src/data_pipeline/merger.py         # Multi-source per-stock merge
src/data_pipeline/store.py          # SQLite WAL + realtime_snapshot upsert
src/data_pipeline/engine.py         # APScheduler lifecycle + polling loop
src/data_pipeline/push.py           # Webhook alert sender
src/data_pipeline/rules.py          # Alert rule definitions
src/scorer.py                       # Extracted compute_relay_score + generate_playbook from recap_engine
tests/test_data_pipeline/__init__.py
tests/test_data_pipeline/test_scorer.py
tests/test_data_pipeline/test_collectors.py
tests/test_data_pipeline/test_normalizer.py
tests/test_data_pipeline/test_store.py
tests/test_data_pipeline/test_rules.py
tests/test_data_pipeline/test_engine.py

# Modified files
pyproject.toml                      # Add aiohttp, apscheduler deps
ecosystem.config.cjs                # Add data-pipeline PM2 entry
src/recap_engine.py                 # Use extracted scorer, read realtime_snapshot
vendor/tickflow-stock-panel/backend/app/api/recap.py  # Add /api/recap/intraday-snapshot
```

---

### Task 1: Dependencies and Infrastructure

**Files:**
- Modify: `pyproject.toml`
- Modify: `ecosystem.config.cjs`
- Create: `src/data_pipeline/__init__.py`

- [ ] **Step 1: Add dependencies to pyproject.toml**

```toml
# pyproject.toml — add to dependencies list
dependencies = [
    "mootdx",
    "akshare",
    "pandas",
    "numpy",
    "scikit-learn",
    "requests",
    "aiohttp",            # Async HTTP + SSE
    "apscheduler>=3.10",  # Cron scheduling (matches vendor panel version)
]
```

- [ ] **Step 2: Add PM2 entry for data-pipeline**

```javascript
// ecosystem.config.cjs — add to apps array
{
  name: 'data-pipeline',
  cwd: '/Users/angojay/20_Projects/dragon-seeking-formula',
  script: './.venv/bin/python',
  args: '-m src.data_pipeline',
  interpreter: 'none',
  autorestart: true,
  max_restarts: 5,
  min_uptime: 10000,
  watch: false,
  env: {
    PATH: process.env.PATH
  }
}
```

- [ ] **Step 3: Create package init**

```python
# src/data_pipeline/__init__.py
import logging

logging.getLogger("data_pipeline").setLevel(logging.INFO)
logger = logging.getLogger("data_pipeline")
```

- [ ] **Step 4: Install new deps and verify**

```bash
pip install -e ".[dev]"
# Verify imports
python -c "import aiohttp; import apscheduler; print('OK')"
```

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml ecosystem.config.cjs src/data_pipeline/__init__.py
git commit -m "chore: add data-pipeline deps and PM2 config"
```

---

### Task 2: Extract scorer from recap_engine

**Files:**
- Create: `src/scorer.py`
- Modify: `src/recap_engine.py:1118-1210, 1214-1222, 266-303`
- Test: `tests/test_data_pipeline/test_scorer.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_data_pipeline/test_scorer.py
import pytest
import sys
sys.path.insert(0, "src")
from scorer import compute_relay_score

def test_compute_relay_score_one_word_board():
    """一字板 at 09:25:00 should get high base score"""
    row = {
        "首次封板时间": "092500",
        "炸板次数": 0,
        "所属行业": "计算机",
        "流通市值": 3_000_000_000,  # 30亿
        "封板资金": 500_000_000,    # 5亿
        "换手率": 3.0,
    }
    score = compute_relay_score(row, sector_limit_ups=5)
    assert 100 <= score <= 150, f"一字板 score={score} out of range"

def test_compute_relay_score_late_blown():
    """尾盘烂板 should get low score"""
    row = {
        "首次封板时间": "145500",
        "炸板次数": 3,
        "所属行业": "纺织",
        "流通市值": 50_000_000_000,  # 500亿
        "封板资金": 100_000_000,      # 1亿
        "换手率": 25.0,
    }
    score = compute_relay_score(row, sector_limit_ups=1)
    assert 0 <= score <= 50, f"烂板 score={score} out of range"

def test_compute_relay_score_caps():
    """Score should be bounded 0-150"""
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
```

- [ ] **Step 2: Run to verify failure**

```bash
python -m pytest tests/test_data_pipeline/test_scorer.py -v
# Expected: ImportError / ModuleNotFoundError for scorer
```

- [ ] **Step 3: Create scorer.py**

```python
# src/scorer.py
"""Shared relay score computation — used by both recap_engine (end-of-day) and data_pipeline (intraday)."""

def compute_relay_score(row: dict, sector_limit_ups: int) -> int:
    """
    Compute the 1进2 relay score (0-150) for a limit-up candidate.

    row dict must contain keys matching akshare zt_pool column names (Chinese):
        "首次封板时间", "炸板次数", "所属行业", "流通市值", "封板资金", "换手率"
    sector_limit_ups: number of limit-up stocks in the same sector today.
    """
    score = 50  # Base

    # A. First seal time
    time_str = str(row["首次封板时间"]).zfill(6)
    is_one_word = (time_str == "092500")

    if is_one_word:
        score += 25
    elif time_str <= "093500":
        score += 20
    elif time_str <= "094500":
        score += 15
    elif time_str <= "103000":
        score += 10
    elif time_str <= "113000":
        score += 5
    elif time_str >= "143000":
        score -= 15
    elif time_str >= "130000":
        score -= 5

    # B. Blown boards
    blown = int(row["炸板次数"])
    if blown == 0:
        score += 15
    elif blown == 1:
        score += 5
    elif blown == 2:
        score -= 5
    else:
        score -= 15

    # C. Seal strength ratio
    float_mcap = float(row["流通市值"])
    seal_funds = float(row["封板资金"])
    seal_ratio = (seal_funds / float_mcap) * 100 if float_mcap > 0 else 0.0

    if seal_ratio >= 8.0:
        score += 20
    elif seal_ratio >= 4.0:
        score += 15
    elif seal_ratio >= 2.0:
        score += 10
    elif seal_ratio >= 1.0:
        score += 5
    elif seal_ratio < 0.5:
        score -= 10

    # D. Market cap (流通市值 is in 元, convert to 亿)
    mcap_yi = float_mcap / 1e8
    if mcap_yi <= 30.0:
        score += 15
    elif mcap_yi <= 80.0:
        score += 10
    elif mcap_yi <= 150.0:
        score += 5
    elif mcap_yi > 300.0:
        score -= 20
    else:
        score -= 10

    # E. Turnover
    turnover = float(row["换手率"])
    if 4.0 <= turnover <= 12.0:
        score += 10
    elif 12.0 <= turnover <= 20.0:
        score += 5
    elif turnover < 2.0 and not is_one_word:
        score -= 10
    elif turnover > 20.0:
        score -= 15

    # F. Sector effect
    if sector_limit_ups >= 6:
        score += 20
    elif sector_limit_ups >= 4:
        score += 15
    elif sector_limit_ups == 3:
        score += 10
    elif sector_limit_ups == 2:
        score += 5

    return max(0, min(150, score))


def generate_playbook(sector: str, time_str: str, blown: int, turnover: float,
                      score: int, sector_limit_ups: int) -> str:
    """Generate momentum trading playbook based on stock metrics (no row dict needed)."""
    time_str = str(time_str).zfill(6)
    is_one_word = (time_str == "092500")
    time_formatted = f"{time_str[:2]}:{time_str[2:4]}:{time_str[4:]}"

    if is_one_word:
        return (
            "【一字极速板】今日全天一字锁死，筹码高度锁定。明日接力策略：不要在竞价或开盘直接挂单排队以防'炸板闷杀'。"
            "可关注明日开盘后的'分歧洗盘再封板'机会。若明日竞价放量且高开在5%-8%之间，可等换手承接充分、下探均线重新走强时介入。"
        )
    if score >= 115:
        return (
            f"【核心领涨黄金标的】今日于 {time_formatted} 极速封板，炸板 {blown} 次，属于多头资金绝对主导的超强首板。所属【{sector}】"
            f"板块今日大面积爆发（共 {sector_limit_ups} 只涨停），板块效应极佳。明日接力策略：明日大概率高开（>4%）。若早盘竞价成交量"
            f"达到今日首板成交额的10%以上，且开盘5分钟内快速放量拉升，可果断半路跟进；或在换手率达到5%左右、股价再度封死二板瞬间打板买入。"
        )
    if score >= 95:
        return (
            f"【强势突围潜力股】首次封板时间 {time_formatted} 处于早盘黄金期，炸板仅 {blown} 次，换手率 {turnover}% 适中，筹码换手健康。"
            f"明日接力策略：明日竞价若小幅高开（2%-4%）且放量，说明有资金继续做接力。建议开盘后等冲高回调至均线守住、再度向上翻红放量时介入；"
            f"或者等日内充分换手（>10%）后，尾盘重新冲击极限封板时确认打板。"
        )
    if blown >= 2 or time_str >= "140000":
        return (
            f"【分歧烂板/尾盘偷袭】今日封板极晚（{time_formatted}）且炸板 {blown} 次，资金分歧剧烈，换手率偏高，筹码结构不稳。"
            f"明日接力策略：该股属于弱势板，明日接力必须遵循'弱转强'原则。弱转强标志：明日竞价超预期高开在2%以上，且开盘快速放量拉升。"
            f"如果明日平开或低开，说明今天套牢盘压力沉重，资金弃疗，应坚决放弃关注，避免接盘。"
        )
    return (
        f"【常规轮动跟风标的】首次封板时间 {time_formatted}，换手率 {turnover}% 正常。所属行业【{sector}】今天有 {sector_limit_ups} 只涨停，"
        f"地位属于跟风或侧翼。明日接力策略：除非明日所属板块龙头开盘封死一字板，带动资金溢出做跟风接力，否则该股性价比一般。"
        f"建议明日不急于建仓，仅作为同板块情绪风向标观察，避免冲高回落被套。"
    )
```

- [ ] **Step 4: Run tests to verify**

```bash
python -m pytest tests/test_data_pipeline/test_scorer.py -v
# Expected: 3 passed
```

- [ ] **Step 5: Refactor recap_engine.py to use src/scorer.py**

Replace lines 1118-1210 in `src/recap_engine.py`:

```python
# BEFORE (around line 1118):
    # Calculate 1进2 Relay Score for each 1-board stock
    scores = []
    playbooks = []

    for idx, row in df_1b.iterrows():
        score = 50  # Base Score
        # A. First seal time ... (75 lines of scoring logic)
        # ... through line 1210

# AFTER (replace all of the above with):
    from scorer import compute_relay_score, generate_playbook

    df_1b["接力指数"] = df_1b.apply(
        lambda r: compute_relay_score(r.to_dict(), sector_counts.get(r["所属行业"], 1)),
        axis=1
    ).astype(int)

    df_1b["操作建议"] = df_1b.apply(
        lambda r: generate_playbook(
            sector=r["所属行业"],
            time_str=r["首次封板时间"],
            blown=int(r["炸板次数"]),
            turnover=float(r["换手率"]),
            score=int(r["接力指数"]),
            sector_limit_ups=sector_counts.get(r["所属行业"], 1),
        ),
        axis=1
    )
```

Also remove the import/unused symbol for `generate_playbook` at its original location (lines 266-303). Delete the `generate_playbook` function body and replace with:
```python
def generate_playbook(row, sector_count, is_one_word):
    from scorer import generate_playbook as _gp
    return _gp(
        sector=row["所属行业"],
        time_str=row["首次封板时间"],
        blown=int(row["炸板次数"]),
        turnover=float(row["换手率"]),
        score=int(row["接力指数"]),
        sector_limit_ups=sector_count,
    )
```

- [ ] **Step 6: Run existing recap tests to verify no regression**

```bash
python -m pytest tests/ -v
# Expected: all existing tests pass
```

- [ ] **Step 7: Commit**

```bash
git add src/scorer.py tests/test_data_pipeline/test_scorer.py src/recap_engine.py
git commit -m "refactor: extract relay scorer into shared src/scorer.py"
```

---

### Task 3: Inline Ashare module

**Files:**
- Create: `src/data_pipeline/ashare.py`

- [ ] **Step 1: Download and inline mpquant/Ashare**

Download from https://raw.githubusercontent.com/mpquant/Ashare/main/Ashare.py and save to `src/data_pipeline/ashare.py`. This is a single-file MIT-licensed module (~200 lines) that wraps Sina/Tencent real-time stock APIs.

Verify the file loads:
```python
# Quick smoke test
from src.data_pipeline.ashare import get_realtime_quotes
# Should not throw
```

- [ ] **Step 2: Verify it works for a known stock**

```bash
python -c "
import sys; sys.path.insert(0, 'src')
from data_pipeline.ashare import get_realtime_quotes
df = get_realtime_quotes(['600519'])
print(df.columns.tolist())
print(df.to_dict('records'))
"
# Expected: DataFrame with columns like ['代码', '名称', '最新价', '涨跌幅', ...]
# If network fails, skip — this is a live API test.
```

- [ ] **Step 3: Commit**

```bash
git add src/data_pipeline/ashare.py
git commit -m "feat: inline Ashare real-time quotes module"
```

---

### Task 4: Collector layer

**Files:**
- Create: `src/data_pipeline/collector.py`
- Test: `tests/test_data_pipeline/test_collectors.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_data_pipeline/test_collectors.py
import pytest
import sys; sys.path.insert(0, "src")
from datetime import datetime, timedelta
from data_pipeline.collector import AshareCollector, ZTPoolCollector, NewsCollector

@pytest.mark.asyncio
async def test_ashare_collector_poll():
    """AshareCollector poll should return DataFrame with required columns"""
    import pandas as pd
    c = AshareCollector(watchlist=["600519", "000001"])
    df = await c.poll()
    assert isinstance(df, pd.DataFrame)
    assert not df.empty
    assert "code" in df.columns
    assert "price" in df.columns
    assert "turnover" in df.columns

@pytest.mark.asyncio
async def test_zt_pool_collector_poll():
    """ZTPoolCollector poll should return DataFrame"""
    import pandas as pd
    c = ZTPoolCollector()
    df = await c.poll()
    assert isinstance(df, pd.DataFrame)
    if not df.empty:
        assert "code" in df.columns
        assert "seal_funds" in df.columns
        assert "blown_count" in df.columns
        assert "first_seal_time" in df.columns

@pytest.mark.asyncio
async def test_collector_empty_on_network_error(mocker):
    """Collector should return empty DataFrame on network failure, not crash"""
    import pandas as pd
    c = AshareCollector(watchlist=[])
    # Mock the underlying ashare function to raise
    mocker.patch("data_pipeline.collector.get_realtime_quotes", side_effect=ConnectionError)
    df = await c.poll()
    assert isinstance(df, pd.DataFrame)
    assert df.empty

@pytest.mark.asyncio
async def test_collector_due():
    """Collector.due() should respect interval"""
    c = AshareCollector(watchlist=[], interval=1.0)
    assert c.due()  # First call always due
    c._last_poll = datetime.now()
    assert not c.due()  # Immediately after, not due
```

- [ ] **Step 2: Run to verify failure**

```bash
python -m pytest tests/test_data_pipeline/test_collectors.py -v
# Expected: ImportError / ModuleNotFoundError
```

- [ ] **Step 3: Create collector.py**

```python
# src/data_pipeline/collector.py
import asyncio
import logging
from abc import ABC, abstractmethod
from datetime import datetime, date
from typing import Optional
import akshare as ak
import pandas as pd

from .ashare import get_realtime_quotes
from ..recap_engine import DATE_STR

logger = logging.getLogger("data_pipeline.collector")


class Collector(ABC):
    """Base class for all data source collectors."""

    def __init__(self, interval: float = 5.0, retry_delay: float = 5.0):
        self.interval = interval
        self.retry_delay = retry_delay
        self._last_poll: Optional[datetime] = None

    def due(self) -> bool:
        now = datetime.now()
        if self._last_poll is None:
            self._last_poll = now
            return True
        elapsed = (now - self._last_poll).total_seconds()
        return elapsed >= self.interval

    @abstractmethod
    async def poll(self) -> pd.DataFrame:
        ...


class AshareCollector(Collector):
    """Real-time quotes via Ashare (Sina/Tencent)."""

    def __init__(self, watchlist: Optional[list[str]] = None, interval: float = 3.0):
        super().__init__(interval=interval)
        self._watchlist = watchlist or []

    def update_watchlist(self, codes: list[str]):
        self._watchlist = list(set(codes))

    async def poll(self) -> pd.DataFrame:
        if not self._watchlist:
            return pd.DataFrame()
        try:
            loop = asyncio.get_event_loop()
            df = await loop.run_in_executor(None, get_realtime_quotes, self._watchlist)
            if df is None or df.empty:
                return pd.DataFrame()
            df = df.rename(columns={
                "代码": "code",
                "名称": "name",
                "最新价": "price",
                "涨跌幅": "change_pct",
                "换手率": "turnover",
            })
            df["code"] = df["code"].astype(str).str.zfill(6)
            self._last_poll = datetime.now()
            return df[["code", "name", "price", "change_pct", "turnover"]]
        except Exception as e:
            logger.warning("AshareCollector poll failed: %s", e)
            return pd.DataFrame()


class ZTPoolCollector(Collector):
    """Limit-up pool via akshare."""

    def __init__(self, interval: float = 5.0):
        super().__init__(interval=interval)

    async def poll(self) -> pd.DataFrame:
        try:
            date_str = date.today().strftime("%Y%m%d")
            loop = asyncio.get_event_loop()
            df = await loop.run_in_executor(None, ak.stock_zt_pool_em, date_str)
            if df is None or df.empty:
                return pd.DataFrame()
            df = df.rename(columns={
                "代码": "code",
                "名称": "name",
                "最新价": "price",
                "涨跌幅": "change_pct",
                "换手率": "turnover",
                "流通市值": "float_mcap",
                "封板资金": "seal_funds",
                "首次封板时间": "first_seal_time",
                "炸板次数": "blown_count",
                "连板数": "consecutive_boards",
                "所属行业": "sector",
            })
            df["code"] = df["code"].astype(str).str.zfill(6)
            df["blown_count"] = df["blown_count"].fillna(0).astype(int)
            df["first_seal_time"] = df["first_seal_time"].astype(str).str.zfill(6)
            self._last_poll = datetime.now()
            return df[["code", "name", "price", "change_pct", "turnover", "float_mcap",
                       "seal_funds", "first_seal_time", "blown_count", "consecutive_boards", "sector"]]
        except Exception as e:
            logger.warning("ZTPoolCollector poll failed: %s", e)
            return pd.DataFrame()


class NewsCollector(Collector):
    """Financial news via akshare."""

    def __init__(self, interval: float = 30.0):
        super().__init__(interval=interval)

    async def poll(self) -> pd.DataFrame:
        try:
            loop = asyncio.get_event_loop()
            df = await loop.run_in_executor(None, ak.stock_news_em)
            if df is None or df.empty:
                return pd.DataFrame()
            df = df.rename(columns={
                "code": "code",
                "title": "title",
                "content": "content",
                "datetime": "ts",
            })
            df["code"] = df["code"].astype(str).str.zfill(6)
            self._last_poll = datetime.now()
            return df[["code", "title", "content", "ts"]]
        except Exception as e:
            logger.warning("NewsCollector poll failed: %s", e)
            return pd.DataFrame()
```

- [ ] **Step 4: Run tests — some will pass (unit tests), some will be skipped or fail (live API)**

```bash
python -m pytest tests/test_data_pipeline/test_collectors.py -v -x
```

- [ ] **Step 5: Commit**

```bash
git add src/data_pipeline/collector.py tests/test_data_pipeline/test_collectors.py
git commit -m "feat: add data pipeline collector layer"
```

---

### Task 5: Normalizer

**Files:**
- Create: `src/data_pipeline/normalizer.py`
- Test: `tests/test_data_pipeline/test_normalizer.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_data_pipeline/test_normalizer.py
import pytest
import sys; sys.path.insert(0, "src")
import pandas as pd
from data_pipeline.normalizer import normalize

def test_normalize_code_cleanup():
    """Codes should be 6-digit strings, no suffixes"""
    df = pd.DataFrame({"code": ["600519.SH", "000001", "300750.SZ"]})
    result = normalize("ashare", df)
    assert result["code"].tolist() == ["600519", "000001", "300750"]

def test_normalize_rename():
    """Chinese column names should map to normalized ones"""
    df = pd.DataFrame({"代码": ["600519"], "最新价": [150.0], "换手率": [5.0]})
    result = normalize("zt_pool", df)
    assert "code" in result.columns
    assert result["code"].iloc[0] == "600519"
    assert result["price"].iloc[0] == 150.0

def test_normalize_drops_nan():
    """Rows with NaN code should be dropped"""
    df = pd.DataFrame({"code": ["600519", None, "000001"]})
    result = normalize("ashare", df)
    assert len(result) == 2

def test_normalize_timestamp():
    """Timestamp column should be added if not present"""
    df = pd.DataFrame({"code": ["600519"]})
    result = normalize("ashare", df)
    assert "ts" in result.columns
```

- [ ] **Step 2: Create normalizer.py**

```python
# src/data_pipeline/normalizer.py
import pandas as pd
from datetime import datetime

FIELD_MAP = {
    "代码": "code", "code": "code", "symbol": "code",
    "名称": "name", "name": "name",
    "最新价": "price", "price": "price", "current": "price",
    "涨跌幅": "change_pct", "change_pct": "change_pct", "pct_chg": "change_pct",
    "换手率": "turnover", "turnover": "turnover", "turnover_ratio": "turnover",
    "流通市值": "float_mcap",
    "封板资金": "seal_funds", "seal_funds": "seal_funds", "funds": "seal_funds",
    "炸板次数": "blown_count", "blown_count": "blown_count",
    "首次封板时间": "first_seal_time",
    "所属行业": "sector", "sector": "sector",
    "标题": "title", "title": "title",
    "内容": "content", "content": "content",
    "时间": "ts", "datetime": "ts",
}


def normalize(source: str, df: pd.DataFrame) -> pd.DataFrame:
    """Normalize field names, code format, and timestamps."""
    if df.empty:
        return df

    df = df.copy()

    # Rename columns
    df = df.rename(columns=FIELD_MAP)
    keep_cols = [c for c in df.columns if c in FIELD_MAP.values() or c == "ts"]
    df = df[keep_cols]

    # Normalize codes to 6-digit strings
    if "code" in df.columns:
        df["code"] = df["code"].astype(str).str.replace(r"\.(SH|SZ|BJ)$", "", regex=True)
        df["code"] = df["code"].str.zfill(6)
        df = df.dropna(subset=["code"])

    # Add timestamp
    if "ts" not in df.columns:
        df["ts"] = datetime.now().isoformat(timespec="seconds")

    return df.reset_index(drop=True)
```

- [ ] **Step 3: Run tests**

```bash
python -m pytest tests/test_data_pipeline/test_normalizer.py -v
# Expected: 4 passed
```

- [ ] **Step 4: Commit**

```bash
git add src/data_pipeline/normalizer.py tests/test_data_pipeline/test_normalizer.py
git commit -m "feat: add data pipeline normalizer"
```

---

### Task 6: Merger

**Files:**
- Create: `src/data_pipeline/merger.py`
- (Tests in store.py since merger is tightly coupled to snapshot format)

- [ ] **Step 1: Create merger.py**

```python
# src/data_pipeline/merger.py
import pandas as pd
from typing import Dict

SOURCE_PRIORITY = ["zt_pool", "ashare", "news"]

# Snapshot schema columns. Order matters for DataFrame column alignment.
SNAPSHOT_COLUMNS = [
    "code", "name", "price", "change_pct", "turnover",
    "seal_funds", "first_seal_time", "blown_count", "sector",
    "float_mcap", "score_intraday",
    "source_ts", "source_tag",
]


def merge(source: str, new_df: pd.DataFrame, snapshot: dict) -> pd.DataFrame:
    """
    Merge new collector data with existing in-memory snapshot.

    snapshot: dict of {code: dict} — the current in-memory state.
    Returns: DataFrame ready for DB upsert.
    """
    rows = []
    for _, row in new_df.iterrows():
        code = str(row.get("code", "")).zfill(6)
        if not code:
            continue

        base = dict(snapshot.get(code, {}))
        new_source = source

        # Determine if this source can overwrite conflicting fields
        for col, val in row.items():
            if col in ("code",):
                continue
            if col in base and col != "ts":
                old_src = base.get("source_tag", "")
                old_rank = SOURCE_PRIORITY.index(old_src) if old_src in SOURCE_PRIORITY else 999
                new_rank = SOURCE_PRIORITY.index(new_source) if new_source in SOURCE_PRIORITY else 999
                if new_rank > old_rank:
                    continue  # Lower priority source doesn't overwrite
            base[col] = val

        base["code"] = code
        base["source_tag"] = new_source
        base["source_ts"] = row.get("ts", base.get("source_ts", ""))
        rows.append(base)

    if not rows:
        return pd.DataFrame(columns=SNAPSHOT_COLUMNS)

    result = pd.DataFrame(rows)
    # Ensure all snapshot columns exist
    for col in SNAPSHOT_COLUMNS:
        if col not in result.columns:
            result[col] = None
    return result[SNAPSHOT_COLUMNS].fillna(value={c: None for c in SNAPSHOT_COLUMNS})
```

- [ ] **Step 2: Quick smoke test**

```bash
python -c "
import sys; sys.path.insert(0, 'src')
import pandas as pd
from data_pipeline.merger import merge

snap = {'600519': {'code': '600519', 'name': '茅台', 'float_mcap': 2e10, 'source_tag': 'zt_pool'}}
new = pd.DataFrame({'code': ['600519'], 'price': [1500.0], 'turnover': [1.5], 'ts': ['2026-06-26T10:00:00']})
result = merge('ashare', new, snap)
print(result.to_dict('records'))
# Must retain float_mcap from snapshot (2e10) plus price from new data
"
```

- [ ] **Step 3: Commit**

```bash
git add src/data_pipeline/merger.py
git commit -m "feat: add data pipeline merger layer"
```

---

### Task 7: Store (SQLite persistence)

**Files:**
- Create: `src/data_pipeline/store.py`
- Test: `tests/test_data_pipeline/test_store.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_data_pipeline/test_store.py
import pytest
import sys; sys.path.insert(0, "src")
import pandas as pd
import tempfile, os
from data_pipeline.store import Store

@pytest.fixture
def store():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    s = Store(db_path)
    yield s
    s.close()
    os.unlink(db_path)

def test_store_creates_table(store):
    """Store.__init__ should create realtime_snapshot table"""
    cursor = store.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in cursor.fetchall()]
    assert "realtime_snapshot" in tables

def test_store_upsert(store):
    """write_snapshot should upsert by code"""
    df = pd.DataFrame({
        "code": ["600519"],
        "name": ["茅台"],
        "price": [1500.0],
        "turnover": [1.5],
    })
    store.write_snapshot(df)

    result = store.get_snapshot()
    assert "600519" in result
    assert result["600519"]["name"] == "茅台"
    assert result["600519"]["price"] == 1500.0

    # Upsert with new price
    df2 = pd.DataFrame({
        "code": ["600519"],
        "name": ["茅台"],
        "price": [1510.0],
        "turnover": [1.5],
    })
    store.write_snapshot(df2)
    result = store.get_snapshot()
    assert result["600519"]["price"] == 1510.0

def test_store_wal_mode(store):
    """Store should enable WAL mode"""
    cursor = store.conn.execute("PRAGMA journal_mode")
    assert cursor.fetchone()[0].lower() == "wal"

def test_store_cleanup(store):
    """cleanup should clear all rows"""
    df = pd.DataFrame({"code": ["600519"], "name": ["茅台"]})
    store.write_snapshot(df)
    store.cleanup()
    result = store.get_snapshot()
    assert len(result) == 0
```

- [ ] **Step 2: Create store.py**

```python
# src/data_pipeline/store.py
import logging
import sqlite3
import pandas as pd
from typing import Dict, Optional

logger = logging.getLogger("data_pipeline.store")

SNAPSHOT_SCHEMA = """
CREATE TABLE IF NOT EXISTS realtime_snapshot (
    code TEXT PRIMARY KEY,
    name TEXT,
    price REAL,
    change_pct REAL,
    turnover REAL,
    seal_funds REAL,
    seal_ratio_instant REAL,
    first_seal_time TEXT,
    blown_count INTEGER DEFAULT 0,
    sector TEXT,
    float_mcap REAL,
    score_intraday INTEGER,
    source_ts TEXT,
    source_tag TEXT
);
"""


class Store:
    """SQLite persistence for realtime snapshot data."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute(SNAPSHOT_SCHEMA)
        self.conn.commit()

    def write_snapshot(self, df: pd.DataFrame):
        """Upsert snapshot wide records into realtime_snapshot table."""
        if df.empty:
            return
        # Compute seal_ratio_instant from seal_funds / float_mcap
        df = df.copy()
        mask = df["seal_funds"].notna() & df["float_mcap"].notna() & (df["float_mcap"] > 0)
        df.loc[mask, "seal_ratio_instant"] = (
            df.loc[mask, "seal_funds"] / df.loc[mask, "float_mcap"] * 100
        )

        cols = [c for c in df.columns if c != "code"]
        placeholders = ", ".join([f"?{c}=excluded.{c}" for c in cols])
        col_names = ", ".join(["code"] + cols)
        col_qs = ", ".join(["?" for _ in range(len(cols) + 1)])

        sql = (
            f"INSERT INTO realtime_snapshot ({col_names}) "
            f"VALUES ({col_qs}) "
            f"ON CONFLICT(code) DO UPDATE SET {placeholders}"
        )

        rows = df.to_dict("records")
        for row in rows:
            vals = [row.get(c) for c in ["code"] + cols]
            vals = [None if (isinstance(v, float) and pd.isna(v)) else v for v in vals]
            try:
                self.conn.execute(sql, vals)
            except Exception as e:
                logger.warning("store upsert failed for %s: %s", row.get("code"), e)
        self.conn.commit()

    def get_snapshot(self) -> Dict[str, dict]:
        """Return current snapshot as dict of {code: row_dict}."""
        cursor = self.conn.execute("SELECT * FROM realtime_snapshot")
        rows = cursor.fetchall()
        columns = [d[0] for d in cursor.description]
        result = {}
        for row in rows:
            record = dict(zip(columns, row))
            code = record.pop("code", "")
            result[code] = record
        return result

    def cleanup(self):
        """Clear all rows from realtime_snapshot (called after market close)."""
        self.conn.execute("DELETE FROM realtime_snapshot")
        self.conn.commit()
        logger.info("realtime_snapshot cleared")

    def close(self):
        self.conn.close()
```

- [ ] **Step 3: Run tests**

```bash
python -m pytest tests/test_data_pipeline/test_store.py -v
# Expected: 4 passed
```

- [ ] **Step 4: Commit**

```bash
git add src/data_pipeline/store.py tests/test_data_pipeline/test_store.py
git commit -m "feat: add data pipeline SQLite store"
```

---

### Task 8: Rules and Push

**Files:**
- Create: `src/data_pipeline/rules.py`
- Create: `src/data_pipeline/push.py`
- Test: `tests/test_data_pipeline/test_rules.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_data_pipeline/test_rules.py
import pytest
import sys; sys.path.insert(0, "src")
from data_pipeline.rules import Rule, RULES, check_rules

def test_blown_alert_rule():
    """blown_alert should fire when blown_count >= 2"""
    rule = [r for r in RULES if r.name == "blown_alert"][0]
    class Row:
        blown_count = 2
        name = "测试"
        code = "000001"
    assert rule.condition(Row())

def test_blown_alert_no_fire():
    """blown_alert should NOT fire when blown_count < 2"""
    rule = [r for r in RULES if r.name == "blown_alert"][0]
    class Row:
        blown_count = 1
    assert not rule.condition(Row())

def test_sector_heat_rule():
    """sector_heat should fire when sector_limit_ups >= 5"""
    rule = [r for r in RULES if r.name == "sector_heat"][0]
    class Row:
        sector_limit_ups = 5
    assert rule.condition(Row())

def test_check_rules_matches():
    """check_rules should return matching rules"""
    class Row:
        code = "000001"
        name = "测试"
        blown_count = 2
        seal_drop_pct = 10
        sector_limit_ups = 1
    matches = check_rules(Row())
    names = [r.name for r in matches]
    assert "blown_alert" in names

def test_rate_limit():
    """Same rule+code should not fire within 5 minutes"""
    from data_pipeline.rules import _rate_limited
    assert not _rate_limited("blown_alert", "000001")  # First fire
    assert _rate_limited("blown_alert", "000001")       # Within 5 min
    assert not _rate_limited("sector_heat", "000001")   # Different rule
```

- [ ] **Step 2: Create rules.py**

```python
# src/data_pipeline/rules.py
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, List


_RATE_LIMIT: dict = {}  # {f"{rule_name}_{code}": datetime}


def _rate_limited(rule_name: str, code: str) -> bool:
    key = f"{rule_name}_{code}"
    now = datetime.now()
    last = _RATE_LIMIT.get(key)
    if last and (now - last) < timedelta(minutes=5):
        return True
    _RATE_LIMIT[key] = now
    return False


@dataclass
class Rule:
    name: str
    condition: Callable[..., bool]
    message_template: str

    def format(self, row) -> str:
        return self.message_template.format(**{k: getattr(row, k, "?") for k in ["name", "code", "sector", "blown_count", "seal_drop_pct", "sector_limit_ups"]})

    def matches(self, row) -> bool:
        return self.condition(row)


RULES: List[Rule] = [
    Rule(
        name="blown_alert",
        condition=lambda r: r.blown_count >= 2,
        message_template="⚠️ {name}({code}) 炸板 {blown_count} 次",
    ),
    Rule(
        name="sector_heat",
        condition=lambda r: getattr(r, "sector_limit_ups", 0) >= 5,
        message_template="🔥 {sector} 板块涨停 {sector_limit_ups} 家",
    ),
]


def check_rules(row) -> List[Rule]:
    """Return rules that match this row, respecting rate limits."""
    matched = []
    for rule in RULES:
        if rule.matches(row) and not _rate_limited(rule.name, row.code):
            matched.append(rule)
    return matched
```

- [ ] **Step 3: Create push.py**

```python
# src/data_pipeline/push.py
import asyncio
import logging
import os
import aiohttp

logger = logging.getLogger("data_pipeline.push")

ALERT_WEBHOOK_URL = os.getenv("ALERT_WEBHOOK_URL", "")


async def push_alert(rule_name: str, message: str):
    """Send alert to configured webhook."""
    if not ALERT_WEBHOOK_URL:
        return
    try:
        async with aiohttp.ClientSession() as session:
            await session.post(ALERT_WEBHOOK_URL, json={
                "msgtype": "text",
                "text": {"content": message},
            }, timeout=aiohttp.ClientTimeout(total=5))
        logger.info("alert pushed: %s", message)
    except Exception as e:
        logger.warning("alert push failed: %s", e)
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_data_pipeline/test_rules.py -v
# Expected: 5 passed
```

- [ ] **Step 5: Commit**

```bash
git add src/data_pipeline/rules.py src/data_pipeline/push.py tests/test_data_pipeline/test_rules.py
git commit -m "feat: add alert rules and push"
```

---

### Task 9: Engine (APScheduler lifecycle + polling loop)

**Files:**
- Create: `src/data_pipeline/engine.py`
- Test: `tests/test_data_pipeline/test_engine.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_data_pipeline/test_engine.py
import pytest
import sys; sys.path.insert(0, "src")
from datetime import datetime
from data_pipeline.engine import is_trading_day

def test_is_trading_day_weekday():
    """Should return True for Mon-Fri (heuristic)"""
    # 2026-06-26 is a Friday
    assert is_trading_day(datetime(2026, 6, 26))

def test_is_trading_day_weekend():
    """Should return False for Sat-Sun"""
    assert not is_trading_day(datetime(2026, 6, 27))  # Saturday
    assert not is_trading_day(datetime(2026, 6, 28))  # Sunday
```

- [ ] **Step 2: Create engine.py**

```python
# src/data_pipeline/engine.py
import asyncio
import logging
import os
from datetime import datetime, date
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from .collector import AshareCollector, ZTPoolCollector, NewsCollector
from .normalizer import normalize
from .merger import merge
from .store import Store
from .rules import check_rules
from .push import push_alert
from ..scorer import compute_relay_score

logger = logging.getLogger("data_pipeline.engine")

DB_PATH = os.getenv("RECAP_DB_PATH", os.path.join(os.path.dirname(__file__), "..", "..", "data", "recap.db"))


def is_trading_day(dt: Optional[datetime] = None) -> bool:
    """Heuristic: Mon-Fri. For precise calendar, use get_trading_days()."""
    dt = dt or datetime.now()
    return dt.weekday() < 5


class Pipeline:
    """Manages collector lifecycle and polling loop."""

    def __init__(self, db_path: str = DB_PATH):
        self.store = Store(db_path)
        self.ashare = AshareCollector()
        self.zt_pool = ZTPoolCollector()
        self.news = NewsCollector()

    def get_watchlist(self) -> list[str]:
        """Build dynamic watchlist from zt_pool snapshot + yesterday's candidates."""
        snapshot = self.store.get_snapshot()
        codes = list(snapshot.keys())

        # Also add yesterday's candidates from DB
        try:
            import sqlite3
            conn = sqlite3.connect(self.store.db_path)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT DISTINCT code FROM candidates WHERE date = (SELECT MAX(date) FROM candidates)"
            )
            codes.extend([r[0] for r in cursor.fetchall()])
            conn.close()
        except Exception as e:
            logger.warning("failed to read yesterday candidates: %s", e)

        return list(set(codes))

    async def run_polling_loop(self):
        """Main polling loop. Runs from 09:15 to 15:00."""
        if not is_trading_day():
            logger.info("非交易日，跳过")
            return

        logger.info("Polling loop started")

        while True:
            now = datetime.now()
            if now.hour > 15 or (now.hour == 15 and now.minute > 0):
                logger.info("收盘，停止轮询")
                break

            # Update watchlist from zt_pool snapshot
            self.ashare.update_watchlist(self.get_watchlist())

            for collector in [self.zt_pool, self.ashare, self.news]:
                if not collector.due():
                    continue
                try:
                    data = await asyncio.wait_for(collector.poll(), timeout=collector.interval)
                except (asyncio.TimeoutError, ConnectionError):
                    await asyncio.sleep(collector.retry_delay)
                    continue

                df = normalize(collector.name, data)
                if df.empty:
                    continue

                # Merge with existing snapshot
                merged = merge(collector.name, df, self.store.get_snapshot())
                if merged.empty:
                    continue

                # Compute sector_limit_ups and intraday score
                sector_counts = merged[merged["seal_funds"].notna()].groupby("sector").size()
                for idx, row in merged.iterrows():
                    sec = row.get("sector", "")
                    sec_count = int(sector_counts.get(sec, 0))
                    merged.at[idx, "score_intraday"] = compute_relay_score(row.to_dict(), sec_count)

                # Persist
                self.store.write_snapshot(merged)

                # Check rules
                for _, row in merged.iterrows():
                    matched = check_rules(row)
                    for rule in matched:
                        msg = rule.format(row)
                        logger.info("rule matched: %s", msg)
                        asyncio.create_task(push_alert(rule.name, msg))

            await asyncio.sleep(0.1)

    async def run(self):
        """Start APScheduler and wait."""
        scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")

        # 09:15 - 15:00 weekdays
        scheduler.add_job(
            self.run_polling_loop,
            CronTrigger(hour="9-14", minute="15-59", day_of_week="mon-fri"),
        )
        scheduler.add_job(
            self.run_polling_loop,
            CronTrigger(hour="15", minute="0", day_of_week="mon-fri"),
        )
        # 15:05 cleanup
        scheduler.add_job(
            self.store.cleanup,
            CronTrigger(hour="15", minute="5", day_of_week="mon-fri"),
        )

        scheduler.start()
        logger.info("Pipeline scheduler started")

        try:
            # Keep alive
            while True:
                await asyncio.sleep(3600)
        except asyncio.CancelledError:
            scheduler.shutdown(wait=False)
            self.store.close()
```

- [ ] **Step 3: Run tests**

```bash
python -m pytest tests/test_data_pipeline/test_engine.py -v
# Expected: 2 passed
```

- [ ] **Step 4: Commit**

```bash
git add src/data_pipeline/engine.py tests/test_data_pipeline/test_engine.py
git commit -m "feat: add pipeline engine with APScheduler lifecycle"
```

---

### Task 10: CLI entry point

**Files:**
- Create: `src/data_pipeline/__main__.py`

- [ ] **Step 1: Create __main__.py**

```python
# src/data_pipeline/__main__.py
"""CLI entry: python -m src.data_pipeline [--db PATH]"""
import argparse
import asyncio
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)


def main():
    parser = argparse.ArgumentParser(description="寻龙诀 盘中实时数据管道")
    parser.add_argument("--db", default=None, help="recap.db path")
    args = parser.parse_args()

    from .engine import Pipeline

    pipeline = Pipeline(db_path=args.db) if args.db else Pipeline()

    try:
        asyncio.run(pipeline.run())
    except KeyboardInterrupt:
        logging.getLogger("data_pipeline").info("Shutdown by user")
        sys.exit(0)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify it starts and exits cleanly**

```bash
python -m src.data_pipeline --db /tmp/test_recap.db &
PID=$!
sleep 2
kill $PID 2>/dev/null
# Expected: clean startup, no traceback
```

- [ ] **Step 3: Commit**

```bash
git add src/data_pipeline/__main__.py
git commit -m "feat: add CLI entry point for data pipeline"
```

---

### Task 11: Integrate recap_engine with realtime_snapshot

**Files:**
- Modify: `src/recap_engine.py`

- [ ] **Step 1: Add realtime_snapshot read in run_recap()**

After the `init_db()` call and before fetching data, read `realtime_snapshot` if available. This is a passive read — no dependency, just a warm cache.

In `run_recap()`, after `init_db()`, add:

```python
    # Optional warm cache from intraday pipeline
    try:
        cursor = conn.execute("PRAGMA table_info(realtime_snapshot)")
        if cursor.fetchall():
            cursor = conn.execute("SELECT * FROM realtime_snapshot")
            snap_cols = [d[0] for d in cursor.description]
            snap_rows = cursor.fetchall()
            if snap_rows:
                print(f"Loaded {len(snap_rows)} records from realtime_snapshot (intraday cache)")
    except Exception:
        pass  # Table doesn't exist or empty — silently ignore
```

- [ ] **Step 2: Commit**

```bash
git add src/recap_engine.py
git commit -m "feat: add realtime_snapshot warm cache read"
```

---

### Task 12: Panel intraday-snapshot endpoint

**Files:**
- Modify: `vendor/tickflow-stock-panel/backend/app/api/recap.py`

- [ ] **Step 1: Add /api/recap/intraday-snapshot endpoint**

Add to the existing `recap.py` router:

```python
@router.get("/api/recap/intraday-snapshot")
async def get_intraday_snapshot(request: Request):
    """Return realtime_snapshot table as JSON (polled by frontend every 5s)."""
    import sqlite3
    import os
    from app.config import settings

    # Find recap.db (same fallback logic as other recap endpoints)
    db_path = (
        os.getenv("RECAP_DB_PATH")
        or os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "..", "data", "recap.db")
    )
    if not os.path.exists(db_path):
        return {"snapshot": [], "ts": None}

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.execute("PRAGMA table_info(realtime_snapshot)")
        if not cursor.fetchall():
            return {"snapshot": [], "ts": None}
        cursor = conn.execute("SELECT * FROM realtime_snapshot ORDER BY score_intraday DESC NULLS LAST")
        rows = [dict(r) for r in cursor.fetchall()]
        ts = rows[0]["source_ts"] if rows else None
        return {"snapshot": rows, "ts": ts}
    finally:
        conn.close()
```

- [ ] **Step 2: Test the endpoint**

```bash
# First ensure recap.db has realtime_snapshot data
python -m src.data_pipeline --db data/recap.db &
# Wait a few seconds for data
curl http://localhost:3018/api/recap/intraday-snapshot | python -m json.tool
# Expected: {"snapshot": [...], "ts": "..."} or empty
kill %1 2>/dev/null
```

- [ ] **Step 3: Commit**

```bash
git add vendor/tickflow-stock-panel/backend/app/api/recap.py
git commit -m "feat: add intraday-snapshot endpoint to vendor panel"
```

---

### Task 13: Integration smoke test

- [ ] **Step 1: Run pipeline against real recap.db**

```bash
# Ensure data/recap.db exists (from previous recap runs)
python -m src.data_pipeline --db data/recap.db &
PID=$!
sleep 15  # Let it run a few cycles
python -c "
import sys; sys.path.insert(0, 'src')
from data_pipeline.store import Store
s = Store('data/recap.db')
snap = s.get_snapshot()
print(f'Snapshot records: {len(snap)}')
if snap:
    codes = list(snap.keys())[:5]
    for code in codes:
        rec = snap[code]
        print(f'  {code}: {rec.get(\"name\",\"\")} price={rec.get(\"price\",\"\")} seal_funds={rec.get(\"seal_funds\",\"\")} score={rec.get(\"score_intraday\",\"\")}')
s.close()
"
kill $PID 2>/dev/null
# Expected: data flowing, scores computed
```

- [ ] **Step 2: Run full test suite**

```bash
python -m pytest tests/ -v
# Expected: all existing + new tests pass
```

- [ ] **Step 3: Commit final**

```bash
git add -A
git commit -m "feat: complete real-time data pipeline v1"
```
