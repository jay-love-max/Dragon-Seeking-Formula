import type { Config } from 'tailwindcss'
import animate from 'tailwindcss-animate'

// 设计语言 §6.0:暗色为主 + 电光蓝强调 + 等宽数字
export default {
  darkMode: ['class'],
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    container: { center: true, padding: '1rem' },
    extend: {
      fontSize: {
        '2xs': 'var(--fs-xs)',
        xs: 'var(--fs-sm)',
        sm: 'var(--fs-base)',
        base: 'var(--fs-md)',
        lg: 'var(--fs-lg)',
        xl: 'var(--fs-xl)',
        '2xl': 'var(--fs-2xl)',
        '3xl': 'var(--fs-3xl)',
      },
      spacing: {
        '1': 'var(--space-1)',
        '2': 'var(--space-2)',
        '3': 'var(--space-3)',
        '4': 'var(--space-4)',
        '5': 'var(--space-5)',
        '6': 'var(--space-6)',
        '8': 'var(--space-8)',
      },
      colors: {
        // §6.0.1 色板 — CSS variables 见 src/index.css
        base:      'hsl(var(--base) / <alpha-value>)',
        surface:   'hsl(var(--surface) / <alpha-value>)',
        elevated:  'hsl(var(--elevated) / <alpha-value>)',
        border:    'hsl(var(--border) / <alpha-value>)',
        foreground: 'hsl(var(--fg-primary) / <alpha-value>)',
        secondary:  'hsl(var(--fg-secondary) / <alpha-value>)',
        muted:      'hsl(var(--fg-muted) / <alpha-value>)',
        accent:     'hsl(var(--accent) / <alpha-value>)',
        // A 股语义色:仅用于价格 / K 线,不用于 UI 状态
        bull:       'hsl(var(--bull) / <alpha-value>)',
        bear:       'hsl(var(--bear) / <alpha-value>)',
        warning:    'hsl(var(--warning) / <alpha-value>)',
        danger:     'hsl(var(--danger) / <alpha-value>)',
      },
      fontFamily: {
        sans: ['Inter', '"PingFang SC"', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', '"IBM Plex Mono"', 'ui-monospace', 'monospace'],
      },
      borderRadius: {
        card: '8px',
        btn: '6px',
        input: '4px',
        dialog: '12px',
      },
      transitionTimingFunction: {
        // §6.0.4 Linear/Vercel 同款缓动
        smooth: 'cubic-bezier(0.16, 1, 0.3, 1)',
      },
      boxShadow: {
        'glow-sm': '0 0 8px hsl(var(--accent) / 0.3)',
        'glow': '0 0 16px hsl(var(--accent) / 0.25)',
      },
      animation: {
        'pulse-glow': 'pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite',
      },
    },
  },
  plugins: [animate],
} satisfies Config
