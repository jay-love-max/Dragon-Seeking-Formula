import { cn } from '@/lib/cn'
import { fmtPct, fmtBigNum } from '@/lib/format'
import type { Candidate } from '@/lib/api'

interface SignalCardProps {
  candidate: Candidate
  rank: number
  active?: boolean
  onClick?: () => void
}

const PERSONALITY_COLORS: Record<string, string> = {
  SSS: 'bg-purple-500/10 text-purple-400 border-purple-500/30',
  S: 'bg-accent/10 text-accent border-accent/40',
  A: 'bg-bull/10 text-bull border-bull/40',
  B: 'bg-warning/10 text-warning border-warning/40',
  C: 'bg-bear/10 text-bear border-bear/40',
  D: 'bg-danger/10 text-danger border-danger/40',
}

function getPersonalityColor(grade: string | null): string {
  return PERSONALITY_COLORS[grade ?? ''] ?? 'bg-elevated text-muted border-border/50'
}

function getScoreColor(score: number): string {
  if (score >= 100) return 'text-bull'
  if (score >= 80) return 'text-accent'
  if (score >= 60) return 'text-warning'
  return 'text-muted'
}

function getLhbColor(value: number | null): string {
  if (value == null) return 'text-muted'
  return value > 0 ? 'text-bull' : value < 0 ? 'text-bear' : 'text-muted'
}

function GradeBadge({ grade }: { grade: string | null }) {
  if (!grade || grade === 'UNKNOWN') return null
  return (
    <span className={`px-1.5 py-0.5 text-[10px] font-bold border rounded ${getPersonalityColor(grade)}`}>
      {grade}
    </span>
  )
}

function ScoreBar({ score }: { score: number }) {
  const pct = Math.min(100, Math.max(0, score))
  return (
    <div className="flex items-center gap-2">
      <span className={`text-base font-bold tabular-nums ${getScoreColor(score)}`}>
        {score}
      </span>
      <div className="flex-1 h-1.5 rounded-full bg-elevated overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-500"
          style={{
            width: `${pct}%`,
            backgroundColor: score >= 100 ? 'rgb(239 68 68)' : score >= 80 ? 'rgb(59 130 246)' : score >= 60 ? 'rgb(234 179 8)' : 'rgb(107 114 128)',
          }}
        />
      </div>
    </div>
  )
}

function ProbBar({ prob, label }: { prob: number | null; label: string }) {
  const pct = prob != null ? Math.min(100, Math.max(0, prob * 100)) : 0
  return (
    <div className="text-[11px]">
      <div className="flex justify-between text-muted mb-0.5">
        <span>{label}</span>
        <span className="tabular-nums font-medium">{prob != null ? `${pct.toFixed(0)}%` : '—'}</span>
      </div>
      <div className="h-1 rounded-full bg-elevated overflow-hidden">
        <div
          className="h-full rounded-full transition-all bg-accent/60"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  )
}

function SealBar({ ratio, turnover }: { ratio: number; turnover: number }) {
  const pct = Math.min(100, Math.max(0, ratio * 100))
  const over100 = ratio > 1
  return (
    <div className="text-[11px]">
      <div className="flex justify-between text-muted mb-0.5">
        <span>封成比</span>
        <span className={`tabular-nums font-medium ${over100 ? 'text-bull' : 'text-muted'}`}>
          {`${(ratio * 100).toFixed(1)}%`}
        </span>
      </div>
      <div className="h-1.5 rounded-full bg-elevated overflow-hidden relative">
        <div
          className={`h-full rounded-full transition-all ${over100 ? 'bg-bull/60' : 'bg-warning/50'}`}
          style={{ width: `${Math.min(100, pct)}%` }}
        />
        {over100 && (
          <div
            className="absolute top-0 h-full w-0.5 bg-bull"
            style={{
              left: `${Math.min(96, pct)}%`,
              boxShadow: '0 0 4px rgba(240,68,56,0.6)',
            }}
          />
        )}
      </div>
      <div className="flex justify-between text-muted mt-0.5">
        <span>换手</span>
        <span className="tabular-nums">{turnover != null ? fmtPct(turnover / 100) : '—'}</span>
      </div>
    </div>
  )
}

