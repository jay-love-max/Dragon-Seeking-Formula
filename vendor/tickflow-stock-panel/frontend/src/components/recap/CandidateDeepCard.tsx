import { cn } from '@/lib/cn'
import { fmtBigNum } from '@/lib/format'
import type { Candidate } from '@/lib/api'

interface CandidateDeepCardProps {
  candidate: Candidate
  rank: number
}

const PERSONALITY_LABELS: Record<string, string> = {
  activity: '活跃度',
  reliability: '可靠性',
  explosiveness: '爆发力',
  capital: '资金力',
  early_board: '早板力',
}

const DIM_COLORS = ['bg-accent/60', 'bg-bull/60', 'bg-warning/60', 'bg-bear/60', 'bg-purple-500/60']

const GRADE_COLORS: Record<string, string> = {
  SSS: 'text-purple-400',
  S: 'text-accent',
  A: 'text-bull',
  B: 'text-warning',
  C: 'text-bear',
  D: 'text-danger',
}

function PersonalityBar({ dim, value }: { dim: string; value: number }) {
  const label = PERSONALITY_LABELS[dim] ?? dim
  const barColor = DIM_COLORS[Object.keys(PERSONALITY_LABELS).indexOf(dim) % DIM_COLORS.length]
  return (
    <div className="flex items-center gap-2 text-[11px]">
      <span className="w-12 text-muted shrink-0 text-right">{label}</span>
      <div className="flex-1 h-1.5 rounded-full bg-elevated overflow-hidden">
        <div
          className={`h-full rounded-full transition-all ${barColor}`}
          style={{ width: `${Math.min(100, Math.max(0, value))}%` }}
        />
      </div>
      <span className="w-8 text-right tabular-nums font-medium text-foreground/80">{value}</span>
    </div>
  )
}

function LhbSegmentedBar({
  gold,
  death,
  inst,
}: {
  gold: number | null
  death: number | null
  inst: number | null
}) {
  const values = [gold ?? 0, death ?? 0, inst ?? 0]
  const maxAbs = Math.max(1, ...values.map(Math.abs))
  const hasData = gold != null || death != null || inst != null
  if (!hasData) {
    return <div className="text-[11px] text-muted/60 py-2">龙虎榜数据 —</div>
  }
  return (
    <div className="space-y-1">
      <div className="flex h-2 rounded-full overflow-hidden bg-elevated">
        {gold != null && gold > 0 && (
          <div
            className="h-full bg-bull/70"
            style={{ width: `${Math.max(4, (gold / maxAbs) * 50)}%` }}
          />
        )}
        {inst != null && inst > 0 && (
          <div
            className="h-full bg-accent/70"
            style={{ width: `${Math.max(4, (inst / maxAbs) * 50)}%` }}
          />
        )}
        {death != null && death < 0 && (
          <div
            className="h-full ml-auto bg-bear/70"
            style={{ width: `${Math.max(4, (Math.abs(death) / maxAbs) * 50)}%` }}
          />
        )}
        {death != null && death > 0 && (
          <div
            className="h-full ml-auto bg-bear/70"
            style={{ width: `${Math.max(4, (death / maxAbs) * 50)}%` }}
          />
        )}
      </div>
      <div className="flex justify-between text-[10px] tabular-nums">
        {gold != null && <span className="text-bull">GOLD +{fmtBigNum(gold)}</span>}
        {inst != null && <span className="text-accent">机构 {fmtBigNum(inst)}</span>}
        {death != null && (
          <span className={death < 0 ? 'text-bear' : 'text-bear'}>
            DEATH {death < 0 ? '' : '+'}{fmtBigNum(death)}
          </span>
        )}
      </div>
    </div>
  )
}

function ScoreRing({ score, size = 56 }: { score: number; size?: number }) {
  const r = (size - 8) / 2
  const circ = 2 * Math.PI * r
  const pct = Math.min(100, Math.max(0, score))
  const stroke = pct >= 100 ? '#EF4444' : pct >= 80 ? '#3B82F6' : pct >= 60 ? '#EAB308' : '#6B7280'
  return (
    <div className="relative inline-flex items-center justify-center" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="currentColor" strokeWidth={3} className="text-elevated" />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke={stroke}
          strokeWidth={3}
          strokeLinecap="round"
          strokeDasharray={circ}
          strokeDashoffset={circ * (1 - pct / 100)}
          className="transition-all duration-700"
        />
      </svg>
      <span className="absolute text-xs font-bold tabular-nums" style={{ color: stroke }}>{score}</span>
    </div>
  )
}

