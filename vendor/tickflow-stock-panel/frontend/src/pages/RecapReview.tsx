import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ChevronDown, ChevronRight, TrendingUp, Award, Search, Target } from 'lucide-react'
import { api } from '@/lib/api'
import { CandidateDeepCard } from '@/components/recap/CandidateDeepCard'
import { fmtPct, fmtPrice } from '@/lib/format'
import { cn } from '@/lib/cn'


function F18Bar({
  rate,
  numerator,
  denominator,
  lowSample,
}: { rate: number | null; numerator: number | null; denominator: number | null; lowSample: boolean | null }) {
  const hasSample = rate != null && numerator != null && denominator != null && denominator > 0
  const pct = hasSample ? Math.min(100, Math.max(0, rate * 100)) : 0
  const valueText = hasSample ? `${Math.round(pct)}% (${numerator}/${denominator})` : 'NO_SAMPLE'
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-xs">
        <span className="text-muted">晋级率</span>
        <span className="font-mono font-bold tabular-nums text-foreground">
          {valueText}
        </span>
      </div>
      <div className="h-2 rounded-full bg-elevated overflow-hidden relative">
        <div
          className="h-full rounded-full bg-accent/60 transition-all"
          style={{ width: `${pct}%` }}
        />
      </div>
      <div className="flex items-center justify-between text-[9px] text-muted/50 tabular-nums">
        <span>0</span>
        <span>25%</span>
        <span>50%</span>
        <span>75%</span>
        <span>100%</span>
      </div>
      {hasSample && lowSample ? (
        <div className="text-[9px] font-medium text-amber-500">LOW_SAMPLE</div>
      ) : null}
    </div>
  )
}

function RegimeBadge({ regime }: { regime: string | null }) {
  if (!regime) return <span className="text-[11px] text-muted/60">—</span>
  const badges: Record<string, { label: string; className: string }> = {
    FROZEN: { label: '冻结', className: 'bg-danger/10 text-danger border-danger/30' },
    SUPPRESSED: { label: '压制', className: 'bg-bear/10 text-bear border-bear/30' },
    ACTIVE: { label: '活跃', className: 'bg-bull/10 text-bull border-bull/30' },
    MAIN_UP: { label: '主升', className: 'bg-accent/10 text-accent border-accent/30' },
    UNKNOWN: { label: '未知', className: 'bg-elevated text-muted border-border/50' },
  }
  const badge = badges[regime] ?? { label: regime, className: 'bg-elevated text-muted border-border/50' }
  return (
    <span
      className={`inline-flex items-center px-1.5 py-0.5 text-[10px] font-bold border rounded ${badge.className}`}
      title={regime}
    >
      {badge.label}
    </span>
  )
}

function IndexCard({ name, price, change }: { name: string; price: number | null; change: number | null }) {
  const changeCls = change != null && change > 0 ? 'text-bull' : change != null && change < 0 ? 'text-bear' : 'text-muted'
  return (
    <div className="flex items-center justify-between py-1">
      <span className="text-[11px] text-muted">{name}</span>
      <div className="text-right">
        <div className="text-xs font-mono tabular-nums text-foreground">{price != null ? fmtPrice(price) : '—'}</div>
        <div className={`text-[10px] font-mono tabular-nums ${changeCls}`}>
          {change != null ? fmtPct(change) : '—'}
        </div>
      </div>
    </div>
  )
}

