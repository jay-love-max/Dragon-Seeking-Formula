# 寻龙诀复盘前端重构 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) for syntax tracking.

**Goal:** 将后端 Phase 3–6 数据（市场风险/个股个性/龙虎榜质量/执行计划）在前端可视化呈现，拆分为盘后复盘(`/recap/review`)和盘中执行驾驶舱(`/recap/trade`)两个独立页面。

**Architecture:** 不改后端 endpoint，在现有 `GET /api/recap/all` response 中扩展字段；后端 `recap.py` 加两条 JOIN 查询 `market_risk` 和 `execution_plans` 表；`recap_engine.py` 写入路径追加个性/龙虎榜字段到 `candidates` 表。前端新建两个页面组件，复用现有设计体系(card/badge/progress bar 模式)。

**Tech Stack:** FastAPI/Python(backend), React 18 + TypeScript + TailwindCSS v3 + framer-motion(frontend), ECharts 5(charts), SQLite(data)

**Spec:** `docs/superpowers/specs/2026-06-27-recap-frontend-redesign.md`

---

### Task 1: Backend —— recap_engine 写入个性/龙虎榜字段

**Files:**
- Modify: `src/recap_engine.py`
- Test: `tests/test_golden_candidates.py`

- [ ] **Step 1: 在 candidates 表写入路径追加新字段**

在 `src/recap_engine.py` 中找到写入 `candidates` 表的 SQL INSERT 语句，追加以下列（顺序无关，`SELECT *` 透传）：

```sql
-- 新增列(需先 ALTER TABLE 或 migration 004):
personality_grade TEXT,
personality_dims TEXT,      -- JSON: {"activity":85,"reliability":72,...}
lhb_gold_net REAL,          -- GOLD 席位净买入(元)
lhb_death_net REAL,         -- DEATH 席位净卖出(元)
lhb_inst_net REAL,          -- 机构席位净买入(元)
block_f16 INTEGER,          -- 0=通过 1=拦截 NULL=未判断
block_f17 INTEGER,
block_f18 INTEGER,
block_f19 INTEGER
```

INSERT 之前从 `compute_personality()` 和 `LhbQuality` 结果中提取这些值。

- [ ] **Step 2: 编写 migration 004 追加列**

```sql
-- src/migrations/004_candidate_columns.sql
ALTER TABLE candidates ADD COLUMN personality_grade TEXT;
ALTER TABLE candidates ADD COLUMN personality_dims TEXT;
ALTER TABLE candidates ADD COLUMN lhb_gold_net REAL;
ALTER TABLE candidates ADD COLUMN lhb_death_net REAL;
ALTER TABLE candidates ADD COLUMN lhb_inst_net REAL;
ALTER TABLE candidates ADD COLUMN block_f16 INTEGER;
ALTER TABLE candidates ADD COLUMN block_f17 INTEGER;
ALTER TABLE candidates ADD COLUMN block_f18 INTEGER;
ALTER TABLE candidates ADD COLUMN block_f19 INTEGER;
```

在 `src/db.py` 的 `APPLIED_MIGRATIONS` 列表中注册 `004_candidate_columns`。

- [ ] **Step 3: 运行测试验证 migration 不影响现有数据**

```bash
python3 -m pytest tests/test_db_migrations.py -q --tb=short
python3 -m pytest tests/test_recap_pipeline.py -q --tb=short
```

---

### Task 2: Backend —— recap.py API 扩展

**Files:**
- Modify: `vendor/tickflow-stock-panel/backend/app/api/recap.py`
- Test: `tests/test_golden_candidates.py`

- [ ] **Step 1: 在 market_recap 循环中补充 market_risk 查询**

`get_all_recap_data()` 中 `for row in recap_rows` 循环内，获取 `market_recap` 后追加：

```python
# 补充 market_risk 字段
cursor.execute(
    "SELECT market_regime, f18_rate, risk_adjustment FROM market_risk WHERE date = ?",
    (date_str,)
)
risk_row = cursor.fetchone()
if risk_row:
    recap_dict["market_regime"] = risk_row[0]
    recap_dict["f18_rate"] = risk_row[1]
    recap_dict["risk_adjustment"] = risk_row[2]
else:
    recap_dict["market_regime"] = None
    recap_dict["f18_rate"] = None
    recap_dict["risk_adjustment"] = None
```

