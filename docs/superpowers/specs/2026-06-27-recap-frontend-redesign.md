# 寻龙诀复盘前端重构
> 将后端 Phase 3–6（市场风险/个股个性/龙虎榜质量/执行计划）在前端可视化呈现

## Motivation

后端已完成 Phase 0–7 全部改造，新增了市况诊断(F18)、个股五维个性、龙虎榜席位质量和执行计划四组数据。但前端 `/recap` 页面仍停留在 Phase 0–2 的面貌——只展示了基础情绪仪表、晋级率趋势、Top5 候选股和手动决策器。

用户同时需要**盘后复盘分析**和**盘中执行决策**两个场景，但当前单页面同时做两件事，两边都不够极致。

## 设计方案

### 核心决策：拆为两个独立入口

| 入口 | URL | 场景 | 心智模型 |
|------|-----|------|----------|
| 寻龙诀复盘 | `/recap/review` | 盘后 15:00+ | 分析者——理解市场，筛选候选，回顾操作 |
| 盘中执行 | `/recap/trade` | 盘中 09:25–10:00 | 交易者——竞价监控，条件单，持仓处理 |

侧边栏导航增加"盘中执行"入口，保持"寻龙诀复盘"为盘后复盘。

### 设计体系约束

所有视觉元素必须遵守现有 TickFlow 前端设计规范：

