# 量比真实计算(E05)Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在盘后 `compute_relay_score` 新增量比(volume_ratio)作为第 7 个加性评分维度,补齐 E05 核弹信号与位置×量价矩阵。

**Architecture:** recap_engine 在调用 compute_relay_score 之前批量预取 mootdx 日K线,计算 volume_ratio 与 price_position,通过 row dict 传入纯函数 scorer。scorer 新增两个纯函数加法贡献分值。数据缺失降级为0分。feature_flag 默认关闭(shadow 模式)。

**Tech Stack:** Python, mootdx(日K线), pytest(TDD), TOML(配置)

**Constraints:** 保留 candidates.score 0-150 语义;compute_relay_score 保持纯函数无网络调用;盘后盘中共享 scorer.py;数据缺失禁止填0伪装。

---

## 文件结构

| 文件 | 责任 | 操作 |
|------|------|------|
| `src/scorer.py` | 0-150 接力指数纯函数 | 新增2函数+集成到 compute_relay_score |
| `src/recap_engine.py` | 盘后编排 | 新增 prefetch_volume_features + 调用点集成 |
| `src/rule_contract.py` | 规则枚举与配置 | 新增原因码 + feature_flag 校验 |
| `config/rules/dragon_formula_v1.toml` | 规则配置 | 新增 [volume_ratio] 段 + feature_flag |
| `tests/test_scorer_volume_ratio.py` | 量比纯函数单元测试 | 新建 |
| `tests/test_volume_prefetch.py` | 预取函数单元测试 | 新建 |

---

### Task 1: 量比基础分纯函数 _volume_ratio_points(TDD)

**Files:**
- Create: `tests/test_scorer_volume_ratio.py`
- Modify: `src/scorer.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_scorer_volume_ratio.py`:

```python
"""Tests for volume ratio scoring dimension (E05)."""
from __future__ import annotations

from scorer import _volume_ratio_points


class TestVolumeRatioPoints:
    def test_nuke_threshold_returns_10(self):
        assert _volume_ratio_points(3.5) == 10

    def test_nuke_boundary_3_0_returns_10(self):
        assert _volume_ratio_points(3.0) == 10

    def test_significant_2_to_3_returns_5(self):
        assert _volume_ratio_points(2.5) == 5

    def test_significant_boundary_2_0_returns_5(self):
        assert _volume_ratio_points(2.0) == 5

    def test_neutral_0_8_to_2_returns_0(self):
        assert _volume_ratio_points(1.0) == 0

    def test_neutral_boundary_0_8_returns_0(self):
        assert _volume_ratio_points(0.8) == 0

    def test_shrink_below_0_8_returns_neg3(self):
        assert _volume_ratio_points(0.5) == -3

    def test_none_returns_0(self):
        assert _volume_ratio_points(None) == 0

    def test_nan_returns_0(self):
        assert _volume_ratio_points(float("nan")) == 0

    def test_zero_returns_0(self):
        assert _volume_ratio_points(0.0) == 0

    def test_negative_returns_0(self):
        assert _volume_ratio_points(-1.0) == 0
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd /Users/angojay/20_Projects/Dragon-Seeking-Formula && .venv/bin/python3 -m pytest tests/test_scorer_volume_ratio.py -v
```
Expected: FAIL with `ImportError: cannot import name '_volume_ratio_points' from 'scorer'`

- [ ] **Step 3: 写最小实现**

在 `src/scorer.py` 的 `_sector_points` 函数之后(约 line 123 后)、`_noise_caps` 之前,添加:

```python
def _volume_ratio_points(volume_ratio: float | None) -> int:
    """E05: 量比基础分。量比≥3核弹+10,2-3显著+5,0.8-2中性0,<0.8缩量-3。

    数据缺失(None/NaN/≤0)返回0(降级不加分)。
    """
    if volume_ratio is None:
        return 0
    try:
        vr = float(volume_ratio)
    except (TypeError, ValueError):
        return 0
    if vr != vr or vr <= 0:  # NaN or non-positive
        return 0
    if vr >= 3.0:
        return 10
    if vr >= 2.0:
        return 5
    if vr >= 0.8:
        return 0
    return -3
```