function AuditMatrix({
  candidates,
}: {
  candidates: { code: string; name: string; block_f16: number | null; block_f17: number | null; block_f18: number | null; block_f19: number | null }[]
}) {
  const rules = [
    { key: 'block_f16' as const, label: 'F16 LHB' },
    { key: 'block_f17' as const, label: 'F17 个性' },
    { key: 'block_f18' as const, label: 'F18 市况' },
    { key: 'block_f19' as const, label: 'F19 过滤' },
  ]
  const top5 = candidates.slice(0, 5)

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[11px]">
        <thead>
          <tr className="border-b border-border/40 text-muted">
            <th className="py-2 pr-3 text-left font-medium">规则</th>
            {top5.map((c) => (
              <th key={c.code} className="py-2 px-2 text-center font-mono font-medium">{c.name}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rules.map((rule) => (
            <tr key={rule.key} className="border-b border-border/20 hover:bg-elevated/20 transition-colors">
              <td className="py-2 pr-3 text-muted">{rule.label}</td>
              {top5.map((c) => {
                const val = c[rule.key]
                const passed = val != null ? !val : null
                return (
                  <td key={c.code} className="py-2 px-2 text-center">
                    {passed === true ? (
                      <span className="text-bull font-bold">✓</span>
                    ) : passed === false ? (
                      <span className="text-danger font-bold">✗</span>
                    ) : (
                      <span className="text-muted/60">—</span>
                    )}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function TrendChartFallback() {
  return (
    <div className="flex items-center justify-center h-[120px] text-[11px] text-muted/40 bg-surface rounded-card border border-border">
      晋级率趋势图 (待接入 ECharts)
    </div>
  )
}

function CalibrationBuckets({ buckets }: { buckets: { bucket_name: string; score_range: string; total_count: number; promoted_count: number; win_rate: number }[] }) {
  if (buckets.length === 0) return null
  return (
    <div className="flex flex-wrap gap-2">
      {buckets.map((b) => (
        <div key={b.bucket_name} className="flex-1 min-w-[100px] rounded bg-elevated p-2.5 border border-border/40">
          <div className="text-[10px] font-medium text-muted">{b.bucket_name}</div>
          <div className="text-[9px] text-muted/60 font-mono">{b.score_range}</div>
          <div className="mt-1 flex items-center justify-between text-[10px]">
            <span className="text-muted">{b.promoted_count}/{b.total_count}</span>
            <span className="font-mono font-bold tabular-nums" style={{
              color: (b.win_rate ?? 0) >= 50 ? '#F04438' : (b.win_rate ?? 0) >= 30 ? '#EAB308' : '#6B7280',
            }}>
              {(b.win_rate ?? 0).toFixed(1)}%
            </span>
          </div>
          <div className="mt-1 h-1 rounded-full bg-elevated overflow-hidden">
            <div
              className="h-full rounded-full transition-all"
              style={{
                width: `${Math.min(100, Math.max(0, b.win_rate))}%`,
                backgroundColor: b.win_rate >= 50 ? '#F04438' : b.win_rate >= 30 ? '#EAB308' : '#6B7280',
              }} />
          </div>
        </div>
      ))}
    </div>
  )
}

export function RecapReview() {
  const { data, isLoading } = useQuery({
    queryKey: ['recapAllData'],
    queryFn: () => api.recapAll(),
  })

  const [uziOpen, setUziOpen] = useState(false)

  const history = data?.history ?? []
  const latest = history[0]
  const candidates = latest?.candidates ?? []
  const top5 = candidates.slice(0, 5)

  if (isLoading) {
    return (
      <div className="p-4 space-y-4 max-w-5xl mx-auto">
        <div className="h-8 w-48 rounded bg-elevated animate-pulse" />
        <div className="grid grid-cols-3 gap-4">
          {[1, 2, 3].map(i => <div key={i} className="h-36 rounded-card bg-elevated animate-pulse" style={{ animationDelay: `${i * 80}ms` }} />)}
        </div>
        <div className="h-32 rounded-card bg-elevated animate-pulse" />
        <div className="h-48 rounded-card bg-elevated animate-pulse" />
        <div className="h-64 rounded-card bg-elevated animate-pulse" />
      </div>
    )
  }

  return (
    <div className="p-4 space-y-4 max-w-5xl mx-auto">
      <div className="flex items-center justify-between">
        <h1 className="text-base font-semibold text-foreground">寻龙诀复盘</h1>
        {latest?.date && (
          <span className="text-[11px] font-mono text-muted bg-surface px-2 py-0.5 rounded border border-border">
            {latest.date}
          </span>
        )}
      </div>


        <div className="rounded-card border border-border bg-surface p-4 space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-[10px] font-medium text-muted">市况诊断 · F18</span>
            <RegimeBadge regime={latest?.market?.market_regime ?? null} />
          </div>
          <F18Bar rate={latest?.market?.f18_rate ?? null} numerator={latest?.market?.f18_numerator ?? null} denominator={latest?.market?.f18_denominator ?? null} lowSample={latest?.market?.f18_low_sample ?? null} />
          {latest?.market?.f18_risk_budget != null && (
            <div className="flex justify-between text-[10px]">
              <span className="text-muted">风险预算</span>
              <span className="font-mono tabular-nums text-muted">{latest.market.f18_risk_budget}</span>
            </div>
          )}
          {latest?.market?.f18_policy && (
            <div className="text-[10px] text-muted/70 truncate" title={latest.market.f18_policy}>
              {latest.market.f18_policy}
            </div>
          )}
        </div>

        <div className="rounded-card border border-border bg-surface p-4 space-y-1">
          <div className="text-[10px] font-medium text-muted mb-1">三大指数</div>
          <IndexCard name="上证" price={latest?.market?.sh_price ?? null} change={latest?.market?.sh_change != null ? latest.market.sh_change / 100 : null} />
          <IndexCard name="深证" price={latest?.market?.sz_price ?? null} change={latest?.market?.sz_change != null ? latest.market.sz_change / 100 : null} />
          <IndexCard name="创业板" price={latest?.market?.cy_price ?? null} change={latest?.market?.cy_change != null ? latest.market.cy_change / 100 : null} />
          <div className="border-t border-border/20 pt-1 mt-1">
            <div className="flex items-center justify-between py-1">
              <span className="text-[11px] text-muted">北向</span>
              <div className="text-right">
                <div className="text-xs font-mono tabular-nums text-foreground">
                  {latest?.market?.hgt_flow != null ? `${(latest.market.hgt_flow).toFixed(1)}亿` : '—'}
                </div>
              </div>
            </div>
          </div>
        </div>

      <div className="space-y-2">
        <div className="text-xs font-medium text-muted flex items-center gap-1.5">
          <TrendingUp className="h-3.5 w-3.5" />
          晋级率趋势</div>
        <TrendChartFallback />
      </div>

      <div className="space-y-2">
        <div className="text-[10px] font-medium text-muted">校准区</div>
        <CalibrationBuckets buckets={data?.calibration ?? []} />
      </div>

      <div className="space-y-3">
        <div className="text-xs font-medium text-muted flex items-center gap-1.5">
          <Award className="h-3.5 w-3.5" />
          候选股深度分析</div>
        {top5.length === 0 ? (
          <div className="text-[11px] text-muted/60 text-center py-8">暂无候选数据</div>
        ) : (
          <div className="space-y-3">
            {top5.map((c, i) => (
              <CandidateDeepCard key={c.code} candidate={c} rank={i + 1} />
            ))}
          </div>
        )}
      </div>

      <div className="space-y-2">
        <div className="text-xs font-medium text-muted flex items-center gap-1.5">
          <Search className="h-3.5 w-3.5" />
          挡板审计矩阵</div>
        <div className="rounded-card border border-border bg-surface p-4">
          <AuditMatrix candidates={candidates} />
        </div>
      </div>

      <div className="rounded-card border border-border bg-surface">
        <button
          onClick={() => setUziOpen(!uziOpen)}
          className="w-full flex items-center justify-between px-4 py-3 text-[11px] font-medium text-muted hover:text-foreground active:bg-accent/[0.02] transition-all"
        >
          <span className="flex items-center gap-1.5">
            <Target className="h-3.5 w-3.5" />
            UZI 智能评审</span>
          {uziOpen ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
        </button>
        {uziOpen && (
          <div className="px-4 pb-4 space-y-2">
            {data?.uzi_audit && data.uzi_audit.length > 0 ? (
              <table className="w-full text-[11px]">
                <thead>
                  <tr className="border-b border-border/30 text-muted">
                    <th className="py-1.5 text-left font-medium pr-2">股票</th>
                    <th className="py-1.5 text-left font-medium pr-2">评分</th>
                    <th className="py-1.5 text-left font-medium pr-2">价值</th>
                    <th className="py-1.5 text-left font-medium pr-2">动量</th>
                    <th className="py-1.5 text-left font-medium pr-2">风险</th>
                    <th className="py-1.5 text-left font-medium">判断</th>
                  </tr>
                </thead>
                <tbody>
                  {data.uzi_audit.map((a) => (
                    <tr key={`${a.date}_${a.code}`} className="border-b border-border/10">
                      <td className="py-1.5 pr-2 font-medium">{a.name} <span className="font-mono text-muted text-[9px]">{a.code}</span></td>
                      <td className="py-1.5 pr-2 font-mono tabular-nums">{(a.average_score ?? 0).toFixed(1)}</td>
                      <td className="py-1.5 pr-2">
                        <span className={cn(
                          'text-[10px] font-medium',
                          a.val_vote === '多头' ? 'text-bull' : a.val_vote === '空头' ? 'text-bear' : 'text-muted',
                        )}>{a.val_vote}</span>
                      </td>
                      <td className="py-1.5 pr-2">
                        <span className={cn(
                          'text-[10px] font-medium',
                          a.mom_vote === '多头' ? 'text-bull' : a.mom_vote === '空头' ? 'text-bear' : 'text-muted',
                        )}>{a.mom_vote}</span>
                      </td>
                      <td className="py-1.5 pr-2">
                        <span className={cn(
                          'text-[10px] font-medium',
                          a.risk_level === '安全' ? 'text-bull' : 'text-danger',
                        )}>{a.risk_level}</span>
                      </td>
                      <td className="py-1.5 text-muted/70 text-[10px] line-clamp-2">{a.summary}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <div className="text-[11px] text-muted/60 text-center py-4">暂无 UZI 评审数据</div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
RecapReview.displayName = 'RecapReview'
