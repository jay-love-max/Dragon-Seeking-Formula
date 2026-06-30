## 量比真实计算(E05)设计方案

- **日期**:2026-06-30
- **版本**:1.0
- **状态**:设计已确认
- **结论**:在盘后 `compute_relay_score` 中新增量比(volume_ratio)作为第 7 个加性评分维度,引入位置×量价矩阵翻译为加减分,数据由 recap_engine 批量预取 mootdx 日K线后传入。数据缺失时降级为不加分,不污染 0-150 语义。

---

### 1. 背景与问题

知识库《量价评分模块》(6/29)明确指出:**评分系统原来完全没量比概念,只靠绝对成交额阈值。知识库中的 volume_ratio 传的是 `amount_yi/chg` 假量比,导致所有量价智慧规则白写了。**

当前 `src/scorer.py` 的 `compute_relay_score` 只有 6 个加性维度:时间(_time_points)、稳定性(_stability_points)、封单(_seal_points)、市值(_size_points)、换手(_turnover_points)、板块(_sector_points)。**完全缺失量比维度**,即 E05(量比≥3=核弹级信号,胜率86.7%)和位置×量价评分矩阵(低位放量×1.08/高位爆量×0.85)均未落地。

这是评分体系最大的结构性缺口(见 2026-06-30 进度评估)。

**本设计范围**:仅盘后 `compute_relay_score` 新增量比维度。盘中 `score_intraday` 不在本期范围(数据源与实时性要求不同,需单独设计)。

---

### 2. 关键概念定义

**量比 (Volume Ratio)**:
今日成交量 / 过去5个交易日平均成交量。盘后场景下今日成交量是收盘后的完整全天值,无需时间修正(与盘中"开盘9:30量比天然大"不同)。

**价格位置 (Price Position)**:
当日收盘价在过去 N 日(N=20)最高价与最低价之间的分位数:
`position = (close - low_N) / (high_N - low_N)`,范围 0~1。
- 低位(<0.33):处于近20日区间下三分之一
- 中位(0.33~0.66):中段
- 高位(>0.66):上三分之一

**量价矩阵**:
知识库《量价评分模块》定义的价格位置×量价联调系数:

| 价格位置 | 放量(量比≥2) | 平量(0.8~2) | 缩量(<0.8) |
|---------|:---:|:---:|:---:|
| 低位(0~33%) | +0.08 | +0.03 | -0.02 |
| 中位(33~66%) | +0.05 | 0 | -0.03 |
| 高位(66~100%) | -0.05 | -0.02 | +0.03 |

注:知识库矩阵为乘性系数,本设计翻译为等效加减分(见 §4)。

---

### 3. 整体架构

```
recap_engine.py 盘后采集阶段(写事务之外)
  │  对每个首板候选:
  │  1. mootdx.bars() 取近25日日K线(volume + high/low/close)
  │     (25日同时满足两个需求:前5日均量用最近6根含今日,位置用最近20根)
  │  2. 计算 volume_ratio = today_volume / mean(prev_5d_volume)
  │  3. 计算 price_position = (close - min_20d_low) / (max_20d_high - min_20d_low)
  │  4. 填入 candidate row dict: volume_ratio, price_position
  ▼
scorer.py compute_relay_score(row, sector_limit_ups)
  │  新增第7维 _volume_ratio_points(volume_ratio, price_position)
  │  与现有6维并列加法贡献
  ▼
candidates.score(0-150,语义不变,只是新增维度贡献)
```

**关键架构约束**:
- `compute_relay_score` 保持纯函数,不引入网络调用(AGENTS.md:外部网络调用必须位于 SQLite 写事务之外)
- mootdx 批量预取在 recap_engine 数据采集阶段完成,结果通过 row dict 传入
- 0-150 接力指数语义不变,量比作为加性维度,不改变刻度
- 盘后与盘中共享 `scorer.py`(AGENTS.md 约束),但本期量比维度仅盘后触发;盘中 `score_intraday` 不传 volume_ratio 字段时,该维度返回0分(降级)

---

### 4. 量比→评分映射

采用**方案A:量比作为独立的第7个加性维度**,与现有6维加法架构一致。知识库乘性矩阵翻译为等效加减分。

#### 4.1 量比基础分(_volume_ratio_points)

| 量比区间 | 含义 | 分值 | 依据 |
|---------|------|:---:|------|
| ≥3.0 | 核弹级放量(E05) | +10 | E05:量比≥3胜率86.7% |
| 2.0 ~ 3.0 | 显著放量 | +5 | 量价联调正向区间 |
| 0.8 ~ 2.0 | 平量(中性) | 0 | 基准区间 |
| <0.8 | 缩量 | -3 | 缩量无接力动能 |