function LhbIndicators({
  gold,
  death,
  inst,
}: {
  gold: number | null
  death: number | null
  inst: number | null
}) {
  if (gold == null && death == null && inst == null) {
    return <div className="text-[10px] text-muted/60">龙虎榜 —</div>
  }
  return (
    <div className="flex gap-2 text-[10px]">
      {gold != null && (
        <span className={`tabular-nums ${getLhbColor(gold)}`}>
          GOLD {fmtBigNum(gold)}
        </span>
      )}
      {death != null && (
        <span className={`tabular-nums ${getLhbColor(death)}`}>
          DEATH {fmtBigNum(death)}
        </span>
      )}
      {inst != null && (
        <span className={`tabular-nums ${getLhbColor(inst)}`}>
          机构 {fmtBigNum(inst)}
        </span>
      )}
    </div>
  )
}

function ActionBadge({ label, color }: { label: string; color: 'bull' | 'bear' | 'warning' | 'accent' }) {
  return (
    <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 text-[10px] font-medium rounded border bg-${color}/10 text-${color} border-${color}/30`}>
      {label}
    </span>
  )
}

export function SignalCard({ candidate: c, rank, active = false, onClick }: SignalCardProps) {
  const rankColors = ['text-danger', 'text-warning', 'text-accent', 'text-muted', 'text-muted']
  const rankBgColors = ['bg-danger/10', 'bg-warning/10', 'bg-accent/10', 'bg-elevated', 'bg-elevated']

  return (
    <div
      onClick={onClick}
      className={cn(
        'rounded-card border transition-all duration-200 cursor-pointer select-none',
        active
          ? 'border-accent/50 bg-accent/[0.03] shadow-[0_0_12px_rgba(59,130,246,0.08)]'
          : 'border-border bg-surface hover:border-accent/30 hover:bg-accent/[0.02]',
      )}
    >
      <div className="p-3">
        <div className="flex items-start gap-3">
          <div className={`flex items-center justify-center w-6 h-6 rounded-full text-[11px] font-bold tabular-nums shrink-0 ${rankColors[rank - 1] ?? 'text-muted'} ${rankBgColors[rank - 1] ?? 'bg-elevated'}`}>
            {rank}
          </div>

          <div className="flex-1 min-w-0 grid grid-cols-3 gap-3">
            <div className="space-y-1">
              <div className="flex items-center gap-1.5">
                <span className="text-sm font-semibold text-foreground truncate">{c.name}</span>
                <span className="text-[10px] font-mono text-muted shrink-0">{c.code}</span>
              </div>
              <div className="flex items-center gap-1.5 flex-wrap">
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-elevated text-muted border border-border/50">
                  {c.sector}
                </span>
                <GradeBadge grade={c.personality_grade} />
                {c.float_mcap != null && (
                  <span className="text-[10px] text-muted tabular-nums">
                    {c.float_mcap.toFixed(1)}亿
                  </span>
                )}
              </div>
              <LhbIndicators gold={c.lhb_gold_net} death={c.lhb_death_net} inst={c.lhb_inst_net} />
            </div>

            <div className="space-y-1.5">
              <ScoreBar score={c.score} />
              <ProbBar prob={c.pred_prob} label="晋级概率" />
              {(c.blown_count ?? 0) > 0 && (
                <div className="text-[10px] text-warning/80 tabular-nums">
                  炸板 {c.blown_count} 次
                </div>
              )}
            </div>

            <div className="space-y-1.5">
              <SealBar ratio={c.seal_ratio ?? 0} turnover={c.turnover ?? 0} />
              <div className="text-[10px] text-muted tabular-nums">
                封单 {c.seal_funds != null ? `${c.seal_funds.toFixed(0)}万` : '—'}
              </div>
            </div>
          </div>
        </div>

        {(c.buy_plan || (c.defensive_plans?.length ?? 0) > 0) && (
          <div className="mt-2 pt-2 border-t border-border/40 flex items-center gap-2 flex-wrap">
            {c.buy_plan && (
              <ActionBadge label={`买入 ≥${c.buy_plan.trigger_price != null ? c.buy_plan.trigger_price.toFixed(2) : '—'}`} color="bull" />
            )}
            {(c.defensive_plans ?? []).map((p, i) => {
              const col = p.action === 'EXIT' ? 'bear' : p.action === 'REDUCE' ? 'warning' : 'accent'
              return <ActionBadge key={i} label={`${p.action} ${p.trigger_price != null ? p.trigger_price.toFixed(2) : '—'}`} color={col as any} />
            })}
          </div>
        )}

        {c.playbook && (
          <div className="mt-1.5 text-[10px] text-muted/70 leading-relaxed line-clamp-2 border-l-2 border-l-accent/30 pl-2">
            {c.playbook}
          </div>
        )}
      </div>
    </div>
  )
}
SignalCard.displayName = 'SignalCard'
