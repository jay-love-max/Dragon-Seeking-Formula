# 晋级监控 · 盘中执行监控 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `GET /api/recap/intraday-execution` endpoint and rewrite TradeCockpit to show real-time Top5 execution monitoring.

**Architecture:** New endpoint in existing `recap.py` runs SQL joining `candidates` (latest Top5) with `realtime_snapshot` (live quotes/score). Frontend switches from `recapAll()` to `intradayExecution()`, removes broker-placeholder components, adds session-aware live data display. SSE auto-refreshes via existing `useQuoteStream`.

**Tech Stack:** Python FastAPI, SQLite, TypeScript React, Tailwind CSS, TanStack React Query

**Constraints:** Must work on a feature branch, not main. All changes in vendor/tickflow-stock-panel/ backend + frontend, plus tests.

---

### Task 0: Create feature branch

- [ ] **Step 1: Create branch from main**

```bash
git checkout main
git pull
git checkout -b feature/intraday-execution-monitor
```

---

### Task 1: Backend endpoint — `GET /api/recap/intraday-execution`

**Files:**
- Modify: `vendor/tickflow-stock-panel/backend/app/api/recap.py`
- Test: `tests/test_intraday_execution.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_intraday_execution.py`:

```python
"""Tests for GET /api/recap/intraday-execution endpoint."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


@pytest.fixture
def mock_db_path(tmp_path: Path) -> Path:
    """Create a real SQLite DB with candidates + realtime_snapshot tables."""
    db_path = tmp_path / "recap.db"
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE candidates (
            date TEXT, code TEXT, name TEXT, score INTEGER, price REAL,
            first_seal_time TEXT, blown_count INTEGER, sector TEXT,
            concept TEXT, playbook TEXT, seal_funds REAL,
            turnover REAL, float_mcap REAL, personality_grade TEXT,
            personality_dims TEXT, lhb_gold_net REAL, lhb_death_net REAL,
            lhb_inst_net REAL, block_f16 INTEGER, block_f17 INTEGER,
            block_f18 INTEGER, block_f19 INTEGER, pred_prob REAL,
            PRIMARY KEY (date, code)
        )
    """)
    conn.execute("""
        CREATE TABLE realtime_snapshot (
            code TEXT PRIMARY KEY, name TEXT, price REAL, change_pct REAL,
            turnover REAL, seal_funds REAL, seal_ratio_instant REAL,
            first_seal_time TEXT, blown_count INTEGER DEFAULT 0,
            consecutive_boards INTEGER DEFAULT 0, sector TEXT,
            float_mcap REAL, score_intraday INTEGER, ts TEXT
        )
    """)
    conn.execute("""
        INSERT INTO candidates (date, code, name, score, price, first_seal_time, blown_count, sector, playbook)
        VALUES ('2026-06-26', '000001', '平安银行', 118, 14.93, '093500', 0, '银行', '测试playbook')
    """)
    conn.execute("""
        INSERT INTO candidates (date, code, name, score, price, first_seal_time, blown_count, sector, playbook)
        VALUES ('2026-06-26', '600000', '浦发银行', 125, 18.50, '092500', 0, '银行', '测试playbook2')
    """)
    conn.execute("""
        INSERT INTO realtime_snapshot (code, name, price, change_pct, seal_funds, score_intraday, ts)
        VALUES ('000001', '平安银行', 15.91, 6.5, 120000000.0, 135, '2026-06-26T09:35:00')
    """)
    conn.execute("""
        INSERT INTO realtime_snapshot (code, name, price, change_pct, seal_funds, score_intraday, ts)
        VALUES ('600000', '浦发银行', 20.35, 10.0, 80000000.0, 128, '2026-06-26T09:35:00')
    """)
    conn.commit()
    conn.close()
    return db_path


def test_intraday_execution_returns_top5_with_realtime(monkeypatch, mock_db_path: Path):
    """Happy path: endpoint returns Top5 candidates enriched with realtime data."""
    from app.api.recap import get_recap_db_path
    monkeypatch.setattr("app.api.recap.get_recap_db_path", lambda: mock_db_path)

    response = client.get("/api/recap/intraday-execution")
    assert response.status_code == 200
    data = response.json()
    assert data["date"] == "2026-06-26"
    assert len(data["candidates"]) == 2  # only 2 in fixture
    # Candidate 000001 should have realtime data merged
    c1 = next(c for c in data["candidates"] if c["code"] == "000001")
    assert c1["score_intraday"] == 135
    assert c1["change_pct"] == 6.5
    assert c1["price"] == 15.91
    assert c1["seal_funds"] == 120000000.0
    assert c1["score"] == 118  # from candidates table
    assert c1["playbook"] == "测试playbook"
    # market brief should be present
    assert "market_brief" in data
    assert data["snapshot_ts"] == "2026-06-26T09:35:00"


def test_intraday_execution_empty_candidates(monkeypatch, tmp_path: Path):
    """When candidates table is empty, return empty list."""
    db_path = tmp_path / "recap.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE candidates (date TEXT, code TEXT, score INTEGER, PRIMARY KEY (date, code))")
    conn.execute("CREATE TABLE realtime_snapshot (code TEXT PRIMARY KEY)")
    conn.commit()
    conn.close()

    monkeypatch.setattr("app.api.recap.get_recap_db_path", lambda: db_path)
    response = client.get("/api/recap/intraday-execution")
    assert response.status_code == 200
    data = response.json()
    assert data["date"] is None
    assert data["candidates"] == []


def test_intraday_execution_no_realtime(monkeypatch, mock_db_path: Path):
    """When realtime_snapshot has no matching rows, realtime fields are null."""
    conn = sqlite3.connect(mock_db_path)
    conn.execute("DELETE FROM realtime_snapshot")
    conn.commit()
    conn.close()

    monkeypatch.setattr("app.api.recap.get_recap_db_path", lambda: mock_db_path)
    response = client.get("/api/recap/intraday-execution")
    assert response.status_code == 200
    data = response.json()
    c1 = next(c for c in data["candidates"] if c["code"] == "000001")
    assert c1["score_intraday"] is None
    assert c1["change_pct"] is None
    assert data["snapshot_ts"] is None
    # Non-null fields should still be present
    assert c1["score"] == 118
    assert c1["playbook"] == "测试playbook"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python3 -m pytest tests/test_intraday_execution.py -v
```

