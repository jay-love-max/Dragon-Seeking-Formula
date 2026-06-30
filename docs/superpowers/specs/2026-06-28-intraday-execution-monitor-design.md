## 晋级监控 · 盘中执行监控设计方案

- **日期**：2026-06-28
- **版本**：1.0
- **状态**：设计已确认
- **结论**：新增 `GET /api/recap/intraday-execution` 端点，将 `src/data_pipeline/` 的实时快照接入 `TradeCockpit` 前端页面，实现前一日 Top5 候选在今日盘中的晋级执行监控。

---

### 1. 背景与问题

当前 `TradeCockpit`（路由 /recap/trade）标签写着"盘中执行"，实际消费的是 `api.recapAll()` 接口，展示的是盘后复盘数据（`candidates` 表）。没有实时行情、没有 `score_intraday` 预览、竞价矩阵拿不到当前涨跌幅。

`src/data_pipeline/` 已完整实现实时数据管道（采集→归一化→合并→存储→告警），每 3 秒写入 `realtime_snapshot` 表（含 `price`、`change_pct`、`score_intraday`、`seal_funds` 等字段），但前端完全未接入这些数据。

**问题：**
1. TradeCockpit 展示的是盘后静态数据，不是盘中实时执行监控
2. `score_intraday` 前端完全没有展示
3. 持仓模拟器/条件买入/防守计划是无券商接入的无效占位
4. 页面语义与功能不符

**本设计范围**：打通 `realtime_snapshot` → 前端通路，改造 TradeCockpit 为真正的晋级执行监控页面。

---

### 2. 整体架构

```
                     src/data_pipeline/
                     store.py 写入 realtime_snapshot (3s 循环)
                              │
                              ▼
                         recap.db (WAL)
                              │
                              ▼
              vendor/backend/app/api/recap.py
              GET /api/recap/intraday-execution
              SQL: candidates (最新 Top5) LEFT JOIN realtime_snapshot
                              │
                              ▼
              vendor/frontend/src/pages/TradeCockpit.tsx
              调用 api.intradayExecution()
              展示实时晋级状态
                              │
                              ▼
              SSE quotes_updated → invalidate 'recap-execution'
              自动刷新
```

**关键架构约束：**
- 盘后和盘中共享同一套规则函数（已有 `scorer.py`，无变动）
- SQLite WAL 是唯一的集成点（无 IPC/网络，沿用 ADR-0002 契约）
- 前端轮询由 SSE 驱动（已有 `useQuoteStream` hook，仅需新增 key prefix）
- 非交易日/非交易时段 → `realtime_snapshot` 无数据 → 前端显示 `—`

---

### 3. 后端：新 API 端点

**文件**：`vendor/tickflow-stock-panel/backend/app/api/recap.py`

新增：

```python
@router.get("/intraday-execution")
def get_intraday_execution():
```

**SQL 逻辑：**

```sql
SELECT
  c.*,
  rs.price,
  rs.change_pct,
  rs.score_intraday,
  rs.seal_funds,
  rs.ts AS snapshot_ts
FROM (
  SELECT * FROM candidates
  WHERE date = (SELECT max(date) FROM candidates)
  ORDER BY score DESC
  LIMIT 5
) c
LEFT JOIN realtime_snapshot rs ON c.code = rs.code
```

另从 `realtime_snapshot` 聚合市场脉搏：

```sql
SELECT
  SUM(CASE WHEN change_pct >= 9.8 THEN 1 ELSE 0 END) AS limit_up,
  SUM(CASE WHEN blown_count > 0 THEN 1 ELSE 0 END) AS broken,
  SUM(CASE WHEN change_pct <= -9.8 THEN 1 ELSE 0 END) AS limit_down
FROM realtime_snapshot
```

`promoted` (已晋级二板数) 由前端在 Top5 中统计 `change_pct >= 9.8` 的个数。

**响应结构：**

```json
{
  "date": "2026-06-19",
  "candidates": [
    {
      "code": "000001",
      "name": "平安银行",
      "score": 118,
      "score_intraday": 135,
      "price": 15.91,
      "change_pct": 6.5,
      "seal_funds": 120000000.0,
      "first_seal_time": "093500",
      "blown_count": 0,
      "sector": "银行",
      "concept": null,
      "playbook": "【强势突围潜力股】...",
      "buy_plan": null,
      "defensive_plans": []
    }
  ],
  "snapshot_ts": "2026-06-26T09:35:00",
  "market_brief": {
    "limit_up": 32,
    "broken": 8,
    "limit_down": 2,
    "promoted": 2,
    "promoted_total": 5
  }
}
```

**字段说明：**
- `score_intraday` / `price` / `change_pct` / `seal_funds` 来自 `realtime_snapshot`，盘中无数据时为 `null`
- `snapshot_ts` 为最新一条快照的时间戳，盘后为 `null`
- 已有盘后字段（`score`、`first_seal_time`、`playbook` 等）保持不变
- 不删除 `buy_plan`/`defensive_plans`，保持向后兼容（前端不再渲染）

**错误处理：**
- `candidates` 表无数据 → 返回 `{"date": null, "candidates": [], "snapshot_ts": null}`
- `realtime_snapshot` 表无数据 → `score_intraday`/`price` 等字段为 `null`
- SQLite 连接失败 → 500 异常（与现有端点一致）

---

### 4. 前端：API 类型与客户端