- [ ] **Step 4: 运行测试确认通过**

```bash
.venv/bin/python3 -m pytest tests/test_scorer_volume_ratio.py -v
```
Expected: 11 passed

- [ ] **Step 5: 提交**

```bash
git add tests/test_scorer_volume_ratio.py src/scorer.py
git commit -m "feat: add _volume_ratio_points E05 nuke signal scoring function"
```

---

### Task 2: 位置×量价联调纯函数 _volume_position_bonus(TDD)

**Files:**
- Modify: `tests/test_scorer_volume_ratio.py`
- Modify: `src/scorer.py`

- [ ] **Step 1: 追加失败测试**

在 `tests/test_scorer_volume_ratio.py` 末尾追加:

```python
from scorer import _volume_position_bonus


class TestVolumePositionBonus:
    # 低位(<0.33): 放量+5, 平量+2, 缩量-2
    def test_low_position_heavy_volume_plus5(self):
        assert _volume_position_bonus(2.5, 0.2) == 5

    def test_low_position_normal_volume_plus2(self):
        assert _volume_position_bonus(1.0, 0.2) == 2

    def test_low_position_shrink_neg2(self):
        assert _volume_position_bonus(0.5, 0.2) == -2

    # 中位(0.33~0.66): 放量+3, 平量0, 缩量-3
    def test_mid_position_heavy_volume_plus3(self):
        assert _volume_position_bonus(2.5, 0.5) == 3

    def test_mid_position_normal_volume_zero(self):
        assert _volume_position_bonus(1.0, 0.5) == 0

    def test_mid_position_shrink_neg3(self):
        assert _volume_position_bonus(0.5, 0.5) == -3

    # 高位(>0.66): 放量-5, 平量-2, 缩量+3
    def test_high_position_heavy_volume_neg5(self):
        assert _volume_position_bonus(3.5, 0.8) == -5

    def test_high_position_normal_volume_neg2(self):
        assert _volume_position_bonus(1.0, 0.8) == -2

    def test_high_position_shrink_plus3(self):
        assert _volume_position_bonus(0.5, 0.8) == 3

    # 边界: position 恰好 0.33 归中位, 0.66 归中位
    def test_boundary_0_33_is_mid(self):
        assert _volume_position_bonus(2.5, 0.33) == 3

    def test_boundary_0_66_is_mid(self):
        assert _volume_position_bonus(2.5, 0.66) == 3

    # 降级
    def test_none_volume_ratio_returns_0(self):
        assert _volume_position_bonus(None, 0.5) == 0

    def test_none_position_returns_0(self):
        assert _volume_position_bonus(2.5, None) == 0

    def test_nan_volume_returns_0(self):
        assert _volume_position_bonus(float("nan"), 0.5) == 0

    def test_zero_volume_returns_0(self):
        assert _volume_position_bonus(0.0, 0.5) == 0
```

- [ ] **Step 2: 运行测试确认失败**

```bash
.venv/bin/python3 -m pytest tests/test_scorer_volume_ratio.py::TestVolumePositionBonus -v
```
Expected: FAIL with `ImportError: cannot import name '_volume_position_bonus'`

- [ ] **Step 3: 写最小实现**

在 `src/scorer.py` 的 `_volume_ratio_points` 之后添加:

```python
def _volume_position_bonus(volume_ratio: float | None, price_position: float | None) -> int:
    """位置×量价联调加分。知识库乘性矩阵翻译为加减分。

    低位放量(吸筹)+5 / 高位爆量(派发)-5 / 高位缩量(健康)+3 等。
    数据缺失返回0(降级)。
    """
    if volume_ratio is None or price_position is None:
        return 0
    try:
        vr = float(volume_ratio)
        pos = float(price_position)
    except (TypeError, ValueError):
        return 0
    if vr != vr or pos != pos or vr <= 0:  # NaN or non-positive
        return 0
    heavy = vr >= 2.0
    light = vr < 0.8
    if pos < 0.33:
        return 5 if heavy else (-2 if light else 2)
    if pos > 0.66:
        return -5 if heavy else (3 if light else -2)
    return 3 if heavy else (-3 if light else 0)
```

