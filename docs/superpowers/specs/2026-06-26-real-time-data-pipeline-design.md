## 寻龙诀 · 盘中实时数据管道设计方案

- **日期**：2026-06-26
- **版本**：1.0
- **状态**：设计已确认
- **结论**：新增独立 `src/data_pipeline/` asyncio 服务，作为实时数据采集、归一化、持久化与推送的轻量管道层，与现有复盘引擎解耦运行。

---

### 1. 背景与目标

当前寻龙诀复盘引擎（`recap_engine.py`）是纯批量的盘后复盘模型：每天一次同步执行，拉全量数据，算完写 SQLite 退出。无 WebSocket、无 SSE、无轮询、无增量处理。

而 vendored `tickflow-stock-panel` 虽独立实现了 SSE 行情推送和深度轮询，但复盘引擎完全不消费那些实时通道。两个系统通过 SQLite 文件耦合，各管各的。

**痛点：**
1. **盘中数据盲区**：首板炸板、封板资金骤降、板块热度突变等实时信号无法被接力评分捕获，只能等收盘才知道
2. **数据源浪费**：用户 Star 里已有 `mpquant/Ashare`、`jcdreamjc/wudao-ashare`、`itick-org/free-stock-api` 等多个免费实时数据源，未集成
3. **无增量计算**：每次运行都要全量重算，无法做盘中增量评分更新
4. **无事件驱动**：无法在条件满足时（如炸板>2次）主动推送告警

**设计目标：**
1. 新增独立 `src/data_pipeline/` asyncio 服务，实时采集、归一化、持久化
2. 与现有复盘引擎解耦，通过 SQLite WAL 共享数据
3. 对接多个免费实时数据源，不绑定 TickFlow
4. 支持 SSE 推送 + 可扩展告警 Webhook
5. 盘中数据自动沉淀，供后续回测和 ML 训练使用

---

### 2. 整体架构

```
┌──────────────────────────────────────────────────────────┐
│                   复盘引擎（批处理）                         │
│                   recap_engine.py                         │
│                  盘后运行，读/写 recap.db                    │
└──────────────────────┬───────────────────────────────────┘
                       │ 共享 recap.db（WAL 模式）
┌──────────────────────▼───────────────────────────────────┐
│                data-pipeline（实时，asyncio）               │
│                src/data_pipeline/engine.py                │
│                                                           │
│  采集层 → 归一化 → WAL 写入 + SSE 推送 + 告警规则          │
│                                                           │
│  数据源:                                                   │
│    Ashare（新浪/腾讯实时行情）                                │
│    akshare（涨停池轮询）                                     │
│    wudao-ashare（A股实时API）                               │
│    TickFlow（vendor 面板共用，可选）                         │
└──────────────────────────────────────────────────────────┘
                       │ SSE
┌──────────────────────▼───────────────────────────────────┐
│            vendored 面板（tickflow-stock-panel）           │
│            FastAPI + Vue 3，消费 SSE 展示                   │
└──────────────────────────────────────────────────────────┘
```

**设计原则：**
- 管道与引擎通过 SQLite 共享数据，不直接调用对方
- 管道崩溃不影响引擎盘后运行
- 数据源可插拔，新增 Collector 只需实现一个 `async def poll()`
- SQLite 启用 WAL 模式，读写不互斥

---

### 3. 管道内部模块

```
src/data_pipeline/
├── __init__.py
├── collector.py       # 采集层 — 对接多数据源，统一输出 DataFrame
├── normalizer.py      # 归一化 — 字段名/时间戳/代码格式统一
├── merger.py          # 聚合层 — 多源数据合并为单条宽记录
├── engine.py          # 主循环 — asyncio 调度器，生命周期管理
├── store.py           # 持久化 — WAL 写 recap.db + 增量事件日志
├── push.py            # 推送 — SSE 端点 + 飞书 webhook
├── rules.py           # 告警规则定义
└── __main__.py        # CLI 入口：python -m src.data_pipeline
```