- [ ] **Step 2: 在 candidates 循环中补充 execution_plans**

`for c_row in candidate_rows` 循环内 `c_dict = dict(zip(candidate_cols, c_row))` 之后追加：

```python
# 补充 execution_plans
cursor.execute(
    "SELECT action, trigger_price, precondition, trigger_type FROM execution_plans "
    "WHERE date = ? AND code = ?",
    (date_str, c_dict["code"])
)
plan_rows = cursor.fetchall()
buy_plans = [dict(zip([desc[0] for desc in cursor.description], r)) for r in plan_rows]
c_dict["buy_plan"] = next((p for p in buy_plans if p["action"] == "CONDITIONAL_BUY"), None)
c_dict["defensive_plans"] = [p for p in buy_plans if p["action"] in ("EXIT", "HOLD")]
```

如果 `buy_plan` 和 `defensive_plans` 字段指向的列在 `candidates` 表已有（personality 等），它们会被 `SELECT *` 自动包含，不需要额外处理。

- [ ] **Step 3: 运行测试确认 API 扩展不破坏现有响应**

```bash
python3 -m pytest tests/test_golden_candidates.py -q --tb=short
```

---

### Task 3: Frontend —— API 类型扩展

**Files:**
- Modify: `vendor/tickflow-stock-panel/frontend/src/lib/api.ts`

- [ ] **Step 1: 扩展 MarketRecap 接口**

```typescript
interface MarketRecap {
  // ... 现有字段
  market_regime: string | null     // FROZEN | CAUTIOUS | NORMAL | ACTIVE | EXTREME
  f18_rate: number | null          // 0-100
  risk_adjustment: number | null   // 负值
}
```

- [ ] **Step 2: 扩展 Candidate 接口**

```typescript
interface Candidate {
  // ... 现有字段
  personality_grade: string | null    // SSS | S | A | B | C | D | UNKNOWN
  personality_dims: {
    activity: number
    reliability: number
    explosiveness: number
    capital: number
    early_board: number
  } | null
  lhb_gold_net: number | null
  lhb_death_net: number | null
  lhb_inst_net: number | null
  block_f16: boolean | null
  block_f17: boolean | null
  block_f18: boolean | null
  block_f19: boolean | null
  buy_plan: {
    action: string
    trigger_price: number | null
    precondition: string
  } | null
  defensive_plans: Array<{
    action: string
    trigger_price: number
    trigger_type: string
  }>
}
```

---

### Task 4: Frontend —— SignalCard HUD 组件

**Files:**
- Create: `vendor/tickflow-stock-panel/frontend/src/components/SignalCard.tsx`

*竞价信号卡片*：单只候选股的实时状态卡片，用于盘中驾驶舱。

Props:
```typescript
interface SignalCardProps {
  candidate: Candidate
  liveData?: { price: number; change: number; turnover: number }
  isSelected: boolean
  onSelect: () => void
}
```

渲染 3 个信息块：
1. **左·身份**：名称 + 代码 + 行业 + 流通市值 + 状态圆点(绿/黄/红)
2. **中·开盘 gauge**：涨幅大字 + 水平渐变进度条 + 游标定位
3. **右·竞价量**：实际量 vs 目标量 + 进度条 + 放量达标标签

底部：个性等级 badge + 龙虎榜标签 + 条件触发状态。

视觉规范：
- 卡片 `rounded-card border border-border bg-surface p-4 cursor-pointer transition-colors duration-150 ease-smooth`
- 选中态 `border-accent/50 bg-accent/[0.03]`
- 数字 `font-mono tabular-nums`
- badge `bg-{color}/10 text-{color} border-{color}/20`

---

### Task 5: Frontend —— AuctionMatrix 组件

**Files:**
- Create: `vendor/tickflow-stock-panel/frontend/src/components/AuctionMatrix.tsx`

*七档竞价矩阵*：7 行水平对照表，选中档高亮。

Props:
```typescript
interface AuctionMatrixProps {
  matrix: Array<{ min_pct: number; max_pct: number; action: string; label: string }>
  currentOpenPct?: number   // 当前实际开盘涨幅(盘中模式)
  previousClose: number
}
```

渲染 7 行，每行：开盘区间 → 操作 → 说明。命中行：`border-l-2 border-l-bull bg-bull/[0.03]`

---

### Task 6: Frontend —— TradeCockpit 页面