| 约束项 | 规则 |
|--------|------|
| 色彩 | `bull`=红(#F04438) / `bear`=绿(#12B76A) / `accent`=蓝(#3B82F6) |
| 字号 | 13px 基准，数字一律 `font-mono tabular-nums` |
| 卡片 | `rounded-card border border-border bg-surface`(8px 圆角) |
| Badge | `bg-{color}/10 text-{color}` 模式 |
| 缓动 | `cubic-bezier(0.16, 1, 0.3, 1)` |
| 按钮 | `rounded-btn border border-border px-2.5 py-1.5 text-[11px]` |
| 主题 | 融合 `--brand-glow` CSS 变量适配 helix/pulsar/vanta/aurora 四套品牌色 |

新增可视化元素（gauge、进度条、环形图、分段条）复用现有 progress bar 和 SVG 模式，不引入新图表库。

---

## 页面一：盘中执行驾驶舱 `/recap/trade`

### 布局

```
┌─────────────────────────────────────────────────────┐
│  ⚡ 盘中执行 · 2026-06-25    [刷新] [竞价倒计时]     │
├──────────────────────────────┬──────────────────────┤
│  🎯 竞价监控 · Top5 信号面板  │  🔔 条件买入           │
│                              │  触发价 10.12          │
│  [ 股票A 卡 ]                │  precondition: >=10.12 │
│  [ 股票B 卡 ]  ← 2/3 宽度    ├──────────────────────┤
│  [ 股票C 卡 ]                │  🛡️ 持仓防守           │
│  [ 股票D 卡 ]                │  止损 -4.8% · 止盈阶梯 │
│  [ 股票E 卡 ]                │  1/3 宽度              │
├──────────────────────────────┴──────────────────────┤
│  📊 七档竞价矩阵 · 命中档高亮     │  📋 实时持仓概览    │
│  ┌──┬──────┬────────────────┐    │  2只 · 浮盈+3,240  │
│  │档│操作  │ 说明           │    │  +1.8%             │
│  │▸│减半  │ 开+4%+ 减半锁利 │    │                    │
│  └──┴──────┴────────────────┘    │                    │
└─────────────────────────────────────────────────────┘
```

### 竞价信号卡片（HUD 风格）

每只候选股为一行横向卡片，3 个信息块 + 底部执行信号：

| 区 | 内容 | 视觉形式 |
|----|------|----------|
| 左 · 身份 | 股票名称·代码·行业·流通市值 | 文字 + 标签，顶部状态圆点(绿/黄/红 + 光晕) |
| 中 · 开盘 gauge | 开盘涨幅数值 | 大字 `+3.8%` + 水平渐变进度条(左绿中灰右红) + 游标定位 |
| 右 · 竞价量 | 实际量 vs 目标量 | 数字 + 进度条(超目标绿/不足灰) + "放量达标"状态标签 |
| 底部 | 个性等级 + 龙虎榜 + 条件单状态 | Badge 组合 + 触发文字 |

**交互：** 点击卡片聚焦——右侧条件买入/持仓防守 联动更新选中标的。

### 条件买入面板

- 触发价大字显示（`text-bull font-mono tabular-nums`）
- 前提条件 + 建议方式（来自 execution_plans 表）
- 距当前价差、溢价空间

### 持仓防守面板

- 硬止损：红色进度条 + 圆形游标 + 价格(-4.8%)
- 两档止盈：绿色文字 + 操作说明（减半仓锁利）

### 七档竞价矩阵

水平对照表，7 行对应 7 个开盘区间（≥+8% / +5~8% / +3~5% / +1~3% / ±1% / -1~-3% / ≤-3%）。

当前开盘价命中的行以红色左边框 + 背景高亮。一眼看到"系统认为我该怎么做"。

### 实时持仓概览

紧凑行：持有只数、浮盈总额、总体盈亏%，绿色/红色指示。

---

## 页面二：盘后复盘 `/recap/review`

### 布局

```
┌──────────────┬─────────────────┬──────────────┐
│ 📊 市场情绪   │ 🎯 市况诊断·F18  │ 📈 三大指数   │
│              │                 │              │
│  72           │  晋级率 14.29%   │ 上证+0.72%   │
│  极度活跃     │  ████████░░░░   │ 深证+1.15%   │
│              │  ACTIVE · 调整-15│ 创业板-0.23% │
│  涨停72 跌停3  │                 │ 北向+42.5亿  │
├──────────────┴─────────────────┴──────────────┤
│ 📈 1进2 晋级率趋势 (ECharts 折线，15日)        │
│ + 校准区: 极强/黄金/强势/弱势 分桶胜率         │
├───────────────────────────────────────────────┤
│ 🏆 候选股深度分析                              │
│ [Top1 卡片]                                    │
│  身份+分数环→五维个性→龙虎榜→挡板✓✗→操作建议  │
│ [Top2 卡片]                                    │
│ ...                                            │
├───────────────────────────────────────────────┤
│ 🔬 挡板审计矩阵                                │
│  规则\股票  │ A  │ B  │ C  │ D  │ E  │       │
│  F16 LHB   │ ✓  │ ✗  │ ✓  │ ✓  │ ✓  │       │
│  F17 个性   │ ✓  │ ✓  │ ✗  │ ✓  │ -   │       │
│  F18 市况   │ ✗  │ ✗  │ ✗  │ ✗  │ ✗  │       │
│  F19 过滤   │ ✓  │ ✓  │ ✓  │ ✓  │ -   │       │
├───────────────────────────────────────────────┤
│ 🎯 UZI 智能评审 (折叠)                        │
│ 📓 模拟交易账本 (折叠)                        │
└───────────────────────────────────────────────┘
```

### 顶部市况诊断区

三列网格替代现有的四张独立指数卡片：

| 列 | 内容 | 备注 |
|----|------|------|
| 左 | 情绪仪表盘 + 数值 + 涨停/跌停数 | 保留现有情绪 SVG gauge，压缩高度 |
| 中 | F18 晋级率进度条 + 市况标签 + 风险调整分 | **新增**：进度条带 0%/10%/20%/50% 参考刻度；标签按 FROZEN/CAUTIOUS/NORMAL/ACTIVE/EXTREME 变色 |
| 右 | 三大指数(上证/深证/创业板) + 北向 | 从 4 张大卡片压缩为一行 |

### 候选股深度分析卡片

每只候选股用一张横向卡片聚合全部维度的信息：

| 行 | 左 | 中 | 右 |
|----|-----|-----|------|
| 第1行 | 排名·名称·代码·行业·流通 | 分数环形图 + 预估晋级率 | 复制条件单/模拟买入按钮 |
| 第2行 | 五维个性(activity/reliability/exposiveness/capital/early) 等级 + 5条水平条形 | 龙虎榜质量(GOLD/DEATH/机构净额)分段进度条 | 挡板审计 ✓/✗ 标签 + 拦截原因 |
| 第3行 | 操作建议文字(撑满) | | |

### 挡板审计矩阵

全量规则(F16/F17/F18/F19) × 5 只候选股的 ✓/✗/- 矩阵表。奇数行交错背景色，使用现有表格模式。

### UZI 评审 + 模拟账本

保持现有面板不变，盘后页面底部默认折叠。

---

## API 改动

**不改 endpoint，扩展现有 `GET /api/recap/all` response。**

### Response 新增字段

```typescript
// RecapHistoryItem 扩展
interface MarketRecap {
  // 现有字段...
  market_regime: string        // FROZEN|CAUTIOUS|NORMAL|ACTIVE|EXTREME
  f18_rate: number             // 0-100 百分比
  risk_adjustment: number      // 风险调整分值(负值)
}

interface Candidate {
  // 现有字段...
  personality_grade: string   // SSS|S|A|B|C|D|UNKNOWN
  personality_dims: {         // 五维 0-100
    activity: number
    reliability: number
    explosiveness: number
    capital: number
    early_board: number
  }
  lhb_gold_net: number        // GOLD 席位的净买入(元)
  lhb_death_net: number       // DEATH 席位的净卖出(元)
  lhb_inst_net: number        // 机构席位净买入(元)
  blocks: {
    f16: boolean | null
    f17: boolean | null
    f18: boolean | null
    f19: boolean | null
  }
  buy_plan: {
    trigger_price: number | null
    precondition: string
    action: string
  } | null
  defensive_plans: Array<{
    trigger_type: string      // stop_loss|partial_profit_1|partial_profit_2
    trigger_price: number
    action: string
  }>
  auction_matrix: Array<{
    min_pct: number
    max_pct: number
    action: string
    label: string
  }>
}
```

### 后端改动

`backend/app/api/recap.py` 中 `get_all_recap_data()` 增加：

1. 对 `market_risk` 表的查询（同 date JOIN to market_recap）
2. 对 `execution_plans` 表的查询（同 date+code JOIN to candidates）
3. `StockPersonality` 和 `LhbQuality` 结果——需要先在写端把数据持久化到 `candidates` 表的新列。在 `src/recap_engine.py` 的候选写入路径中追加以下字段：
   - `personality_grade`, `personality_dims` (JSON 字符串), `lhb_gold_net`, `lhb_death_net`, `lhb_inst_net`
   - `block_f16`, `block_f17`, `block_f18`, `block_f19` (BOOLEAN)
   
   ADR 兼容性："引入新列 → 读端 SELECT * 透传，无害"。

### 前端改动

1. `src/lib/api.ts` — 扩展 TypeScript 类型
2. `src/pages/DragonSeekingRecap.tsx` — 保留作为向后兼容重定向或移除
3. 新建 `src/pages/TradeCockpit.tsx` — 盘中执行驾驶舱
4. 新建 `src/pages/RecapReview.tsx` — 盘后复盘
5. `src/router.tsx` — 增加 `/recap/trade` 和 `/recap/review` 路由（或 `/recap` 重定向到 `/recap/review`）
6. `src/components/Layout.tsx` — 侧边栏增加"盘中执行"入口

---

## 测试策略

| 层面 | 测试内容 | 方法 |
|------|----------|------|
| 后端 API | 扩展字段返回正确值 | 在现有 `test_golden_candidates.py` 中校验新字段 |
| 前端组件 | 新 UI 组件渲染 + 交互 | Playwright 或 Vitest + React Testing Library |
| 场景覆盖 | 空数据、null 字段、极端值 | 每种新字段类型至少一个边界测试 |
| 设计合规 | 与现有页面视觉一致性 | 对比现有 card/badge/table 模式 |

---

## 实施顺序

1. 后端 API 扩展（`recap.py` JOIN + 字段注入）
2. TypeScript 类型扩展
3. 盘中执行驾驶舱 (`TradeCockpit.tsx`)
4. 盘后复盘 (`RecapReview.tsx`)
5. 路由 + 导航
6. 设计合规审查 + 边界测试

## 回滚方案

路由设计：

- `/recap/review` → `RecapReview.tsx`（盘后复盘）
- `/recap/trade` → `TradeCockpit.tsx`（盘中执行）
- `/recap` → 自动重定向到 `/recap/review`（非交易日）或 `/recap/trade`（交易日 09:15-15:00）
- 保留 `DragonSeekingRecap.tsx` 作为 `RecapReview.tsx` 的向后兼容 wrapper

如果新页面出现问题，只需把 `/recap` 重定向指回旧组件。