- [ ] **Step 4: 运行测试确认通过**

```bash
.venv/bin/python3 -m pytest tests/test_scorer_volume_ratio.py -v
```
Expected: 26 passed (11 from Task 1 + 15 new)

- [ ] **Step 5: 提交**

```bash
git add tests/test_scorer_volume_ratio.py src/scorer.py
git commit -m "feat: add _volume_position_bonus price×volume matrix scoring"
```

---

### Task 3: 集成到 compute_relay_score(TDD)

**Files:**
- Modify: `tests/test_scorer_volume_ratio.py`
- Modify: `src/scorer.py:125-210`

- [ ] **Step 1: 追加集成测试**

在 `tests/test_scorer_volume_ratio.py` 末尾追加:

```python
from scorer import compute_relay_score


def _base_row(**overrides):
    """构造一个基础候选 row,默认全中性值,可覆盖。"""
    row = {
        "first_seal_time": "093500",
        "blown_count": 0,
        "float_mcap": 5e9,  # 50亿
        "seal_funds": 1e8,   # 1亿
        "turnover": 8.0,     # 8%
    }
    row.update(overrides)
    return row


class TestComputeRelayScoreWithVolume:
    def test_volume_ratio_increases_score(self):
        """有量比维度时分数高于无量比(其他相同)。"""
        base = compute_relay_score(_base_row(), 3)
        with_vol = compute_relay_score(_base_row(volume_ratio=3.5, price_position=0.2), 3)
        assert with_vol > base

    def test_missing_volume_ratio_degrades_to_base(self):
        """volume_ratio 缺失时退化为原6维(等于不传该字段)。"""
        no_vol = compute_relay_score(_base_row(), 3)
        none_vol = compute_relay_score(_base_row(volume_ratio=None, price_position=None), 3)
        assert no_vol == none_vol

    def test_nuke_low_position_max_bonus(self):
        """量比≥3 + 低位放量 = 核弹+10 + 联调+5 = +15。"""
        base = compute_relay_score(_base_row(), 3)
        nuke = compute_relay_score(_base_row(volume_ratio=3.5, price_position=0.2), 3)
        assert nuke - base == 15

    def test_high_position_heavy_volume_penalizes(self):
        """高位爆量 = 核弹+10 + 联调-5 = +5(比中性少)。"""
        base = compute_relay_score(_base_row(), 3)
        high_blow = compute_relay_score(_base_row(volume_ratio=3.5, price_position=0.8), 3)
        assert high_blow - base == 5

    def test_score_stays_within_0_150(self):
        """量比不突破 0-150 边界。"""
        high = compute_relay_score(_base_row(volume_ratio=10.0, price_position=0.1), 6)
        assert 0 <= high <= 150
```

- [ ] **Step 2: 运行测试确认失败**

```bash
.venv/bin/python3 -m pytest tests/test_scorer_volume_ratio.py::TestComputeRelayScoreWithVolume -v
```
Expected: FAIL — `test_volume_ratio_increases_score` 失败(compute_relay_score 当前忽略 volume_ratio)

- [ ] **Step 3: 集成到 compute_relay_score 和 _noise_caps**

修改 `src/scorer.py` 的 `_noise_caps` 函数(在 sector_points 参数后加 volume_points):

```python
def _noise_caps(
    score: int,
    time_str: str,
    blown: int,
    turnover: float,
    sector_limit_ups: int,
    is_one_word: bool,
    timing_points: int,
    stability_points: int,
    seal_points: int,
    size_points: int,
    turnover_points: int,
    sector_points: int,
    volume_points: int,
) -> int:
    supportive_factors = sum(
        p >= 10
        for p in (
            timing_points,
            stability_points,
            seal_points,
            size_points,
            turnover_points,
            sector_points,
            volume_points,
        )
    )

    if supportive_factors <= 2:
        score = min(score, 85)
    elif supportive_factors == 3:
        score = min(score, 100)

    if blown >= 2:
        score = min(score, 80)
    if sector_limit_ups <= 1 and not is_one_word:
        score = min(score, 90)
    if time_str >= "140000" and not is_one_word:
        score = min(score, 75)
    if turnover > 20.0 and blown >= 1:
        score = min(score, 70)

    return score
```

