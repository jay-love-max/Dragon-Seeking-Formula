import { useEffect, useState } from 'react'
import { RadioTower, Square, GitFork, Sparkles, type LucideIcon } from 'lucide-react'
import { storage } from './storage'

export interface BrandTheme {
  id: 'pulsar' | 'vanta' | 'helix' | 'aurora'
  name: string
  tagline: string
  hint: string
  icon: LucideIcon
  iconAccent: string                  // tailwind text color
  nameClass: string                   // typography style
  glow: string                        // hex color for glow/accents
  badgeClass: string                  // custom badge styling
}

export const BRAND_THEMES: Record<BrandTheme['id'], BrandTheme> = {
  pulsar: {
    id: 'pulsar',
    name: 'TickFlow Stock Panel',
    tagline: 'A-SHARE · SIGNAL TERMINAL',
    hint: '脉冲星、雷达波纹 — 青绿强调色，极简黑体，经典量化风格',
    icon: RadioTower,
    iconAccent: 'text-[#3DD68C]',
    nameClass: 'font-sans font-black text-sm tracking-[0.10em]',
    glow: '#3DD68C',
    badgeClass: 'bg-[#3DD68C]/10 text-[#3DD68C] border-[#3DD68C]/20',
  },
  vanta: {
    id: 'vanta',
    name: 'TickFlow Stock Panel',
    tagline: 'MARKET · INTELLIGENCE',
    hint: 'Vantablack — 纯白单色，极重字重，超宽字距，纯粹极简的高级感',
    icon: Square,
    iconAccent: 'text-[#FAFAFA]',
    nameClass: 'font-sans font-black text-sm tracking-[0.18em]',
    glow: '#FAFAFA',
    badgeClass: 'bg-white/10 text-white border-white/20',
  },
  helix: {
    id: 'helix',
    name: 'TickFlow Stock Panel',
    tagline: 'QUANT · TERMINAL',
    hint: 'DNA 螺旋 — 赛博紫色强调，等宽字体，专业量化与硬核开发气质',
    icon: GitFork,
    iconAccent: 'text-[#8B5CF6]',
    nameClass: 'font-mono font-bold text-sm tracking-[0.08em]',
    glow: '#8B5CF6',
    badgeClass: 'bg-[#8B5CF6]/10 text-[#8B5CF6] border-[#8B5CF6]/20',
  },
  aurora: {
    id: 'aurora',
    name: 'TickFlow Stock Panel',
    tagline: 'A-SHARE · DASHBOARD',
    hint: '极光 — 优雅青色强调，细字轻盈，与红绿涨跌无视觉冲突的自然设计',
    icon: Sparkles,
    iconAccent: 'text-[#22D3EE]',
    nameClass: 'font-sans font-light text-sm tracking-[0.12em]',
    glow: '#22D3EE',
    badgeClass: 'bg-[#22D3EE]/10 text-[#22D3EE] border-[#22D3EE]/20',
  },
}

const EVENT_NAME = 'tf-brand-theme-changed'

export function getActiveBrandTheme(): BrandTheme {
  const saved = storage.brandTheme.get('helix') as BrandTheme['id']
  if (saved && BRAND_THEMES[saved]) {
    return BRAND_THEMES[saved]
  }
  return BRAND_THEMES.helix // default to helix (purple)
}

export function setActiveBrandTheme(themeId: BrandTheme['id']) {
  if (BRAND_THEMES[themeId]) {
    storage.brandTheme.set(themeId)
    window.dispatchEvent(new CustomEvent(EVENT_NAME, { detail: themeId }))
  }
}

export function useBrandTheme() {
  const [theme, setTheme] = useState<BrandTheme>(getActiveBrandTheme)

  useEffect(() => {
    const handler = (e: Event) => {
      const themeId = (e as CustomEvent).detail as BrandTheme['id']
      if (BRAND_THEMES[themeId]) {
        setTheme(BRAND_THEMES[themeId])
      }
    }
    window.addEventListener(EVENT_NAME, handler)
    return () => window.removeEventListener(EVENT_NAME, handler)
  }, [])

  return [theme, setActiveBrandTheme] as const
}
