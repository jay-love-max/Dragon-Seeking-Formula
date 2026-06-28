/**
 * 图表主题色 — 统一来源，所有 chart 组件从这儿读取。
 * 颜色值与 src/index.css 中的 CSS 变量一致：
 *   --bull ≈ #F04438, --bear ≈ #12B76A
 */
export const CHART = {
  bull: '#F04438',
  bear: '#12B76A',
  bullAlpha: 'rgba(240,68,56,0.4)',
  bearAlpha: 'rgba(18,183,106,0.4)',
  neutral: '#A1A1AA',
  text: '#A1A1AA',
  grid: 'rgba(255,255,255,0.04)',
  border: '#27272A',
  bg: 'transparent',
  accent: '#3B82F6',
  warning: '#F59E0B',
  purple: '#8B5CF6',
  yellow: '#FACC15',
  orange: '#F97316',
  cyan: '#22D3EE',
  ma5: '#A1A1AA',
  ma10: '#3B82F6',
  ma20: '#F97316',
  ma60: '#8B5CF6',
  vol5: '#FACC15',
  vol10: '#8B5CF6',
  label: '#8E8E96',
  sep: 'rgba(255,255,255,0.08)',
} as const
