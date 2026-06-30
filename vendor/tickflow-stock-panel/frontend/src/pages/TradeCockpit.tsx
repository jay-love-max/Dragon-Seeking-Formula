import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { RefreshCw, Zap, Target, Bell, Activity, TrendingUp, TrendingDown } from 'lucide-react'
import { api, type IntradayExecutionCandidate } from '@/lib/api'
import { AuctionMatrix, DEFAULT_AUCTION_TIERS } from '@/components/recap/AuctionMatrix'
import { fmtPrice, fmtPct, priceColorClass, fmtBigNum } from '@/lib/format'
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

const RANK_COLORS = ['text-bull', 'text-warning', 'text-accent', 'text-muted', 'text-muted']
const RANK_BG = ['bg-bull/10', 'bg-warning/10', 'bg-accent/10', 'bg-elevated', 'bg-elevated']

function getSession(): { label: string; color: string; dot: string } {
  const now = new Date()
  const t = now.getHours() * 100 + now.getMinutes()
  if (t < 915) return { label: '盘前', color: 'text-muted', dot: '○' }
  if (t < 925) return { label: '竞价时段', color: 'text-bull', dot: '●' }
  if (t < 930) return { label: '集合竞价', color: 'text-warning', dot: '●' }
  if (t < 1130) return { label: '早盘交易', color: 'text-bull', dot: '●' }
  if (t < 1300) return { label: '午间休市', color: 'text-muted', dot: '○' }
  if (t < 1500) return { label: '午后交易', color: 'text-bull', dot: '●' }
  return { label: '已收盘', color: 'text-muted', dot: '○' }
}

function getScoreBarColor(score: number): string {
  if (score >= 100) return 'bg-bull'
  if (score >= 80) return 'bg-accent'
  if (score >= 60) return 'bg-warning'
  return 'bg-muted/50'
}

function ScoreBadge({ score, scoreIntraday }: { score: number; scoreIntraday: number | null }) {
  const diff = scoreIntraday != null ? scoreIntraday - score : null
  return (
    <div className="flex items-center gap-2">
      <div className="flex items-baseline gap-1">
        <span className="text-[10px] text-muted/60">盘后</span>
        <span className={cn('text-xs font-bold tabular-nums', score >= 100 ? 'text-bull' : score >= 80 ? 'text-accent' : 'text-muted')}>
          {score}
        </span>
      </div>
      {scoreIntraday != null && (
        <>
          <span className="text-muted/30">→</span>
          <div className="flex items-baseline gap-0.5">
            <span className="text-[10px] text-muted/60">盘中</span>
            <span className="text-xs font-bold tabular-nums text-accent">{scoreIntraday}</span>
            {diff != null && diff !== 0 && (
              <span className={cn('text-[10px] font-medium', diff > 0 ? 'text-bull' : 'text-bear')}>
                {diff > 0 ? '↑' : '↓'}{Math.abs(diff)}
              </span>
            )}
          </div>
        </>
      )}
    </div>
  )
}

