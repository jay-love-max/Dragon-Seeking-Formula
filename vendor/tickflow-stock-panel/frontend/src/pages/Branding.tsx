import { motion } from 'framer-motion'
import {
  Star,
  LineChart,
  ScanSearch,
  History,
  Signal as SignalIcon,
  Eye,
  FileText,
} from 'lucide-react'
import { PageHeader } from '@/components/PageHeader'
import { useBrandTheme, BRAND_THEMES, type BrandTheme } from '@/lib/brand'

const MOCK_NAV = [
  { icon: Star, label: '自选' },
  { icon: LineChart, label: 'K 线' },
  { icon: ScanSearch, label: '策略' },
  { icon: History, label: '回测' },
  { icon: SignalIcon, label: '信号' },
  { icon: Eye, label: '监控' },
  { icon: FileText, label: '财务' },
]

export function Branding() {
  const [activeTheme, setTheme] = useBrandTheme()

  return (
    <>
      <PageHeader
        title="视觉风格选择"
        subtitle="选择你喜欢的系统品牌标识风格。选中的风格将立即应用到侧边栏及系统关键元素。"
      />

      <div className="px-8 py-6">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {Object.values(BRAND_THEMES).map((v) => (
            <Sample
              key={v.id}
              v={v}
              isActive={activeTheme.id === v.id}
              onSelect={() => setTheme(v.id)}
            />
          ))}
        </div>

        <div className="mt-8 rounded-card border border-border bg-surface p-5 text-sm text-secondary leading-relaxed max-w-2xl">
          <div className="font-medium text-foreground mb-2">如何应用？</div>
          点击上方任意风格卡片中的 <code className="font-mono text-accent">应用此风格</code> 按钮，即可将对应的字体、配色、图标和发光效果应用到系统的真实侧边栏。
        </div>
      </div>
    </>
  )
}

function Sample({
  v,
  isActive,
  onSelect,
}: {
  v: BrandTheme
  isActive: boolean
  onSelect: () => void
}) {
  const Icon = v.icon

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
      className={`rounded-card border overflow-hidden bg-base flex transition-all duration-200 ${
        isActive ? 'border-accent shadow-glow-sm' : 'border-border'
      }`}
    >
      {/* 模拟侧边栏 */}
      <div className="w-52 bg-surface border-r border-border flex flex-col shrink-0 select-none">
        {/* Logo 区 */}
        <div className="px-4 py-5 border-b border-border">
          <div className="flex items-center gap-2">
            <div
              className="grid place-items-center h-7 w-7 rounded-md"
              style={{
                background: `${v.glow}1a`,
                boxShadow: `0 0 12px ${v.glow}33`,
              }}
            >
              <Icon className={`h-4 w-4 ${v.iconAccent}`} />
            </div>
            <div className={`${v.nameClass} text-foreground leading-tight`}>
              <div>TickFlow</div>
              <div>Stock Panel</div>
            </div>
          </div>
          <div className="mt-2.5 text-[9px] uppercase tracking-[0.18em] text-secondary">
            {v.tagline}
          </div>
          <div
            className="mt-3 h-px"
            style={{
              background: `linear-gradient(90deg, ${v.glow}66, transparent)`,
            }}
          />
          <div className="mt-2 text-[10px] text-secondary">
            档位 · <span className={`text-[9px] px-1.5 py-0.5 rounded font-mono border font-medium ${v.badgeClass}`}>Pro</span>
          </div>
        </div>

        {/* 模拟导航 */}
        <nav className="px-2 py-3 space-y-0.5">
          {MOCK_NAV.slice(0, 5).map(({ icon: I, label }, i) => (
            <div
              key={label}
              className={`flex items-center gap-3 px-3 py-1.5 rounded-btn text-xs ${
                i === 0
                  ? 'bg-elevated text-foreground font-medium'
                  : 'text-foreground/80'
              }`}
            >
              <I className="h-3.5 w-3.5" />
              {label}
            </div>
          ))}
        </nav>
      </div>

      {/* 右侧说明 + 大字预览 */}
      <div className="flex-1 p-5 flex flex-col justify-between">
        <div>
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wider text-accent">{v.id}</span>
            {isActive && (
              <span className={`text-[9px] px-2 py-0.5 rounded-full border font-medium ${v.badgeClass}`}>
                当前激活
              </span>
            )}
          </div>
          <div className="mt-2 leading-relaxed text-xs text-secondary">
            {v.hint}
          </div>
        </div>

        <div>
          {/* 大字 wordmark 预览 */}
          <div className="mt-4 pt-4 border-t border-border">
            <div
              className={`${v.nameClass} text-foreground`}
              style={{
                textShadow: `0 0 16px ${v.glow}44`,
              }}
            >
              {v.name}
            </div>
            <div className="mt-1 text-[9px] uppercase tracking-[0.2em] text-secondary">
              {v.tagline}
            </div>
          </div>

          {/* 模拟一个数据卡片 */}
          <div className="mt-4 rounded-btn bg-surface border border-border px-3 py-1.5 flex items-baseline justify-between">
            <span className="text-[10px] text-secondary font-mono">600519.SH (贵州茅台)</span>
            <span className="font-mono text-xs font-semibold" style={{ color: v.glow }}>
              +1.85%
            </span>
          </div>

          {/* 应用按钮 */}
          <button
            onClick={onSelect}
            disabled={isActive}
            className={`mt-4 w-full py-2 px-3 rounded-btn text-xs font-medium transition-all duration-150 ${
              isActive
                ? 'bg-bear/10 text-bear border border-bear/20 cursor-default'
                : 'bg-accent/15 hover:bg-accent/25 text-accent border border-accent/20 active:scale-[0.98]'
            }`}
          >
            {isActive ? '✓ 已应用此风格' : '应用此风格'}
          </button>
        </div>
      </div>
    </motion.div>
  )
}