**文件**：`vendor/tickflow-stock-panel/frontend/src/lib/api.ts`

新增类型：

```typescript
export interface IntradayExecutionCandidate extends Candidate {
  score_intraday: number | null;
  price: number | null;
  change_pct: number | null;
  seal_funds: number | null;
}

export interface IntradayExecutionResponse {
  date: string | null;
  candidates: IntradayExecutionCandidate[];
  snapshot_ts: string | null;
}
```

新增 API 方法：

```typescript
intradayExecution: () =>
  request<IntradayExecutionResponse>('/api/recap/intraday-execution'),
```

---

### 5. 前端：TradeCockpit 改版

**文件**：`vendor/tickflow-stock-panel/frontend/src/pages/TradeCockpit.tsx`

#### 5.1 页面重命名

页面标题从"盘中执行"改为"晋级监控"。

#### 5.2 数据源切换

```diff
- queryKey: ['recapAllData'],
- queryFn: () => api.recapAll(),
+ queryKey: ['recap-execution'],
+ queryFn: () => api.intradayExecution(),
```

#### 5.3 布局变更

**去除（无券商接入的无效占位）：**
- `PositionOverview` 组件（持仓概览）
- `CondBuyPanel` 组件（条件买入）
- `DefensivePanel` 组件（防守计划）

**保持：**
- `SignalCard` 组件（Top5 候选卡）— 需增强实时数据展示
- `AuctionMatrix` 组件（竞价决策矩阵）— 传入实时 `currentChangePct`

**新增：**
- 页面顶部的交易时段指示器（盘前/竞价/早盘/午盘/收盘）
- 每个候选卡的实时行情行（涨跌幅、score_intraday 对比盘后 score）
- 右侧选中候选详情面板（评分对比、封单进度条、龙虎榜可视化、操作建议）
- 底部市场脉搏小面板（盘中涨停/炸板/跌停计数）

#### 5.4 时段指示器逻辑

```typescript
function getTradingSession(): 'pre' | 'auction' | 'morning' | 'afternoon' | 'closed' {
  const now = new Date()
  const h = now.getHours(), m = now.getMinutes()
  const t = h * 100 + m
  if (t < 915) return 'pre'
  if (t < 925) return 'auction'
  if (t < 1130) return 'morning'
  if (t < 1300) return 'break'
  if (t < 1500) return 'afternoon'
  return 'closed'
}
```

#### 5.5 评分对比可视化

每个候选卡展示两条信息：
- 盘后评分 `score`（灰色，基准值）
- 盘中评分 `score_intraday`（蓝色，预览值）
- 差异指示器：`score_intraday - score`（正差=蓝色 ↑，负差=红色 ↓）
- 评分进度条宽度基于 `score/150`

#### 5.6 竞价矩阵绑定实时数据

```tsx
const selectedCandidate = candidates.find(c => c.code === selectedCode)
<AuctionMatrix
  tiers={DEFAULT_AUCTION_TIERS}
  currentChangePct={selectedCandidate?.change_pct}
/>
```

#### 5.7 状态降级规则

| 场景 | 显示 |
|------|------|
| `price` 为 null | `—` |
| `change_pct` 为 null | `—` |
| `score_intraday` 为 null | 不显示盘中评分行 |
| `seal_funds` 为 null | 不显示封单行 |
| 所有实时字段为 null（盘前）| 候选卡显示灰色静态数据，时段指示器标注"盘前" |

---

### 6. SSE 自动刷新

**文件**：`vendor/tickflow-stock-panel/frontend/src/lib/queryKeys.ts`

```diff
export const SSE_INVALIDATE_PREFIXES = [
  'watchlist',
  'quote-status',
  'index-quotes',
  'overview-market',
  'limit-ladder',
  'screener-cached',
+ 'recap-execution',
] as const
```

`GET /api/intraday/stream` 的 `quotes_updated` 事件每 3 秒触发时，`useQuoteStream` 自动 invalidate `recap-execution` 前缀，`TradeCockpit` 的 `useQuery` 自动重取。

---

### 7. 配套改动

#### 测试

**文件**：`tests/test_intraday_execution.py`

- 测试端点正常返回 Top5 + 实时数据
- 测试 `candidates` 表为空时返回空列表
- 测试 `realtime_snapshot` 表为空时实时字段为 null
- 测试 SQLite 连接失败时返回 500

---

### 8. 影响范围

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `recap.py` | 新增端点 | +40 行，含 SQL 查询和 JSON 序列化 |
| `TradeCockpit.tsx` | 重写 | 保持 ~200 行，去掉占位组件，增强实时展示 |
| `api.ts` | 新增类型+方法 | +30 行 |
| `queryKeys.ts` | 修改常量 | +1 行 |
| `test_intraday_execution.py` | 新建 | +60 行 |

---

### 9. 未纳入范围

- 盘中全量首板实时监控（当前聚焦 Top5 执行监控）
- 券商对接/自动下单（系统不连接券商）
- score_intraday 历史趋势图（SQLite 仅存快照，无时序日志）
- 飞书/企微 webhook 通用化（当前 push.py 仅钉钉格式）

---

### 10. 回滚方案

回滚只需移除新增端点并恢复 TradeCockpit 历史版本。新增的 `realtime_snapshot` 表和数据不受影响，`score_intraday DEFAULT 0` 变更向下兼容。