#### 4.2 位置×量价联调加分(_volume_position_bonus)

知识库矩阵的乘性系数翻译为加减分(乘性×1.08 对中等分值约+4~5分,故翻译为+5):

| 价格位置 | 放量(≥2) | 平量(0.8~2) | 缩量(<0.8) |
|---------|:---:|:---:|:---:|
| 低位(<0.33) | +5 | +2 | -2 |
| 中位(0.33~0.66) | +3 | 0 | -3 |
| 高位(>0.66) | -5 | -2 | +3 |

#### 4.3 总量比维度分

```
volume_dimension = _volume_ratio_points(volume_ratio)
                 + _volume_position_bonus(volume_ratio, price_position)
```

加入现有 6 维加总:
```python
score = 50 + (timing + stability + seal + size + turnover + sector + volume_dimension)
```

#### 4.4 降级处理

- `volume_ratio` 或 `price_position` 为 None / NaN / ≤0:`volume_dimension = 0`(退化为原6维),记录 `DataStatus.DEGRADED` + 原因码 `VOLUME_RATIO_MISSING`
- mootdx 请求失败:同上降级,不 fail-closed(避免网络抖动丢失候选)

#### 4.5 边界与 clamp

- 现有 `_noise_caps` 已对 score 做 max(0, min(150, score)) 保护,量比维度不突破此边界
- 量比维度最大贡献 +10(核弹)+5(低位放量)= +15;最小贡献 -3(缩量)-5(高位爆量)= -8,与现有维度量级一致

---

### 5. 数据预取(recap_engine.py)

新增预取函数,在调用 `compute_relay_score` 之前执行:

```python
def prefetch_volume_features(adapter, codes: list[str], today_date: str) -> dict[str, dict]:
    """批量预取候选的量比与价格位置。网络调用,位于写事务之外。

    Returns: {code: {"volume_ratio": float|None, "price_position": float|None}}
    """
```

实现要点:
- 对每个 code 调用 `adapter.client.bars(symbol=code, market=0|1, category=9, start=0, count=25)`(取25日,用后20日算位置,前5日算均量)
- market 判定:code 以 6/9 开头 → market=1(沪);以 0/3 开头 → market=0(深);以 8/4 开头 → market=0(北交所,暂按深市接口试取,失败则降级)
- volume_ratio = bars[-1].volume / mean(bars[-6:-1].volume)(今日 / 前5日均)
- price_position = (bars[-1].close - min(b[-20:].low)) / (max(b[-20:].high) - min(b[-20:].low))
- 单票失败不影响其他:try/except per code,失败则该 code 值为 None
- 全部失败:返回全 None dict,所有候选降级为0分(不阻断流程)

**性能**:假设 Top5 候选,5 次 mootdx 调用,每次 <1s,总 <5s,可接受。
(注:若候选宇宙扩大到全量首板观察样本,需加并发或缓存,本期不涉及)

---

### 6. scorer.py 改动

新增两个纯函数 + 集成到 compute_relay_score:

```python
def _volume_ratio_points(volume_ratio: float) -> int:
    if volume_ratio is None or volume_ratio != volume_ratio or volume_ratio <= 0:
        return 0
    if volume_ratio >= 3.0:
        return 10
    if volume_ratio >= 2.0:
        return 5
    if volume_ratio >= 0.8:
        return 0
    return -3

def _volume_position_bonus(volume_ratio: float, price_position: float) -> int:
    if volume_ratio is None or price_position is None or volume_ratio <= 0:
        return 0
    heavy = volume_ratio >= 2.0
    light = volume_ratio < 0.8
    if price_position < 0.33:
        return 5 if heavy else (-2 if light else 2)
    if price_position > 0.66:
        return -5 if heavy else (3 if light else -2)
    return 3 if heavy else (-3 if light else 0)
```

`compute_relay_score` 改动:
```python
volume_ratio = _safe_float(row.get("volume_ratio"), None)
price_position = _safe_float(row.get("price_position"), None)
volume_points = _volume_ratio_points(volume_ratio) + _volume_position_bonus(volume_ratio, price_position)
# 加入 score 加总 + _noise_caps 参数
```

`_noise_caps` 需新增 volume_points 参数以参与 supportive_factors 计数(量比≥10分视为支撑因子)。

---

### 7. rule_contract.py 与配置改动

#### rule_contract.py
新增原因码:
```python
VOLUME_RATIO_MISSING = "VOLUME_RATIO_MISSING"  # 量比/位置数据缺失,降级不加分
VOLUME_RATIO_NUKE = "VOLUME_RATIO_NUKE"  # E05 量比≥3 核弹信号
```

