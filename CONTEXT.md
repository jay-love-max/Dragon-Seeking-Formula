# 寻龙诀 1进2 连板接力分析

用于对 A 股首板（首次涨停）股票进行次日“1进2”连板接力潜力的量化打分、机器学习胜率预估与智能审计。

## 领域语言 (Language)

**ROE (净资产收益率)**:
指标的最新一期已披露定期报告（一季报、半年报、三季报或年报）中，未扣除非经常性损益的加权平均净资产收益率。
_Avoid_: 滚动 TTM ROE、单季度平均 ROE

**EPS (每股收益)**:
指标的最新一期已披露定期报告（一季报、半年报、三季报或年报）中的基本每股收益。
_Avoid_: 扣非每股收益、单季度每股收益

**行业板块 (Sector)**:
指互斥且唯一的主线所属行业分类，用于板块热度计数，判断赛道内个股的资金共振接力强度。
_Avoid_: 概念题材、复合板块

**题材概念 (Concept)**:
指跨行业的一对多概念归因分类，用作个股复盘的逻辑标签，不参与热度评分计数。
_Avoid_: 行业板块、细分行业

**财务地雷 (Burry Traps)**:
指可能导致标的暴雷并被排雷席位一票否决的四项红线指标集合，包括 ST 标记、负债率 >= 75%、商誉占比 >= 30%、应收账款占比 >= 50%。
_Avoid_: 财务退市、违约风险、亏损股

**首次封板时间 (First Seal Time)**:
股票当日第一次封死涨停的时刻。若时间为 09:25:00 则定义为 **一字板 (One-Word Board)**。
_Avoid_: 涨停时间、冲板时间

**炸板次数 (Blown Boards)**:
分时图上股价封板后，封单资金被砸开导致股价跌破涨停价的累计次数。
_Avoid_: 开板次数、开板、分时烂板

**封板强度 (Seal Strength)**:
收盘时涨停板上的买单排队封板资金占个股流通市值的比率。
在交易时段由实时管道记录的瞬时值为 **瞬时封板强度 (Instant Seal Strength)**，用于盘中接力指数预览，标注为非正式值。
_Avoid_: 封单比率、排单占比

**流通市值 (Float Market Cap)**:
股票二级市场流通股本对应的市值（以亿为单位）。

**换手率 (Turnover Rate)**:
当日成交股数占流通总股数的百分比。

**行业涨停数 (Sector Limit-ups)**:
当日同行业板块内（Sector 维度）封死涨停板的标的总家数。

**席位表决意见 (Seat Votes)**:
巴菲特席位和赵老哥席位对个股的接力倾向判定，仅允许输出 **“多头”**、**“空头”** 或 **“观望”** 三个值。
_Avoid_: 看多、看空、中立、看平、积极、消极

**排雷评级 (Risk Ratings)**:
大空头排雷席位对个股潜在财务风险的综合判定。当前实现按
《2026-06-26-统一数据源与内置 UZI 大模型审计设计方案》采用
三档枚举：**"安全"**、**"危险"**、**"极度危险"**。
早期四档方案（含"关注"、"高危"）已弃用，仅作为历史设计参考。
_Avoid_: 低风险、中风险、高风险、健康、违约

## 关系 (Relationships)

* 一个 **巴菲特价值席位** 的 **席位表决意见** 依赖于标的股票的 **ROE** 和 **EPS**。
* 一个 **赵老哥游资席位** 的 **席位表决意见** 依赖于标的股票的 **首次封板时间**、**炸板次数**、**封板强度** 和 **行业涨停数**。
* 一个 **大空头排雷席位** 的 **排雷评级** 依赖于标的股票是否触及 **财务地雷 (Burry Traps)**。
* 标的股票的 **接力指数 (Relay Score)** 是由 **首次封板时间**、**炸板次数**、**封板强度**、**流通市值**、**换手率** 与 **行业涨停数** 共同决定的得分。盘后 `run_recap()` 计算的为**正式接力指数**，覆盖当日盘中值。
* 一个 **盘中接力指数 (Intraday Relay Score)** 在交易时段由实时数据管道基于瞬时快照轻量计算，标注为"盘中预览"（蓝色标记）。盘后被正式接力指数替换。

## 盘中实时管道 (Intraday Pipeline)

线上运行的 `src/data_pipeline/` 独立 asyncio 服务负责盘中数据采集、聚合与推送，具体见 `docs/superpowers/specs/2026-06-26-real-time-data-pipeline-design.md`。

## 示例对话 (Example Dialogue)

> **开发者:** “当本地 Parquet 财务数据未同步时，我们如何获取标的股票的 **ROE** 与 **EPS**？”
> **领域专家:** “我们应自动退回到网络接口（如 `mootdx`）拉取最新季报的财务快照数据，确保决策依据不因本地缓存失效而中断。”

---

## 工程初始化

本仓库的复盘引擎（`src/recap_engine.py`）在运行时依赖同目录下 vendored 的 `tickflow-stock-panel` 面板（读取其同步的本地财务 Parquet 与共享 AI 配置）。该面板以独立 git 仓库形式置于 `vendor/tickflow-stock-panel/`，**不纳入本仓库版本控制**，而是通过版本锁文件 `vendor/VERSION` 记录其 commit hash。

**首次 clone 本仓库后必须执行：**

> ⚠️ 首次 clone 本仓库后，必须先运行 `bash scripts/restore-vendor.sh` 恢复 `vendor/tickflow-stock-panel`，再执行 Docker 构建或 `scripts/dev.sh`。

```bash
bash scripts/restore-vendor.sh    # 克隆并 checkout 到 vendor/VERSION 锁定的版本
bash scripts/check-vendor.sh      # （可选）校验 vendor 是否在锁定版本
```

### 升级 tickflow-stock-panel 版本流程

1. 在本地开发环境中（仅一次）：
   ```bash
   cd vendor/tickflow-stock-panel
   git fetch origin
   git checkout <new-commit-or-tag>
   ```

2. 将新的 commit hash 写入 `vendor/VERSION`（仅一行 40 位 SHA）并提交：
   ```bash
   git -C vendor/tickflow-stock-panel rev-parse HEAD > vendor/VERSION
   git commit -am "chore: bump tickflow-stock-panel to <sha>"
   ```

3. 其他开发者或 CI 通过：
   ```bash
   bash scripts/restore-vendor.sh
   bash scripts/check-vendor.sh
   ```
   将本地 vendor 恢复到锁定版本。

**每日运行复盘：**

```bash
bash run_daily.sh                 # 等价于 python3 src/recap_engine.py [--date YYYY-MM-DD | --backfill N]
```

**生产部署：**

```bash
docker compose up --build -d
```

Docker Compose 是唯一的生产拓扑：`pipeline` 负责盘中采集，`recap-scheduler`
在工作日 15:10 运行盘后复盘，`tickflow` 提供面板。三者通过根目录
`data/recap.db` 共享同一个 SQLite 数据库。`ecosystem.config.cjs` 仅作为本地
PM2 备用入口，不再包含机器相关绝对路径。

运行依赖声明见根目录 `pyproject.toml`（`pip install -e ".[dev]"` 安装运行与开发依赖），环境变量样例见 `.env.example`。