修改 `compute_relay_score`(在 sector_points 计算后、score 加总前加入量比维度):

```python
def compute_relay_score(row: dict, sector_limit_ups: int) -> int:
    """Compute the 1进2 relay score (0-150) for a limit-up candidate."""
    time_str = _normalize_time(row.get("first_seal_time"))
    is_one_word = time_str == "092500"

    blown = _safe_int(row.get("blown_count"), 0)
    float_mcap = _safe_float(row.get("float_mcap"), 0.0)
    seal_funds = _safe_float(row.get("seal_funds"), 0.0)
    turnover = _safe_float(row.get("turnover"), 0.0)
    sector_limit_ups = _safe_int(sector_limit_ups, 0)
    volume_ratio = row.get("volume_ratio")  # None if absent
    price_position = row.get("price_position")

    timing_points = _time_points(time_str)
    stability_points = _stability_points(blown)
    seal_points = _seal_points(seal_funds, float_mcap)
    size_points = _size_points(float_mcap)
    turnover_points = _turnover_points(turnover, is_one_word)
    sector_points = _sector_points(sector_limit_ups)
    volume_points = _volume_ratio_points(volume_ratio) + _volume_position_bonus(
        volume_ratio, price_position
    )

    score = 50 + (
        timing_points
        + stability_points
        + seal_points
        + size_points
        + turnover_points
        + sector_points
        + volume_points
    )

    score = _noise_caps(
        score=score,
        time_str=time_str,
        blown=blown,
        turnover=turnover,
        sector_limit_ups=sector_limit_ups,
        is_one_word=is_one_word,
        timing_points=timing_points,
        stability_points=stability_points,
        seal_points=seal_points,
        size_points=size_points,
        turnover_points=turnover_points,
        sector_points=sector_points,
        volume_points=volume_points,
    )

    return max(0, min(150, score))
```

- [ ] **Step 4: 运行测试确认通过**

```bash
.venv/bin/python3 -m pytest tests/test_scorer_volume_ratio.py -v
.venv/bin/python3 -m pytest tests/test_recap_pipeline.py -q
```
Expected: test_scorer_volume_ratio.py 31 passed;test_recap_pipeline.py 全绿(回归:无 volume_ratio 字段时退化为原6维)

- [ ] **Step 5: 提交**

```bash
git add tests/test_scorer_volume_ratio.py src/scorer.py
git commit -m "feat: integrate volume ratio as 7th scoring dimension in compute_relay_score"
```

---

### Task 4: rule_contract.py 原因码与配置(TDD)

**Files:**
- Modify: `src/rule_contract.py`
- Modify: `config/rules/dragon_formula_v1.toml`
- Test: `tests/test_rule_contract.py`

- [ ] **Step 1: 追加失败测试**

在 `tests/test_rule_contract.py` 末尾追加(先查看该文件现有测试风格,保持一致):

```python
def test_volume_ratio_missing_reason_code_exists():
    """VOLUME_RATIO_MISSING 原因码已定义。"""
    from src.rule_contract import ReasonCode
    assert ReasonCode.VOLUME_RATIO_MISSING.value == "VOLUME_RATIO_MISSING"


def test_volume_ratio_nuke_reason_code_exists():
    """VOLUME_RATIO_NUKE 原因码已定义。"""
    from src.rule_contract import ReasonCode
    assert ReasonCode.VOLUME_RATIO_NUKE.value == "VOLUME_RATIO_NUKE"


def test_enforce_volume_ratio_flag_validates():
    """feature_flags.enforce_volume_ratio 必须是 bool。"""
    from src.rule_contract import load_rule_config
    cfg = load_rule_config()
    assert isinstance(cfg.raw["feature_flags"]["enforce_volume_ratio"], bool)
```

- [ ] **Step 2: 运行测试确认失败**

```bash
.venv/bin/python3 -m pytest tests/test_rule_contract.py -k "volume_ratio" -v
```
Expected: FAIL — `VOLUME_RATIO_MISSING` 不存在 / `enforce_volume_ratio` key 缺失