**Files:**
- Create: `vendor/tickflow-stock-panel/frontend/src/pages/TradeCockpit.tsx`

*盘中执行驾驶舱*：三栏弹性网格布局。

数据源：使用 `api.recapAll()`，取 latest history item（今日）。

结构：
- Header: 标题 + 日期 + 刷新按钮 + 竞价倒计时(自动计算)
- 左区(2/3): `SignalCard` × 5 (可滚动列表)
- 右上: 条件买入面板 + 持仓防守面板（联动左侧选中项）
- 底左: `AuctionMatrix`
- 底右: 实时持仓概览

交互：
- 点击信号卡片 → 聚焦选中 → 右侧面板联动
- 刷新按钮 → 触发 Tencent 实时报价脚本（复用现有 `fetchLiveQuotes` 逻辑）

---

### Task 7: Frontend —— CandidateDeepCard 组件

**Files:**
- Create: `vendor/tickflow-stock-panel/frontend/src/components/CandidateDeepCard.tsx`

*候选股深度分析卡*：用于盘后复盘，聚合全维度信息。

Props:
```typescript
interface CandidateDeepCardProps {
  candidate: Candidate
  rank: number
}
```

渲染 3 行：
1. 身份行：排名 + 名称代码 + 行业流通 + 分数环形图 + 预估晋级率 + 模拟买入
2. 详情行：五维个性条形组(5条水平 progress bar) + 龙虎榜分段条(GOLD红/DEATH绿/机构蓝) + 挡板标签(✓/✗)
3. 操作建议行 + 复制条件单按钮

---

### Task 8: Frontend —— RecapReview 页面

**Files:**
- Create: `vendor/tickflow-stock-panel/frontend/src/pages/RecapReview.tsx`

*盘后复盘*：替代现有 `DragonSeekingRecap.tsx`。

数据源：`api.recapAll()`。

布局（同 spec 设计）：
1. 顶部三列：情绪仪表 + 市况诊断(F18) + 指数精简
2. 晋级率趋势 ECharts 折线 + 校准区
3. `CandidateDeepCard` × 5
4. 挡板审计矩阵
5. UZI 评审（折叠，展开后内容同现有）
6. 模拟账本（折叠，展开后内容同现有）

关键：新增的 F18 晋级率进度条、市况标签、五维个性、龙虎榜、挡板审计矩阵——这些是原有页面没有的内容。

---

### Task 9: Frontend —— 路由 + 导航 + 清理

**Files:**
- Modify: `vendor/tickflow-stock-panel/frontend/src/router.tsx`
- Modify: `vendor/tickflow-stock-panel/frontend/src/components/Layout.tsx`

- [ ] **Step 1: router.tsx 添加新路由**

```typescript
// 新增
import { TradeCockpit } from '@/pages/TradeCockpit'
import { RecapReview } from '@/pages/RecapReview'

// 路由表追加:
{ path: '/recap/trade', element: <TradeCockpit /> },
{ path: '/recap/review', element: <RecapReview /> },
// 保留 /recap 兼容
{ path: '/recap', element: <RecapReview /> },
```

- [ ] **Step 2: Layout.tsx 侧边栏增加盘中执行入口**

```typescript
// nav 数组中追加:
{ path: '/recap/trade', label: '盘中执行', icon: Zap },
// 寻龙诀复盘指向 /recap/review
{ path: '/recap/review', label: '寻龙诀复盘', icon: Sparkles },
```

---

### Task 10: 验证

- [ ] **Step 1: 后端测试**

```bash
cd /Users/angojay/20_Projects/Dragon-Seeking-Formula
python3 -m pytest tests/ -q --tb=short
python3 -m ruff check src tests
```

- [ ] **Step 2: 前端构建检查**

```bash
cd vendor/tickflow-stock-panel/frontend
pnpm build 2>&1 | tail -20
```

- [ ] **Step 3: 手动验证 API 响应**

```bash
curl -s http://localhost:3018/api/recap/all | python3 -c "import json,sys; d=json.load(sys.stdin); h=d['history'][0]; print('market_regime:', h['market'].get('market_regime')); print('candidate blocks:', h['candidates'][0].get('block_f16') if h['candidates'] else 'N/A'); print('buy_plan:', h['candidates'][0].get('buy_plan') if h['candidates'] else 'N/A')"
```