#### 3.1 采集层（collector.py）

每个数据源实现一个 Collector（鸭子类型），核心接口：

```python
class Collector(ABC):
    name: str               # 唯一标识
    interval: float          # 轮询间隔（秒）
    retry_delay: float = 5.0 # 失败重试间隔

    @abstractmethod
    async def poll(self) -> pd.DataFrame:
        """拉取一次数据，返回标准化 DataFrame"""
```

**初始 Collector 实现（P0，首次上线）：**

| Collector | 源 | 间隔 | 产出 |
|-----------|-----|------|------|
| `AshareCollector` | mpquant/Ashare 新浪双核 | 3s | 实时行情（价/量/换手率） |
| `ZTPoolCollector` | akshare `stock_zt_pool_em` | 5s | 涨停池变动（封板资金/炸板/封板时间） |
| `NewsCollector` | akshare/新闻 RSS | 30s | 舆情摘要 |

**AshareCollector 动态 watchlist：** 不轮询全市场。维护一个由以下来源组成的动态列表：
- `zt_pool` 每次返回的涨停标的（~30-80 只）
- 昨日的 `candidates`（持仓观察期首板标的）
watchlist 在每个 `ZTPoolCollector` poll 周期刷新一次。

**后续可加（P1/P2，不阻塞上线）：**
- `DepthCollector` — 盘口五档（依赖 vendor TickFlow 订阅）
- `WudaoCollector` — 竞价/资金流向（wudao-ashare）

每个 Collector 内部自动处理：
- 网络超时 → `asyncio.wait_for` + 退避重试
- 限流 → 自适应延长间隔（响应慢则自动降频）
- 空数据 → 跳过本轮，不写空记录

#### 3.2 归一化层（normalizer.py）

```python
def normalize(source: str, df: pd.DataFrame) -> pd.DataFrame:
    """统一字段名、时间戳格式、股票代码格式"""
```

标准化字段映射：

| 源字段 | 归一化字段 |
|--------|-----------|
| `代码`, `code`, `symbol` | `code` |
| `最新价`, `price`, `current` | `price` |
| `涨跌幅`, `change_pct`, `pct_chg` | `change_pct` |
| `换手率%`, `turnover`, `turnover_ratio` | `turnover` |
| `封板资金`, `seal_funds`, `funds` | `seal_funds` |
| `炸板次数`, `blown_count` | `blown_count` |
| `首次封板时间` | `first_seal_time` |

代码标准化：6位代码补齐 → 移除后缀（`.SH`/`.SZ`）→ 统一为 6 位字符串。

#### 3.3 聚合层（merger.py）

将当前 collector 的新数据与磁盘快照中已有数据合并为统一宽记录：

```python
SOURCE_PRIORITY = ["zt_pool", "ashare", "news"]

def merge(source: str, new_df: pd.DataFrame, snapshot: dict) -> pd.DataFrame:
    """
    按 code 合并多源数据。
    - 新数据覆盖对应字段
    - 未覆盖的字段保留 snapshot 中的旧值
    - 字段冲突按 SOURCE_PRIORITY 决定：高优源覆盖低优源
    """
    rows = []
    for _, row in new_df.iterrows():
        code = row["code"]
        base = snapshot.get(code, {})
        base.update(row)
        rows.append(base)
    return pd.DataFrame(rows)
```

#### 3.4 盘中接力指数计算

现有 `recap_engine.py` 的接力指数公式（封板时间权重 + 炸板扣分 + 封板强度加分 + 市值扣分 + 换手率调节 + 板块效应加分）提取为独立函数 `compute_relay_score(row) -> int`，给引擎和管道共用。

管道内调用的 `compute_intraday_score()` 是对这个函数的**轻量封装**——入参换用 `realtime_snapshot` 的瞬时值（`seal_ratio_instant` 替代 `seal_ratio`，`blown_count` 取盘中累计值），产出写入 `score_intraday` 字段。公式与引擎完全一致，仅入参来源不同。