Expected: FAIL with `ModuleNotFoundError` or import errors (endpoint doesn't exist yet).

- [ ] **Step 3: Implement the endpoint**

Add to `vendor/tickflow-stock-panel/backend/app/api/recap.py`, before the `@router.post("/run")` line:

```python
@router.get("/intraday-execution")
def get_intraday_execution():
    """Return latest Top5 candidates enriched with realtime snapshot data."""
    db_path = get_recap_db_path()
    if not db_path.exists():
        return {"date": None, "candidates": [], "snapshot_ts": None, "market_brief": None}

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # 1. Fetch latest Top5 candidates
        cursor.execute("""
            SELECT * FROM candidates
            WHERE date = (SELECT max(date) FROM candidates)
            ORDER BY score DESC
            LIMIT 5
        """)
        candidate_cols = [desc[0] for desc in cursor.description] if cursor.description else []
        candidate_rows = cursor.fetchall()

        if not candidate_rows:
            conn.close()
            return {"date": None, "candidates": [], "snapshot_ts": None, "market_brief": None}

        latest_date = candidate_rows[0]["date"]
        codes = [row["code"] for row in candidate_rows]

        # 2. Fetch realtime snapshot for each candidate
        placeholders = ", ".join("?" for _ in codes)
        cursor.execute(f"""
            SELECT code, price, change_pct, score_intraday, seal_funds, ts
            FROM realtime_snapshot
            WHERE code IN ({placeholders})
        """, codes)
        rs_rows = cursor.fetchall()
        rs_map = {row["code"]: dict(row) for row in rs_rows}

        # Determine latest snapshot timestamp
        snapshot_ts = None
        for rs in rs_map.values():
            if rs.get("ts"):
                snapshot_ts = rs["ts"]

        # 3. Build candidate list
        candidates_list = []
        for row in candidate_rows:
            c = dict(row)
            code = c["code"]
            rs = rs_map.get(code, {})
            c["score_intraday"] = rs.get("score_intraday")
            c["price"] = rs.get("price")
            c["change_pct"] = rs.get("change_pct")
            c["seal_funds"] = rs.get("seal_funds")
            candidates_list.append(c)

        # 4. Market brief from realtime_snapshot
        try:
            cursor.execute("""
                SELECT
                    SUM(CASE WHEN change_pct >= 9.8 THEN 1 ELSE 0 END) AS limit_up,
                    SUM(CASE WHEN blown_count > 0 THEN 1 ELSE 0 END) AS broken,
                    SUM(CASE WHEN change_pct <= -9.8 THEN 1 ELSE 0 END) AS limit_down
                FROM realtime_snapshot
            """)
            brief_row = cursor.fetchone()
            market_brief = dict(brief_row) if brief_row else None
        except Exception:
            market_brief = None

        conn.close()

        return {
            "date": latest_date,
            "candidates": candidates_list,
            "snapshot_ts": snapshot_ts,
            "market_brief": market_brief,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to query intraday execution data: {str(e)}")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python3 -m pytest tests/test_intraday_execution.py -v
```

Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add vendor/tickflow-stock-panel/backend/app/api/recap.py tests/test_intraday_execution.py
git commit -m "feat: add GET /api/recap/intraday-execution endpoint with realtime snapshot enrichment"
```

---

### Task 2: Frontend API types and client method

**Files:**
- Modify: `vendor/tickflow-stock-panel/frontend/src/lib/api.ts`

- [ ] **Step 1: Add types**

After the existing `UziAuditRecord` type (around line 696 in api.ts), add:

```typescript
export interface IntradayExecutionCandidate extends Candidate {
  score_intraday: number | null;
  price: number | null;
  change_pct: number | null;
  seal_funds: number | null;
}

export interface MarketBrief {
  limit_up: number | null;
  broken: number | null;
  limit_down: number | null;
}

export interface IntradayExecutionResponse {
  date: string | null;
  candidates: IntradayExecutionCandidate[];
  snapshot_ts: string | null;
  market_brief: MarketBrief | null;
}
```

- [ ] **Step 2: Add API method**

After the `recapRun` line (~line 721 in api.ts), add:

```typescript
intradayExecution: () =>
  request<IntradayExecutionResponse>('/api/recap/intraday-execution'),
```

- [ ] **Step 3: Commit**

```bash
git add vendor/tickflow-stock-panel/frontend/src/lib/api.ts
git commit -m "feat: add IntradayExecution types and api.intradayExecution()"
```

---

### Task 3: SSE invalidation for recap-execution

**Files:**
- Modify: `vendor/tickflow-stock-panel/frontend/src/lib/queryKeys.ts`

- [ ] **Step 1: Add 'recap-execution' to SSE_INVALIDATE_PREFIXES**

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

- [ ] **Step 2: Commit**

```bash
git add vendor/tickflow-stock-panel/frontend/src/lib/queryKeys.ts
git commit -m "feat: add recap-execution to SSE auto-refresh prefixes"
```

---

### Task 4: TradeCockpit page rewrite

**Files:**
- Modify: `vendor/tickflow-stock-panel/frontend/src/pages/TradeCockpit.tsx`

- [ ] **Step 1: Rewrite TradeCockpit.tsx**

Full replacement of the file content. Key changes:
- Switch data source from `api.recapAll()` to `api.intradayExecution()`
- Remove `CondBuyPanel`, `DefensivePanel`, `PositionOverview` components
- Add session indicator logic
- Add real-time data display per candidate card
- Add score comparison (盘后 vs 盘中)
- Add market brief panel at bottom
- Wire `currentChangePct` into AuctionMatrix

```typescript
import { useState, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { RefreshCw, Zap, Target, Bell, Activity } from 'lucide-react'
import { api, type IntradayExecutionCandidate } from '@/lib/api'
import { SignalCard } from '@/components/recap/SignalCard'
import { AuctionMatrix, DEFAULT_AUCTION_TIERS } from '@/components/recap/AuctionMatrix'
import { fmtPrice, fmtPct, priceColorClass } from '@/lib/format'
import { cn } from '@/lib/cn'

function TradeSkeleton() {
  return (
    <div className="p-4 space-y-4">
      <div className="h-8 w-64 rounded bg-elevated animate-pulse" />
      <div className="grid grid-cols-3 gap-4">
        <div className="col-span-2 space-y-2">
          {[1, 2, 3].map(i => (
            <div key={i} className="h-24 rounded-card bg-elevated animate-pulse" style={{ animationDelay: `${i * 80}ms` }} />
          ))}
        </div>
        <div className="space-y-3">
          <div className="h-32 rounded-card bg-elevated animate-pulse" />
          <div className="h-32 rounded-card bg-elevated animate-pulse" />
        </div>
      </div>
    </div>
  )
}

function formatDateLabel(dateStr: string | null): string {
  if (!dateStr) return '—'
  const d = new Date(dateStr)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function getTradingSession(): { label: string; color: string; dot: string } {
  const now = new Date()
  const h = now.getHours(); const m = now.getMinutes()
  const t = h * 100 + m
  if (t < 915) return { label: '盘前', color: 'text-muted', dot: '○' }
  if (t < 925) return { label: '竞价时段', color: 'text-bull', dot: '●' }
  if (t < 930) return { label: '集合竞价', color: 'text-warning', dot: '●' }
  if (t < 1130) return { label: '早盘交易', color: 'text-bull', dot: '●' }
  if (t < 1300) return { label: '午间休市', color: 'text-muted', dot: '○' }
  if (t < 1500) return { label: '午后交易', color: 'text-bull', dot: '●' }
  return { label: '已收盘', color: 'text-muted', dot: '○' }
}

function MarketBrief({ data }: { data: { limit_up: number | null; broken: number | null; limit_down: number | null } | null }) {
  if (!data) return null
  return (
    <div className="grid grid-cols-4 gap-2">
      {[
        { label: '涨停', value: data.limit_up, color: 'text-bull' },
        { label: '炸板', value: data.broken, color: 'text-warning' },
        { label: '跌停', value: data.limit_down, color: 'text-bear' },
        { label: '快照', value: null, color: 'text-muted' },
      ].map(item => (
        <div key={item.label} className="rounded-card border border-border bg-surface p-2.5">
          <div className="text-[10px] text-muted font-medium">{item.label}</div>
          <div className={cn('text-lg font-bold tabular-nums leading-tight', item.color)}>
            {item.value != null ? item.value : '—'}
          </div>
        </div>
      ))}
    </div>
  )
}

export function TradeCockpit() {
  const { data, isLoading, refetch } = useQuery({
    queryKey: ['recap-execution'],
    queryFn: () => api.intradayExecution(),
    refetchInterval: 30_000, // fallback poll if SSE missed
  })

  const [selectedCode, setSelectedCode] = useState<string | null>(null)

  const candidates = data?.candidates ?? []
  const top5 = candidates.slice(0, 5)
  const selectedCandidate = top5.find(c => c.code === selectedCode) ?? top5[0] ?? null
  const session = getTradingSession()

  if (isLoading) return <TradeSkeleton />

  return (
    <div className="p-4 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h1 className="text-base font-semibold text-foreground flex items-center gap-2">
            <Zap className="h-4 w-4 text-accent" />
            晋级监控
          </h1>
          <span className="text-[11px] font-mono text-muted bg-surface px-2 py-0.5 rounded border border-border">
            {formatDateLabel(data?.date ?? null)}
          </span>
          <span className={cn('text-[11px] font-medium flex items-center gap-1', session.color)}>
            <span className="text-xs">{session.dot}</span>
            {session.label}
          </span>
        </div>
        <button
          onClick={() => refetch()}
          className="rounded-btn border border-border px-2.5 py-1.5 text-[11px] text-muted hover:text-foreground hover:border-accent/40 active:scale-[0.97] transition-all flex items-center gap-1.5"
        >
          <RefreshCw className="h-3 w-3" />
          刷新
        </button>
      </div>

      {/* Main: 3-col layout */}
      <div className="grid grid-cols-3 gap-4">
        {/* Left: Top5 cards */}
        <div className="col-span-2 space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-medium text-muted flex items-center gap-1.5">
              <Target className="h-3.5 w-3.5" />
              实时晋级监控 · Top5 候选
            </span>
            <span className="text-[10px] text-muted/50 tabular-nums">
              {data?.snapshot_ts ? `快照 ${data.snapshot_ts.slice(11, 16)}` : '无实时数据'}
            </span>
          </div>
          {top5.length === 0 ? (
            <div className="text-[11px] text-muted/60 text-center py-8">暂无候选数据</div>
          ) : (
            <div className="space-y-2">
              {top5.map((c, i) => (
                <SignalCard
                  key={c.code}
                  candidate={c}
                  rank={i + 1}
                  active={selectedCode === c.code}
                  onClick={() => setSelectedCode(c.code)}
                />
              ))}
            </div>
          )}
        </div>

        {/* Right: Selected detail + Auction */}
        <div className="space-y-3">
          {/* Selected detail card */}
          <div className="rounded-card border border-border bg-surface p-3">
            <div className="text-[11px] font-medium text-muted mb-2 flex items-center gap-1.5 border-b border-border pb-2">
              <Bell className="h-3.5 w-3.5" />
              {selectedCandidate ? `${selectedCandidate.name} · ${selectedCandidate.code}` : '未选择'}
            </div>
            {selectedCandidate ? (
              <IntradayDetail candidate={selectedCandidate} />
            ) : (
              <div className="text-[11px] text-muted/60 text-center py-4">选择一个候选查看详情</div>
            )}
          </div>

          {/* Auction matrix */}
          <div className="rounded-card border border-border bg-surface p-3">
            <AuctionMatrix
              tiers={DEFAULT_AUCTION_TIERS}
              currentChangePct={selectedCandidate?.change_pct ?? null}
            />
          </div>
        </div>
      </div>

      {/* Market brief */}
      {data?.market_brief && (
        <div>
          <div className="text-[11px] font-medium text-muted mb-2 flex items-center gap-1.5">
            <Activity className="h-3.5 w-3.5" />
            市场脉搏
          </div>
          <MarketBrief data={data.market_brief} />
        </div>
      )}
    </div>
  )
}

TradeCockpit.displayName = 'TradeCockpit'

function IntradayDetail({ candidate }: { candidate: IntradayExecutionCandidate }) {
  const scoreDiff = candidate.score_intraday != null ? candidate.score_intraday - candidate.score : null

  return (
    <div className="space-y-3">
      {/* Score comparison */}
      <div className="grid grid-cols-2 gap-3">
        <div>
          <div className="text-[10px] text-muted font-medium">盘后评分</div>
          <div className="text-lg font-bold tabular-nums text-foreground">{candidate.score}</div>
        </div>
        <div>
          <div className="text-[10px] text-muted font-medium">盘中评分</div>
          <div className="flex items-baseline gap-1.5">
            <span className={cn(
              'text-lg font-bold tabular-nums',
              candidate.score_intraday != null ? 'text-accent' : 'text-muted/50',
            )}>
              {candidate.score_intraday != null ? candidate.score_intraday : '—'}
            </span>
            {scoreDiff != null && (
              <span className={cn(
                'text-[10px] font-medium',
                scoreDiff > 0 ? 'text-bull' : scoreDiff < 0 ? 'text-bear' : 'text-muted',
              )}>
                {scoreDiff > 0 ? '↑' : '↓'}{Math.abs(scoreDiff)}
              </span>
            )}
          </div>
        </div>
      </div>

      {/* Price + Change */}
      <div className="grid grid-cols-2 gap-3 pt-2 border-t border-border/50">
        <div>
          <div className="text-[10px] text-muted font-medium">当前价格</div>
          <div className="text-base font-bold tabular-nums font-mono text-foreground">
            {candidate.price != null ? fmtPrice(candidate.price) : '—'}
          </div>
        </div>
        <div>
          <div className="text-[10px] text-muted font-medium">涨幅</div>
          <div className={cn(
            'text-base font-bold tabular-nums font-mono',
            candidate.change_pct != null ? priceColorClass(candidate.change_pct) : 'text-muted/50',
          )}>
            {candidate.change_pct != null ? fmtPct(candidate.change_pct) : '—'}
          </div>
        </div>
      </div>

      {/* Seal funds */}
      {candidate.seal_funds != null && (
        <div className="pt-2 border-t border-border/50">
          <div className="text-[10px] text-muted font-medium">封单资金</div>
          <div className="text-base font-bold tabular-nums text-bull">
            {fmtPrice(candidate.seal_funds)}元
          </div>
        </div>
      )}

      {/* Playbook */}
      <div className="pt-2 border-t border-border/50">
        <div className="text-[10px] text-muted font-medium mb-1">操作建议</div>
        <div className="text-[10px] text-muted/80 leading-relaxed border-l-2 border-l-accent/30 pl-2 line-clamp-4">
          {candidate.playbook}
        </div>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Commit**

```bash
git add vendor/tickflow-stock-panel/frontend/src/pages/TradeCockpit.tsx
git commit -m "feat: rewrite TradeCockpit as 晋级监控 with real-time execution monitoring"
```

---

### Task 5: Verify and run checks

- [ ] **Step 1: Run backend tests**

```bash
python3 -m pytest tests/test_intraday_execution.py -v
```

Expected: 3 PASS

- [ ] **Step 2: Run full test suite**

```bash
python3 -m pytest -q
```

Expected: All existing tests still pass + 3 new tests pass.

- [ ] **Step 3: Ruff check**

```bash
python3 -m ruff check src tests
```

Expected: No new warnings.

- [ ] **Step 4: Final commit of any outstanding changes**

```bash
git status
```

Verify only expected files are modified.

---

### Task 6: Final checks and merge prep

- [ ] **Step 1: Review the full diff**

```bash
git log --oneline --first-parent
git diff main --stat
```

- [ ] **Step 2: Merge to main**

```bash
git checkout main
git merge --squash feature/intraday-execution-monitor
git commit -m "feat: 晋级监控 — 盘中执行模块前后端打通，Top5 候选实时晋级跟踪"
```

- [ ] **Step 3: Delete branch**

```bash
git branch -d feature/intraday-execution-monitor
```

- [ ] **Step 4: Push**

```bash
git push
```