function ExecutionCard({ candidate, rank, active, onClick }: {
  candidate: IntradayExecutionCandidate
  rank: number
  active: boolean
  onClick: () => void
}) {
  const hasRealtime = candidate.change_pct != null
  const isLimitUp = candidate.change_pct != null && candidate.change_pct >= 9.8
  const isBroken = (candidate.blown_count ?? 0) > 0

  return (
    <div
      onClick={onClick}
      className={cn(
        'rounded-card border transition-all duration-200 cursor-pointer select-none p-3',
        active
          ? 'border-accent/50 bg-accent/[0.03] shadow-[0_0_12px_rgba(59,130,246,0.08)]'
          : 'border-border bg-surface hover:border-accent/30 hover:bg-accent/[0.02]',
      )}
    >
      <div className="flex items-start gap-3">
        <div className={cn(
          'w-6 h-6 rounded-full text-[11px] font-bold tabular-nums flex items-center justify-center shrink-0',
          RANK_COLORS[rank - 1], RANK_BG[rank - 1],
        )}>
          {rank}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-semibold text-sm text-foreground truncate">{candidate.name}</span>
            <span className="text-[10px] font-mono text-muted shrink-0">{candidate.code}</span>
            {candidate.personality_grade && (
              <span className="px-1 py-0.5 text-[9px] font-bold border rounded bg-purple-500/10 text-purple-400 border-purple-500/30 shrink-0">
                {candidate.personality_grade}
              </span>
            )}
          </div>
          <div className="flex items-center gap-2 mt-0.5">
            <span className="text-[10px] text-muted/70">{candidate.sector}</span>
            {hasRealtime && (
              <>
                <span className="text-muted/30">·</span>
                <span className={cn('text-[10px] font-medium', isLimitUp ? 'text-bull' : isBroken ? 'text-warning' : 'text-muted/70')}>
                  {isLimitUp ? '● 已封板' : isBroken ? `◆ 炸板 ${candidate.blown_count} 次` : `◈ ${candidate.first_seal_time_formatted ?? candidate.first_seal_time} 封`}
                </span>
              </>
            )}
          </div>
          <div className="flex items-center justify-between mt-2">
            <ScoreBadge score={candidate.score} scoreIntraday={candidate.score_intraday} />
            {hasRealtime && (
              <div className={cn(
                'text-sm font-bold tabular-nums font-mono',
                priceColorClass(candidate.change_pct!),
              )}>
                {fmtPct(candidate.change_pct!)}
              </div>
            )}
          </div>
          <div className="flex items-center gap-2 mt-1.5">
            <div className="flex-1 h-1.5 rounded-full bg-elevated overflow-hidden">
              <div
                className={cn('h-full rounded-full transition-all duration-500', getScoreBarColor(candidate.score))}
                style={{ width: `${Math.min(100, (candidate.score / 150) * 100)}%` }}
              />
            </div>
            {hasRealtime && candidate.price != null && (
              <span className="text-[10px] font-mono text-muted tabular-nums shrink-0">
                {fmtPrice(candidate.price)}
              </span>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

function IntradayDetail({ candidate }: { candidate: IntradayExecutionCandidate }) {
  const scoreDiff = candidate.score_intraday != null ? candidate.score_intraday - candidate.score : null

  return (
    <div className="space-y-3">
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
              <span className={cn('text-[10px] font-medium', scoreDiff > 0 ? 'text-bull' : scoreDiff < 0 ? 'text-bear' : 'text-muted')}>
                {scoreDiff > 0 ? '↑' : '↓'}{Math.abs(scoreDiff)}
              </span>
            )}
          </div>
        </div>
      </div>

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

      <div className="grid grid-cols-2 gap-3 pt-2 border-t border-border/50">
        <div>
          <div className="text-[10px] text-muted font-medium">封单资金</div>
          <div className="text-sm font-bold tabular-nums text-bull">
            {candidate.seal_funds != null ? fmtBigNum(candidate.seal_funds) : '—'}
          </div>
        </div>
        <div>
          <div className="text-[10px] text-muted font-medium">首封时间</div>
          <div className="text-sm font-bold tabular-nums font-mono text-foreground">
            {candidate.first_seal_time_formatted ?? candidate.first_seal_time ?? '—'}
          </div>
        </div>
      </div>

      {candidate.playbook && (
        <div className="pt-2 border-t border-border/50">
          <div className="text-[10px] text-muted font-medium mb-1">操作建议</div>
          <div className="text-[10px] text-muted/80 leading-relaxed border-l-2 border-l-accent/30 pl-2 line-clamp-4">
            {candidate.playbook}
          </div>
        </div>
      )}
    </div>
  )
}

function MarketBrief({ data }: { data: { limit_up: number | null; broken: number | null; limit_down: number | null } | null }) {
  if (!data) return null
  const items = [
    { label: '涨停', value: data.limit_up, color: 'text-bull', icon: TrendingUp },
    { label: '炸板', value: data.broken, color: 'text-warning', icon: null },
    { label: '跌停', value: data.limit_down, color: 'text-bear', icon: TrendingDown },
  ]
  return (
    <div className="grid grid-cols-3 gap-2">
      {items.map(item => (
        <div key={item.label} className="rounded-card border border-border bg-surface p-2.5">
          <div className="flex items-center gap-1.5 text-[10px] text-muted font-medium">
            {item.icon && <item.icon className="h-3 w-3" />}
            {item.label}
          </div>
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
    refetchInterval: 30_000,
  })

  const [selectedCode, setSelectedCode] = useState<string | null>(null)

  const candidates = data?.candidates ?? []
  const top5 = candidates.slice(0, 5)
  const selectedCandidate = top5.find(c => c.code === selectedCode) ?? top5[0] ?? null
  const session = getSession()

  if (isLoading) return <TradeSkeleton />

  const promotedCount = top5.filter(c => c.change_pct != null && c.change_pct >= 9.8).length

  return (
    <div className="p-4 space-y-4">
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
          {data?.snapshot_ts && (
            <span className="text-[10px] text-muted/50 font-mono">
              快照 {data.snapshot_ts.slice(11, 16)}
            </span>
          )}
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
              实时晋级监控 · Top5 候选
            </span>
            <span className="text-[10px] text-muted/50 tabular-nums">
              {promotedCount > 0 ? `已晋级 ${promotedCount}/5` : `${candidates.length} 只候选`}
            </span>
          </div>
          {top5.length === 0 ? (
            <div className="text-[11px] text-muted/60 text-center py-8">暂无候选数据</div>
          ) : (
            <div className="space-y-2">
              {top5.map((c, i) => (
                <ExecutionCard
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

          <div className="rounded-card border border-border bg-surface p-3">
            <AuctionMatrix
              tiers={DEFAULT_AUCTION_TIERS}
              currentChangePct={selectedCandidate?.change_pct ?? null}
            />
          </div>
        </div>
      </div>

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