```python
def compute_intraday_score(df: pd.DataFrame) -> pd.DataFrame:
    """给 snapshot 宽表每一行算盘中接力指数"""
    # 先算每条记录的板块涨停数（从 snapshot 中实时计数）
    sector_counts = df[df["seal_funds"].notna()].groupby("sector").size()
    df["sector_limit_ups"] = df["sector"].map(sector_counts).fillna(0)

    df["score_intraday"] = df.apply(compute_relay_score, axis=1).astype(int)
    return df
```

#### 3.5 主循环（engine.py）

**调度策略（APScheduler 进程内）：**

管道始终在线（PM2 `autorestart: true`），APScheduler 管理内部 job 生命周期，对齐 vendor 面板的调度模式：

```python
# APScheduler CronTrigger 调度
scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")

# 工作日 09:15–15:00 执行主轮询循环
scheduler.add_job(
    run_polling_loop,
    CronTrigger(hour="9-14", minute="15-59", day_of_week="mon-fri"),
)

scheduler.add_job(
    run_polling_loop,
    CronTrigger(hour="15", minute="0", day_of_week="mon-fri"),
)

# 15:05 清空 realtime_snapshot（为次日开盘重建做准备）
scheduler.add_job(
    cleanup,
    CronTrigger(hour="15", minute="5", day_of_week="mon-fri"),
)
```

`run_polling_loop` 是主协程，09:15–15:00 持续运行。APScheduler 自带的时区感知 + 交易日检测（CronTrigger 的 `mon-fri` 匹配 A 股常规交易日，遇到调休日通过 `get_trading_days()` 二次校验）。

```python
async def run_polling_loop():
    """主轮询循环，持续运行直到收盘"""
    if not is_trading_day(datetime.now()):
        return

    collectors = [
        AshareCollector(),    # P0 — 3s 实时行情
        ZTPoolCollector(),    # P0 — 5s 涨停池变动
        NewsCollector(),      # P0 — 30s 舆情
    ]
    rules = load_rules()

    while datetime.now().hour < 15 or (datetime.now().hour == 15 and datetime.now().minute == 0):
        for c in collectors:
            if not c.due():
                continue
            try:
                data = await asyncio.wait_for(c.poll(), timeout=c.interval)
            except (TimeoutError, ConnectionError):
                await asyncio.sleep(c.retry_delay)
                continue

            df = normalizer.normalize(c.name, data)

            # 合并多源数据 → 算盘中接力指数 → 写入宽表 → 推送
            merged = merger.merge(c.name, df, store.get_snapshot())
            merged = compute_intraday_score(merged)
            store.write_snapshot(merged)
            push.broadcast(c.name, merged)

            for rule in rules:
                if rule.matches(merged, store.get_snapshot()):
                    push.alert(rule, merged)

        await asyncio.sleep(0.1)  # 100ms 调度粒度
```

**启动入口（`__main__.py`）：**
```python
# python -m src.data_pipeline [--db PATH] [--port PORT]
asyncio.run(run())
```

#### 3.5 持久化层（store.py）

**V1 仅用 1 张快照表（暂不写时序日志）：**

盘中数据的价值在"当前状态"，不在"历史序列"。时序日志（`realtime_log`）等有回测需求时再加。

```sql
-- 当前快照：每只股票的最新完整宽记录（多源聚合后），按 code 主键 upsert
CREATE TABLE IF NOT EXISTS realtime_snapshot (
    code TEXT PRIMARY KEY,           -- 6 位股票代码，唯一
    name TEXT,
    price REAL,
    change_pct REAL,
    turnover REAL,
    seal_funds REAL,
    seal_ratio_instant REAL,        -- 瞬时封板强度（盘中预览用）
    first_seal_time TEXT,
    blown_count INTEGER DEFAULT 0,
    sector TEXT,
    float_mcap REAL,                 -- 流通市值（亿元，zt_pool 提供，日内不变）
    score_intraday INTEGER,          -- 盘中接力指数（0-150，由管道轻量计算）
    source_ts TEXT,                  -- 最新更新时间
    source_tag TEXT                  -- 最后更新源（zt_pool / ashare / news）
);
```