- [ ] **Step 3: 加原因码**

在 `src/rule_contract.py` 的 `ReasonCode` 枚举里(在 `WEAK_SEAL_50_TO_100M` 之后)添加:

```python
    # 量比维度(E05)
    VOLUME_RATIO_MISSING = "VOLUME_RATIO_MISSING"
    VOLUME_RATIO_NUKE = "VOLUME_RATIO_NUKE"
```

在 `_validate` 函数的 feature_flags 检查列表里(在 `"personality_enforce"` 之后)添加:

```python
        "enforce_volume_ratio",
```

在 `config/rules/dragon_formula_v1.toml` 的 `[feature_flags]` 段(在 `personality_enforce` 之后)添加:

```toml
enforce_volume_ratio = false  # Phase X:量比维度(默认关闭,回测达标后开启)
```

在 `config/rules/dragon_formula_v1.toml` 末尾新增段:

```toml
[volume_ratio]
nuke_threshold = 3.0
nuke_points = 10
significant_threshold = 2.0
significant_points = 5
shrink_threshold = 0.8
shrink_points = -3
position_lookback = 20
volume_ma_window = 5
```

- [ ] **Step 4: 运行测试确认通过**

```bash
.venv/bin/python3 -m pytest tests/test_rule_contract.py -v
```
Expected: 全绿(含新增3个测试)

- [ ] **Step 5: 提交**

```bash
git add src/rule_contract.py config/rules/dragon_formula_v1.toml tests/test_rule_contract.py
git commit -m "feat: add VOLUME_RATIO reason codes and config section"
```

---

### Task 5: 预取函数 prefetch_volume_features(TDD)

**Files:**
- Create: `tests/test_volume_prefetch.py`
- Modify: `src/recap_engine.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_volume_prefetch.py`:

```python
"""Tests for prefetch_volume_features — mootdx volume ratio pre-fetching."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd

from recap_engine import prefetch_volume_features


def _mock_bars_df(volumes: list[float], closes: list[float],
                  highs: list[float], lows: list[float]) -> pd.DataFrame:
    """构造 mootdx.bars() 返回格式的 DataFrame。"""
    n = len(volumes)
    return pd.DataFrame({
        "volume": volumes,
        "close": closes,
        "high": highs,
        "low": lows,
        "datetime": [f"2026-06-{20+i:02d} 15:00" for i in range(n)],
    })


class TestPrefetchVolumeFeatures:
    def test_computes_volume_ratio_and_position(self):
        """正常返回 volume_ratio 和 price_position。"""
        # 25日:今日 volume=300000,前5日均=100000 → ratio=3.0(核弹)
        volumes = [100000] * 24 + [300000]
        closes = [10.0] * 20 + [11.0, 12.0, 9.0, 10.5, 11.0]
        highs = [10.5] * 20 + [11.5, 12.5, 9.5, 11.0, 11.5]
        lows = [9.5] * 20 + [10.5, 11.5, 8.5, 10.0, 10.5]
        mock_df = _mock_bars_df(volumes, closes, highs, lows)

        mock_client = MagicMock()
        mock_client.bars.return_value = mock_df
        with patch("recap_engine.Quotes") as mock_quotes_cls:
            mock_quotes_cls.factory.return_value = mock_client
            result = prefetch_volume_features(["000001"], "2026-06-30")

        assert "000001" in result
        vr = result["000001"]["volume_ratio"]
        pp = result["000001"]["price_position"]
        assert vr is not None
        assert 2.9 <= vr <= 3.1  # 300000/100000 = 3.0
        assert pp is not None
        assert 0.0 <= pp <= 1.0

    def test_single_code_failure_does_not_affect_others(self):
        """code A 抛异常,code B 正常返回。"""
        good_df = _mock_bars_df([100000] * 24 + [200000],
                                [10.0] * 25, [10.5] * 25, [9.5] * 25)
        mock_client = MagicMock()
        mock_client.bars.side_effect = [Exception("network error"), good_df]
        with patch("recap_engine.Quotes") as mock_quotes_cls:
            mock_quotes_cls.factory.return_value = mock_client
            result = prefetch_volume_features(["000001", "000002"], "2026-06-30")

        assert result["000001"]["volume_ratio"] is None
        assert result["000002"]["volume_ratio"] is not None

    def test_all_failure_returns_all_none(self):
        """全部失败返回全 None dict(不阻断流程)。"""
        mock_client = MagicMock()
        mock_client.bars.side_effect = Exception("network error")
        with patch("recap_engine.Quotes") as mock_quotes_cls:
            mock_quotes_cls.factory.return_value = mock_client
            result = prefetch_volume_features(["000001", "000002"], "2026-06-30")

        assert all(v["volume_ratio"] is None for v in result.values())
        assert all(v["price_position"] is None for v in result.values())

    def test_empty_codes_returns_empty_dict(self):
        with patch("recap_engine.Quotes") as mock_quotes_cls:
            result = prefetch_volume_features([], "2026-06-30")
        assert result == {}
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd /Users/angojay/20_Projects/Dragon-Seeking-Formula && .venv/bin/python3 -m pytest tests/test_volume_prefetch.py -v
```
Expected: FAIL with `ImportError: cannot import name 'prefetch_volume_features'`

