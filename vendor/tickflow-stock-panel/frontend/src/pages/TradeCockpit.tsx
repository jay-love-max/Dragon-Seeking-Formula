import { useState, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { RefreshCw, Zap, Target, Bell, Shield, ClipboardList } from 'lucide-react'
import { api, type Candidate } from '@/lib/api'
import { SignalCard } from '@/components/recap/SignalCard'
import { AuctionMatrix, DEFAULT_AUCTION_TIERS } from '@/components/recap/AuctionMatrix'
import { fmtPrice } from '@/lib/format'
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

function formatDateLabel(dateStr: string): string {
  const d = new Date(dateStr)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function CondBuyPanel({ candidate }: { candidate: Candidate | null }) {
  if (!candidate?.buy_plan) {
    return (
      <div className="flex items-center justify-center h-full text-[11px] text-muted/60">
        未设置条件买入
      </div>
    )
  }
  const plan = candidate.buy_plan
  return (
    <div className="space-y-2">
      <div className="text-xs font-medium text-foreground">{candidate.name} · 条件买入</div>
      <div className={cn('text-2xl font-bold tabular-nums', plan.trigger_price != null ? 'text-bull' : 'text-muted')}>
        {plan.trigger_price != null ? fmtPrice(plan.trigger_price) : '—'}
      </div>
      {plan.trigger_type && (
        <div className="text-[11px] text-muted">
          触发方式: <span className="font-mono text-foreground/80">{plan.trigger_type}</span>
        </div>
      )}
      {plan.precondition && (
        <div className="text-[11px] text-muted">
          前提条件: <span className="font-mono text-foreground/80">{plan.precondition}</span>
        </div>
      )}
    </div>
  )
}

function DefensivePanel({ candidate }: { candidate: Candidate | null }) {
  const plans = candidate?.defensive_plans ?? []
  if (plans.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-[11px] text-muted/60">
        未设置防守计划
      </div>
    )
  }
  return (
    <div className="space-y-2">
      <div className="text-xs font-medium text-foreground">{candidate?.name ?? '—'} · 持仓防守</div>
      {plans.map((p, i) => (
        <div key={i} className="flex items-center gap-2 text-[11px]">
          <span className={cn(
            'px-1.5 py-0.5 rounded text-[10px] font-medium border',
            p.action === 'EXIT' ? 'bg-danger/10 text-danger border-danger/30' :
            p.action === 'REDUCE' ? 'bg-warning/10 text-warning border-warning/30' :
            'bg-accent/10 text-accent border-accent/30',
          )}>
            {p.action}
          </span>
          <span className="font-mono tabular-nums text-foreground/80">
            {p.trigger_price != null ? fmtPrice(p.trigger_price) : '—'}
          </span>
          {p.precondition && (
            <span className="text-muted/70">{p.precondition}</span>
          )}
        </div>
      ))}
    </div>
  )
}

function PositionOverview() {
  return (
    <div className="flex items-center gap-4 text-xs">
      <div>
        <span className="text-muted">持仓 </span>
        <span className="font-mono tabular-nums text-foreground">0 只</span>
      </div>
      <div>
        <span className="text-muted">浮盈 </span>
        <span className="font-mono tabular-nums text-muted">—</span>
      </div>
      <div>
        <span className="text-muted">盈亏 </span>
        <span className="font-mono tabular-nums text-muted">—</span>
      </div>
    </div>
  )
}

export function TradeCockpit() {
  const { data, isLoading, refetch } = useQuery({
    queryKey: ['recapAllData'],
    queryFn: () => api.recapAll(),
  })

  const [selectedCode, setSelectedCode] = useState<string | null>(null)

  const latestHistory = useMemo(() => {
    if (!data?.history?.length) return null
    return data.history[0]
  }, [data])

  const candidates = latestHistory?.candidates ?? []
  const top5 = candidates.slice(0, 5)
  const selectedCandidate = candidates.find(c => c.code === selectedCode) ?? top5[0] ?? null

  const latestDate = latestHistory?.date ?? '—'

  if (isLoading) return <TradeSkeleton />

  return (
    <div className="p-4 space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h1 className="text-base font-semibold text-foreground flex items-center gap-2">
            <Zap className="h-4 w-4 text-accent" />
            盘中执行
          </h1>
          <span className="text-[11px] font-mono text-muted bg-surface px-2 py-0.5 rounded border border-border">
            {formatDateLabel(latestDate)}
          </span>
          <Bell className="h-3.5 w-3.5 text-muted/50" />
        </div>
        <button
          onClick={() => refetch()}
          className="rounded-btn border border-border px-2.5 py-1.5 text-[11px] text-muted hover:text-foreground hover:border-accent/40 active:scale-[0.97] transition-all flex items-center gap-1.5"
        >
          <RefreshCw className="h-3 w-3" />
          刷新
        </button>
      </div>

      <div className="grid grid-cols-3 gap-4">
        <div className="col-span-2 space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-medium text-muted flex items-center gap-1.5">
              <Target className="h-3.5 w-3.5" />
              竞价监控 · Top5 信号面板</span>
            <span className="text-[10px] text-muted/50 tabular-nums">{candidates.length} 只候选</span>
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

        <div className="space-y-3">
          <div className="rounded-card border border-border bg-surface p-3 min-h-[120px]">
            <div className="text-[11px] font-medium text-muted mb-2 flex items-center gap-1.5">
              <Bell className="h-3.5 w-3.5" />
              条件买入</div>
            <CondBuyPanel candidate={selectedCandidate} />
          </div>
          <div className="rounded-card border border-border bg-surface p-3 min-h-[120px]">
            <div className="text-[11px] font-medium text-muted mb-2 flex items-center gap-1.5">
              <Shield className="h-3.5 w-3.5" />
              持仓防守</div>
            <DefensivePanel candidate={selectedCandidate} />
          </div>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-4">
        <div className="col-span-2">
          <AuctionMatrix tiers={DEFAULT_AUCTION_TIERS} currentChangePct={null} />
        </div>
        <div className="rounded-card border border-border bg-surface p-3 flex items-center">
          <div className="space-y-1 w-full">
            <div className="text-[11px] font-medium text-muted flex items-center gap-1.5">
              <ClipboardList className="h-3.5 w-3.5" />
              持仓概览</div>
            <PositionOverview />
          </div>
        </div>
      </div>
    </div>
  )
}
TradeCockpit.displayName = 'TradeCockpit'