**WAL 模式：** 管道启动时执行 `PRAGMA journal_mode=WAL`，读写不互斥。

**数据保留策略：**
- `realtime_snapshot`：每次开盘重建（检测到交易日 09:15 后清空）
- 清理时机：非交易时段跳过写入，仅保留读取能力

**写入性能：** 默认批量写入（collector 每次 poll 的数据攒批），每批开启独立事务。

#### 3.6 推送层（push.py）

**V1: 面板通过 polling 消费实时快照（不引入 SSE）**

管道照常写 `realtime_snapshot` 表。vendored 面板的 recap API 新增一个只读端点：

```python
# 在 vendor/tickflow-stock-panel/backend/app/api/recap.py 添加
@router.get("/api/recap/intraday-snapshot")
async def get_intraday_snapshot():
    """返回 realtime_snapshot 全表 JSON（面板每 5s 轮询一次）"""
    return read_snapshot()
```

面板 Vue 前端每 5s 用 `setInterval` 调用此端点，直接更新接力看板上的实时指标。复用现有复盘看板的渲染逻辑，数据源从 `candidates` 切换为 `realtime_snapshot` 即可。

**V2（后续性能优化）：SSE 端点（内嵌 aiohttp web server）**

在管道内嵌轻量 aiohttp server，绑定 `127.0.0.1:9300`，供面板后端做 SSE 订阅。此阶段暂不实现。

事件格式：
```json
{
  "type": "zt_pool_update",
  "ts": "2026-06-26T10:30:00",
  "data": [
    {"code": "600123", "name": "某某股", "blown_count": 2, ...}
  ]
}
```

vendored 面板通过 `/api/realtime/stream` 消费事件（使用 `EventSource` 或 `sse_starlette`）。

**Webhook 告警：**

```python
async def push_alert(rule: Rule, df: pd.DataFrame):
    """调用飞书/微信 webhook URL"""
    payload = rule.format(df)
    async with aiohttp.ClientSession() as session:
        await session.post(WEBHOOK_URL, json=payload)
```

Webhook URL 通过环境变量 `ALERT_WEBHOOK_URL` 配置。未设置时静默跳过推送。

#### 3.7 告警规则（rules.py）

```python
@dataclass
class Rule:
    name: str
    condition: Callable[[SnapshotRow], bool]
    message: str

RULES = [
    Rule("blown_alert",
         lambda r: r.blown_count >= 2,
         "⚠️ {name}({code}) 炸板 {blown_count} 次"),

    Rule("seal_drop",
         lambda r: r.seal_drop_pct > 30,
         "🚨 {name}({code}) 封板资金骤降 {seal_drop_pct}%"),

    Rule("sector_heat",
         lambda r: r.sector_limit_ups >= 5,
         "🔥 {sector} 板块涨停 {sector_limit_ups} 家"),
]
```

推送频率控制：同一标的同一规则触发后，5分钟内不重复推送。通过内存 dict 记录 `{rule_name}_{code}: last_ts` 实现。

---

### 4. 数据源接入方案

| 数据源 | 接入方式 | 鉴权 | 优先度 |
|--------|---------|------|--------|
| **mpquant/Ashare** | HTTP GET 新浪/腾讯行情接口 | 无 | P0 — 主力实时行情 |
| **akshare** (`stock_zt_pool_em`) | HTTP GET 东方财富 | 无 | P0 — 涨停池 |
| **wudao-ashare** | HTTP GET 多个细分端点 | 无 | P1 — 补充数据 |
| **TickFlow** (vendor) | HTTP GET vendor 内部 API | 无（本地） | P1 — 深度盘口 |
| **itick free-stock-api** | WebSocket | 注册免费 Key | P2 — WebSocket 低延迟 |
| **akshare 新闻** | HTTP GET 东方财富 | 无 | P2 — 舆情 |