- [ ] **Step 3: 写最小实现**

`src/recap_engine.py` 顶部当前**没有** `from mootdx.quotes import Quotes`(已确认:import 块在 line 1-35,无 mootdx)。需在 import 区(line 35 后,`sys.path.append` 块之前或之内)添加:

```python
from mootdx.quotes import Quotes
```

然后在 import 块结束后(line 65 `ADAPTER = get_adapter()` 附近,作为模块级函数)添加:

```python
def prefetch_volume_features(codes: list[str], today_date: str) -> dict[str, dict]:
    """批量预取候选的量比与价格位置。

    网络调用(mootdx Quotes.factory().bars()),必须在 SQLite 写事务之外调用。
    对每个 code 取近25日日K线,计算:
      - volume_ratio: 今日成交量 / 前5日平均成交量
      - price_position: 今日收盘在近20日高低区间的分位

    与 AStockAdapter 现有方法一致,每次现建 Quotes.client(不缓存)。

    Args:
        codes: 候选证券代码列表(6位字符串)
        today_date: 今日日期 YYYY-MM-DD(仅用于日志)

    Returns:
        {code: {"volume_ratio": float|None, "price_position": float|None}}
        单票失败该 code 值为 None;全部失败返回全 None dict。
    """
    result: dict[str, dict] = {}
    if not codes:
        return result

    try:
        client = Quotes.factory(market="std")
    except Exception:
        return {code: {"volume_ratio": None, "price_position": None} for code in codes}

    for code in codes:
        try:
            market = 1 if code.startswith(("6", "9")) else 0
            df = client.bars(symbol=code, market=market, category=9, start=0, count=25)
            if df is None or len(df) < 6:
                result[code] = {"volume_ratio": None, "price_position": None}
                continue

            volumes = df["volume"].tolist()
            closes = df["close"].tolist()
            highs = df["high"].tolist()
            lows = df["low"].tolist()

            today_vol = float(volumes[-1])
            prev_5d_avg = sum(float(v) for v in volumes[-6:-1]) / 5.0
            volume_ratio = today_vol / prev_5d_avg if prev_5d_avg > 0 else None

            lookback = min(20, len(volumes))
            recent_high = max(float(h) for h in highs[-lookback:])
            recent_low = min(float(l) for l in lows[-lookback:])
            today_close = float(closes[-1])
            if recent_high > recent_low:
                price_position = (today_close - recent_low) / (recent_high - recent_low)
            else:
                price_position = None

            result[code] = {"volume_ratio": volume_ratio, "price_position": price_position}
        except Exception:
            result[code] = {"volume_ratio": None, "price_position": None}

    return result
```

- [ ] **Step 4: 运行测试确认通过**

```bash
.venv/bin/python3 -m pytest tests/test_volume_prefetch.py -v
```
Expected: 4 passed

- [ ] **Step 5: 提交**