function BlockBadge({ label, passed }: { label: string; passed: boolean | null }) {
  if (passed == null) {
    return (
      <span className="inline-flex items-center gap-1 px-1.5 py-0.5 text-[10px] font-medium border rounded bg-elevated text-muted border-border/50">
        {label} —
      </span>
    )
  }
  if (passed) {
    return (
      <span className="inline-flex items-center gap-1 px-1.5 py-0.5 text-[10px] font-medium border rounded bg-bull/10 text-bull border-bull/30">
        {label} ✓
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1 px-1.5 py-0.5 text-[10px] font-medium border rounded bg-danger/10 text-danger border-danger/30">
      {label} ✗
    </span>
  )
}

export function CandidateDeepCard({ candidate: c, rank }: CandidateDeepCardProps) {
  const dims = c.personality_dims ?? {}
  const dimEntries = Object.entries(PERSONALITY_LABELS).map(([key, label]) => ({
    key,
    label,
    value: (dims as any)[key] ?? 0,
  }))

  return (
    <div className="rounded-card border border-border bg-surface overflow-hidden">
      <div className="p-4 space-y-4">
        <div className="flex items-start gap-4">
          <div className="flex items-center gap-2 min-w-0">
            <span className={cn(
              'flex items-center justify-center w-6 h-6 rounded-full text-xs font-bold tabular-nums shrink-0',
              rank === 1 ? 'bg-danger/10 text-danger' :
              rank === 2 ? 'bg-warning/10 text-warning' :
              rank === 3 ? 'bg-accent/10 text-accent' :
              'bg-elevated text-muted',
            )}>
              {rank}
            </span>
            <div>
              <div className="flex items-center gap-1.5">
                <span className="text-sm font-semibold text-foreground">{c.name}</span>
                <span className="text-[10px] font-mono text-muted">{c.code}</span>
              </div>
              <div className="flex items-center gap-1.5 text-[10px] text-muted">
                <span>{c.sector}</span>
                {c.float_mcap != null && <span>· {c.float_mcap.toFixed(1)}亿</span>}
              </div>
            </div>
          </div>

          <div className="flex items-center gap-3 ml-auto">
            <ScoreRing score={c.score} />
            <div className="text-right">
              <div className={cn(
                'text-[11px] font-bold tabular-nums',
                c.pred_prob != null && c.pred_prob >= 0.3 ? 'text-bull' :
                c.pred_prob != null && c.pred_prob >= 0.1 ? 'text-warning' : 'text-muted',
              )}>
                {c.pred_prob != null ? `${(c.pred_prob * 100).toFixed(1)}%` : '—'}
              </div>
              <div className="text-[10px] text-muted">晋级概率</div>
            </div>
          </div>
        </div>

        <div className="grid grid-cols-3 gap-4">
          <div className="space-y-1.5">
            <div className="text-[10px] font-medium text-muted mb-1">五维个性</div>
            <div className="flex items-center gap-1.5 mb-1.5">
              <span className={cn('text-xs font-bold', GRADE_COLORS[c.personality_grade ?? ''] ?? 'text-muted')}>
                {c.personality_grade ?? '—'}
              </span>
              <span className="text-[10px] text-muted">等级</span>
            </div>
            {dimEntries.map(({ key, value }) => (
              <PersonalityBar key={key} dim={key} value={value} />
            ))}
          </div>

          <div className="space-y-2">
            <div className="text-[10px] font-medium text-muted">龙虎榜质量</div>
            <LhbSegmentedBar gold={c.lhb_gold_net} death={c.lhb_death_net} inst={c.lhb_inst_net} />
            <div className="pt-2 border-t border-border/30">
              <div className="text-[10px] font-medium text-muted mb-1">挡板审计</div>
              <div className="flex flex-wrap gap-1">
                <BlockBadge label="F16 LHB" passed={c.block_f16 != null ? !c.block_f16 : null} />
                <BlockBadge label="F17 个性" passed={c.block_f17 != null ? !c.block_f17 : null} />
                <BlockBadge label="F18 市况" passed={c.block_f18 != null ? !c.block_f18 : null} />
                <BlockBadge label="F19 过滤" passed={c.block_f19 != null ? !c.block_f19 : null} />
              </div>
            </div>
          </div>

          <div className="space-y-2">
            <div className="text-[10px] font-medium text-muted">执行计划</div>
            {c.buy_plan ? (
              <div className="text-[11px] space-y-0.5">
                <div className="text-bull font-medium">条件买入</div>
                <div className="text-muted">
                  触发价 <span className="font-mono tabular-nums text-foreground/80">{c.buy_plan.trigger_price?.toFixed(2) ?? '—'}</span>
                </div>
                {c.buy_plan.precondition && (
                  <div className="text-muted">{c.buy_plan.precondition}</div>
                )}
              </div>
            ) : (
              <div className="text-[11px] text-muted/60">—</div>
            )}
            {(c.defensive_plans?.length ?? 0) > 0 && (
              <div className="border-t border-border/30 pt-1.5">
                <div className="text-[10px] text-muted mb-1">防守</div>
                {c.defensive_plans?.map((p, i) => (
                  <div key={i} className="flex items-center gap-1.5 text-[10px]">
                    <span className={cn(
                      'px-1 py-px rounded text-[9px] font-medium border',
                      p.action === 'EXIT' ? 'bg-danger/10 text-danger border-danger/30' :
                      p.action === 'REDUCE' ? 'bg-warning/10 text-warning border-warning/30' :
                      'bg-accent/10 text-accent border-accent/30',
                    )}>
                      {p.action}
                    </span>
                    <span className="font-mono tabular-nums text-muted">{p.trigger_price?.toFixed(2)}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {c.playbook && (
          <div className="text-[11px] text-muted/80 leading-relaxed border-l-2 border-l-accent/30 pl-3 py-1 bg-accent/[0.02] rounded-r">
            {c.playbook}
          </div>
        )}
      </div>
    </div>
  )
}
CandidateDeepCard.displayName = 'CandidateDeepCard'