各 Collector 通过环境变量选择启用/禁用及配置间隔：

```bash
# .env
PIPELINE_COLLECTORS=ashare,zt_pool,depth,news
PIPELINE_INTERVAL_ASHARE=3
PIPELINE_INTERVAL_ZTPOOL=5
PIPELINE_INTERVAL_DEPTH=5
PIPELINE_INTERVAL_NEWS=30
```

---

### 5. 与现有系统的关系

| 维度 | 关系说明 |
|------|---------|
| **recap_engine.py** | 不依赖管道。`run_recap()` 启动时读 `realtime_snapshot` 获取当日盘中状态（如有），无则静默忽略 |
| **vendor 面板** | 通过 SSE 消费实时事件做前端展示。面板的 `/api/recap/*` 继续读 `market_recap`/`candidates`，不变 |
| **recap.db** | 新增 `realtime_log` + `realtime_snapshot` 表，不影响已有 4 表契约（ADR 0002） |
| **部署** | 管道作为独立进程运行（`python -m src.data_pipeline`），可与面板同进程或独立 docker container |

**启动方式：**

```bash
# 仅复盘（盘后）
python src/recap_engine.py --date 2026-06-26

# 仅实时管道（盘中）
python -m src.data_pipeline

# 两者都启动（PM2 或 docker-compose 管理两个进程）
```

---

### 6. 部署方式

**初始：PM2 + 手动终端混合**

```javascript
// ecosystem.config.cjs 新增
{
  name: 'data-pipeline',
  script: './.venv/bin/python',
  args: '-m src.data_pipeline',
  autorestart: true,          // 进程崩溃时 PM2 自动拉起
  max_restarts: 5,             // 单日最多重启 5 次（防死循环）
  min_uptime: 10000,           // 运行少于 10s 不计入稳定启动
}
```

可手动开终端 `python -m src.data_pipeline` 调试，稳定后 `pm2 start data-pipeline` 托管。进程始终在线，APScheduler 内部管理调度，非交易时段无 jobs 运行，CPU 占用 ≈ 0。

**后续（Docker Compose）：**

```yaml
# docker-compose.yml 新增
services:
  pipeline:
    build:
      context: .
      dockerfile: Dockerfile  # 复用现有 Dockerfile
    command: python -m src.data_pipeline
    volumes:
      - ./data:/app/data  # 共享 recap.db
    depends_on: [tickflow]  # 可选，面板不在时也独立运行
```

---

### 7. 依赖与安装

新增依赖（均已在用户 Star 中，免费开源）：

```toml
# pyproject.toml 新增
dependencies = [
    "aiohttp",            # 异步 HTTP + SSE
]
```

Ashare 不需要 pip 安装，直接内嵌 `src/data_pipeline/ashare.py`（单文件，MIT 协议，约 200 行）。TickFlow 复用 vendor 的 HTTP 接口，无新增依赖。

---

### 8. 测试策略

- `tests/test_data_pipeline/`
  - `test_collectors.py` — mock HTTP 响应，验证 poll() 输出格式
  - `test_normalizer.py` — 字段映射、代码格式、异常数据
  - `test_store.py` — WAL 写入 + 快照 upsert + 清理
  - `test_rules.py` — 规则匹配逻辑 + 推送频率控制
  - `test_engine.py` — 主循环调度（mock 所有 collector，验证时序正确性）

---

### 9. 不涉及

- **WebSocket 服务端**：不自行实现 WebSocket，推送只用 SSE
- **Redis / 消息队列**：不引入额外中间件，SQLite WAL 足够
- **容器化改造**：管道复用现有 docker-compose 的 Python 环境
- **历史数据回填**：管道只处理启动后的实时数据，不回溯历史