#### config/rules/dragon_formula_v1.toml
新增 `[volume_ratio]` 段:
```toml
[volume_ratio]
enabled = true                    # 总开关
nuke_threshold = 3.0             # E05 核弹阈值
nuke_points = 10                 # 核弹加分
significant_threshold = 2.0      # 显著放量阈值
significant_points = 5
shrink_threshold = 0.8            # 缩量阈值
shrink_points = -3
position_lookback = 20           # 价格位置回看天数
volume_ma_window = 5             # 量比均量窗口
```

feature_flags 新增:
```toml
enforce_volume_ratio = false     # Phase X:量比维度(默认关闭,回测达标后开启)
```

---

### 8. 测试策略(TDD)

遵循 AGENTS.md"先写失败测试",覆盖边界(低/等/高于阈值):

#### 8.1 scorer 单元测试(tests/test_scorer_volume_ratio.py,新建)

| 测试 | 输入 | 期望 |
|------|------|------|
| 量比≥3 核弹加分 | volume_ratio=3.5, position=0.5 | volume_dimension=10+0=10 |
| 量比=3 边界 | volume_ratio=3.0, position=0.5 | 10(含边界) |
| 量比2-3 显著放量 | volume_ratio=2.5, position=0.5 | 5+0=5 |
| 量比0.8-2 中性 | volume_ratio=1.0, position=0.5 | 0+0=0 |
| 量比<0.8 缩量 | volume_ratio=0.5, position=0.5 | -3+0=-3 |
| 低位放量联调 | volume_ratio=2.5, position=0.2 | 5+5=10 |
| 高位爆量联调 | volume_ratio=3.5, position=0.8 | 10+(-5)=5 |
| 高位缩量(好消息) | volume_ratio=0.5, position=0.8 | -3+3=0 |
| 数据缺失降级 | volume_ratio=None | 0+0=0 |
| NaN 降级 | volume_ratio=NaN | 0 |
| ≤0 降级 | volume_ratio=-1 | 0 |
| 位置缺失降级 | volume_ratio=2.5, position=None | 5+0=5(基础分保留) |

#### 8.2 预取函数测试(tests/test_volume_prefetch.py,新建)
- mock mootdx client.bars 返回固定 DataFrame,验证 volume_ratio 与 price_position 计算
- 单票失败不影响其他(code A 抛异常,code B 正常)
- 全部失败返回全 None dict
- 金样本:用本地确定性数据(不依赖实时网络),符合 AGENTS.md"金样本必须本地、确定"

#### 8.3 集成测试
- recap_engine 端到端:验证 volume_ratio/price_position 字段被填入 row dict 并传入 compute_relay_score

#### 8.4 回归
- 现有 402 个 pytest 全绿(量比字段缺失时退化为原6维,不破坏现有评分)
- 金样本回归 2026-06-19/24/25/26(量比默认关闭 via feature_flag,不改变历史候选分数)

---

### 9. 影响范围

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `src/scorer.py` | 新增2函数+集成 | +~40行,_volume_ratio_points / _volume_position_bonus + compute_relay_score 改动 |
| `src/recap_engine.py` | 新增预取+调用 | +~50行,prefetch_volume_features + 调用点 |
| `src/rule_contract.py` | 新增原因码 | +2行 |
| `config/rules/dragon_formula_v1.toml` | 新增配置段 | +~12行,[volume_ratio] + feature_flag |
| `tests/test_scorer_volume_ratio.py` | 新建 | +~80行,边界测试 |
| `tests/test_volume_prefetch.py` | 新建 | +~60行,预取测试 |

---

### 10. 不纳入范围

- 盘中 score_intraday 量比(需改 ashare.py 补取腾讯 volume + 盘中网络策略,单独设计)
- price_action_monitor 全市场扫描(6/29 已定界为持仓+策略候选,不在本期)
- 量比历史趋势图(SQLite 仅存快照,无时序)
- backtest_volume 量价回测(知识库已有,但属验证工具非生产管道)

---

### 11. 灰度与回滚

- `feature_flags.enforce_volume_ratio` 默认 `false`(shadow 模式):量比计算但**不参与最终 score**,仅记录到候选扩展字段供观察
- 回测验证量比对金样本的影响后,手动开启 `true`
- 回滚:关闭 feature_flag 即可,无需代码回退;或删除新增维度(降级为0分自动退化)

---

### 12. 回滚方案

- 代码级:`git revert` 新增 commit,compute_relay_score 退回6维
- 数据级:无 schema migration(realtime_snapshot 已有字段,candidates 不新增列,量比仅作为运行时计算值不持久化)
- 配置级:关闭 `enforce_volume_ratio` feature_flag
