import { cn } from '@/lib/cn'
import { fmtPct } from '@/lib/format'

export interface AuctionTier {
  min_pct: number
  max_pct: number
  action: string
  label: string
}

interface AuctionMatrixProps {
  tiers: AuctionTier[]
  currentChangePct?: number | null
  title?: string
}

const ACTION_COLORS: Record<string, string> = {
  immediate_buy: 'bg-bull/10 text-bull border-bull/30',
  partial_add: 'bg-bull/5 text-bull/80 border-bull/20',
  hold: 'bg-warning/10 text-warning border-warning/30',
  partial_reduce: 'bg-bear/10 text-bear border-bear/30',
  exit: 'bg-danger/10 text-danger border-danger/30',
  watch: 'bg-accent/10 text-accent border-accent/30',
}

const TIER_LABELS: Record<string, string> = {
  immediate_buy: '加仓',
  partial_add: '加仓',
  hold: '持有',
  partial_reduce: '减半',
  exit: '清仓',
  watch: '观察',
}

export function AuctionMatrix({ tiers, currentChangePct, title = '竞价矩阵' }: AuctionMatrixProps) {
  return (
    <div className="rounded-card border border-border bg-surface p-3">
      <div className="text-xs font-medium text-muted mb-2">{title}</div>
      <div className="space-y-1">
        {tiers.map((t, i) => {
          const isActive =
            currentChangePct != null &&
            currentChangePct >= t.min_pct &&
            currentChangePct < t.max_pct
          const label = TIER_LABELS[t.action] ?? t.action
          const actionColor = ACTION_COLORS[t.action] ?? 'bg-elevated text-muted'

          return (
            <div
              key={i}
              className={cn(
                'flex items-center gap-2 px-3 py-1.5 rounded text-[11px] transition-colors',
                isActive
                  ? 'border-l-2 border-l-bear bg-bear/[0.04] -ml-px'
                  : 'hover:bg-elevated/40',
              )}
            >
              <span className="w-6 text-[10px] font-mono text-muted tabular-nums text-center shrink-0">
                {t.min_pct > 0 ? `≥+${t.min_pct * 100}%` : t.max_pct < 0 ? `≤${t.max_pct * 100}%` : fmtPct(t.min_pct)}
              </span>
              <span className={cn('inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium border shrink-0', actionColor)}>
                <span>{label}</span>
              </span>
              <span className="text-muted/70 truncate">{t.label}</span>
              {isActive && (
                <span className="ml-auto text-[10px] font-bold text-bear tabular-nums shrink-0">
                  当前 {fmtPct(currentChangePct!)}
                </span>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
AuctionMatrix.displayName = 'AuctionMatrix'

export const DEFAULT_AUCTION_TIERS: AuctionTier[] = [
  { min_pct: 0.08, max_pct: Infinity, action: 'partial_reduce', label: '开 +8% 以上，减半锁利' },
  { min_pct: 0.05, max_pct: 0.08, action: 'partial_reduce', label: '开 +5~8%，减半锁利' },
  { min_pct: 0.03, max_pct: 0.05, action: 'partial_add', label: '开 +3~5%，观察加仓' },
  { min_pct: 0.01, max_pct: 0.03, action: 'hold', label: '开 +1~3%，持有观察' },
  { min_pct: -0.01, max_pct: 0.01, action: 'hold', label: '开 ±1%，持有观察' },
  { min_pct: -0.03, max_pct: -0.01, action: 'watch', label: '开 -1~-3%，谨慎观察' },
  { min_pct: -Infinity, max_pct: -0.03, action: 'exit', label: '开 -3% 以下，退出' },
]