```bash
git add tests/test_volume_prefetch.py src/recap_engine.py
git commit -m "feat: add prefetch_volume_features for mootdx kline batch pre-fetch"
```

---

### Task 6: 集成预取到 recap_engine 调用点

**Files:**
- Modify: `src/recap_engine.py:1285-1300`

- [ ] **Step 1: 修改调用点**

在 `src/recap_engine.py` 的 `from scorer import compute_relay_score, generate_playbook`(line 1285)之前,添加预取调用并构造 volume_features dict。

定位 `if not df_1b.empty:`(line 1287),在其之前添加:

```python
        # 量比预取(网络调用,位于写事务之外)。失败降级为 None,不阻断。
        vol_features = {}
        if not df_1b.empty:
            try:
                codes = df_1b["code"].astype(str).str.zfill(6).tolist()
                vol_features = prefetch_volume_features(codes, date_str)
            except Exception:
                vol_features = {}
```

修改 `compute_relay_score` 调用(line 1289-1298),在 row dict 里加入 volume_ratio 和 price_position:

```python
            df_1b["relay_score"] = df_1b.apply(
                lambda r: compute_relay_score(
                    {
                        "first_seal_time": r["first_seal_time"],
                        "blown_count": r["blown_count"],
                        "float_mcap": r["float_mcap_yuan"],
                        "seal_funds": r["seal_funds_yuan"],
                        "turnover": r["turnover_pct"],
                        "volume_ratio": vol_features.get(str(r["code"]).zfill(6), {}).get("volume_ratio"),
                        "price_position": vol_features.get(str(r["code"]).zfill(6), {}).get("price_position"),
                    },
                    sector_counts.get(r["sector"], 1),
                ),
                axis=1,
            ).astype(int)
```

注:`prefetch_volume_features` 签名为 `(codes, today_date)`,内部自行创建 mootdx `Quotes.factory(market="std")` client,不依赖 adapter 实例(与 AStockAdapter 现有方法模式一致)。`date_str` 为 `run_recap` 函数参数(已确认 line 1122),在该作用域可用。

- [ ] **Step 2: 运行回归测试**

```bash
.venv/bin/python3 -m pytest tests/test_recap_pipeline.py tests/test_scorer_volume_ratio.py tests/test_volume_prefetch.py -q
.venv/bin/python3 -m ruff check src tests
```
Expected: 全绿;ruff 无新警告

- [ ] **Step 3: 提交**

```bash
git add src/recap_engine.py
git commit -m "feat: wire prefetch_volume_features into relay score computation"
```

---

### Task 7: 全量验证与金样本回归

- [ ] **Step 1: 全量 pytest**

```bash
.venv/bin/python3 -m pytest -q
```
Expected: 原有 402 + 新增 ~19 = ~421 passed,0 failed

- [ ] **Step 2: ruff**

```bash
.venv/bin/python3 -m ruff check src tests
```
Expected: All checks passed

- [ ] **Step 3: 金样本回归(AGENTS.md 要求)**

```bash
# 若金样本测试在 pytest 中(检查是否存在 test_golden_candidates.py)
.venv/bin/python3 -m pytest tests/test_golden_candidates.py -v
```
Expected: 全绿(量比默认关闭 via feature_flag,且 volume_ratio 字段在金样本 fixture 缺失时降级为0分,不改变历史候选分数)

- [ ] **Step 4: 最终检查**

```bash
git log --oneline feature/volume-ratio-e05 ^main
git diff main --stat
```
确认提交历史清晰,改动文件符合预期。

- [ ] **Step 5: push**

```bash
git push -u origin feature/volume-ratio-e05
```

---

## 完成判据

- `_volume_ratio_points` 与 `_volume_position_bonus` 纯函数实现,覆盖边界测试
- `compute_relay_score` 集成量比为第7维,0-150 语义不变
- `prefetch_volume_features` 批量预取,单票失败不影响其他
- `rule_contract.py` 新增原因码,`dragon_formula_v1.toml` 新增配置段
- `enforce_volume_ratio` feature_flag 默认 false(shadow)
- 全量 pytest 通过(无回归)
- 金样本回归通过(历史候选分数不变)
- 特性分支已 push
