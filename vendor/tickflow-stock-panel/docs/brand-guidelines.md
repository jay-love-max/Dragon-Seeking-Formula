# TickFlow Stock Panel 品牌标识与视觉规范 (Brand Guidelines)

本规范定义了 **TickFlow Stock Panel (TickFlow 股票面板)** 的品牌标识、核心价值观、视觉要素以及四套内置主题的视觉规范，以确保软件界面、文档和宣传材料的品牌一致性。

---

## 1. 品牌定位与核心价值观 (Brand Positioning)

### 1.1 品牌释义
**TickFlow Stock Panel** 是一款为个人散户与量化交易爱好者量身定制的 A 股行情分析、策略回测与实时监控工作台。我们依托 TickFlow 优质数据源，旨在让高级量化分析能力触手可及。

### 1.2 核心价值观
* **精准与硬核 (Precision & Quant)**: 关注数据本质。界面排版偏向专业终端（Terminal）体验，数据展示精确、排版严谨，契合量化分析的科学属性。
* **极简与效率 (Minimalism & Efficiency)**: 拒绝无谓的视觉噪音。首选平铺的 Bento Grid 网格与高对比度排版，让交易者在毫秒级内获取关键信号。
* **高定与个性化 (Tailored Cyberpunk)**: 提供多种赛博朋克微光风格（Pulsar / Vanta / Helix / Aurora），让专业工具也能拥有极高格调与舒适感。

---

## 2. 品牌标志 (The Logo)

### 2.1 标志构成与寓意
TickFlow Logo 由**方括号 (Brackets)** 与 **K线实体 (Candlestick)** 融合而成：
* **外层方括号 `[ ]`**：代表终端边界、代码块、引用区间，赋予产品“量化与编程”的硬核属性。
* **内部影线与实体**：代表标准 K 线，上影线短、下影线长，呈 bullish 站稳形态，寓意在起伏的资金流中稳健前行。

```
  [  |  ]
  [ █   ]
  [ █   ]
  [  |  ]
```

### 2.2 React SVG 组件实现
标志应使用组件 `Logo.tsx` 动态渲染，支持继承父级字色 (`currentColor`)：

```typescript
// components/Logo.tsx
export function Logo({ className, size = 32, style }: LogoProps) {
  return (
    <svg viewBox="0 0 32 32" width={size} height={size} fill="none" className={className} style={style}>
      {/* 左括号 */}
      <path d="M10 4 L4 4 L4 28 L10 28" stroke="currentColor" strokeWidth="2" />
      {/* 右括号 */}
      <path d="M22 4 L28 4 L28 28 L22 28" stroke="currentColor" strokeWidth="2" />
      {/* 影线 */}
      <line x1="16" y1="7" x2="16" y2="25" stroke="currentColor" strokeWidth="1.5" strokeOpacity="0.6" />
      {/* 实体 */}
      <rect x="13" y="9" width="6" height="10" fill="currentColor" rx="0.5" />
    </svg>
  )
}
```

---

## 3. 视觉风格与主题色彩 (Brand Color Themes)

本系统默认采用**暗色调底色 (Dark Mode Base)**，通过引入四种不同的调性色彩，满足不同量化交易者的审美偏好：

### 3.1 核心主题色矩阵

| 主题 ID | 主题中文名 | 核心主色 (Hex) | 视觉特征 | 适用场景 |
| :--- | :--- | :--- | :--- | :--- |
| **pulsar** | 脉冲星 | `#3DD68C` | 青绿强调，如同雷达波纹，散发强烈生命力与监控感 | 实时短线监控、看盘终端 |
| **vanta** | 极黑 | `#FAFAFA` | 纯白单色，超大字距，经典 Monochrome 无彩色美学 | 极简主义、深夜静默分析 |
| **helix** (默认) | 双螺旋 | `#8B5CF6` | 赛博紫强调，等宽英文字体，量化开发者经典配色 | 策略编写、回测分析、主控台 |
| **aurora** | 极光 | `#22D3EE` | 轻盈青色强调，细体字，与 A股涨跌（红/绿）互不冲突 | 长线定投、财务深度检索 |

### 3.2 语义色彩标准 (Semantic Colors)
在界面设计中，必须严格区分**品牌色**与**交易语义色**，防止视觉混淆：
* **上涨 (Bullish)**: 采用 A 股传统红色 `#EF4444` (Red) 或 `#F87171`。
* **下跌 (Bearish)**: 采用 A 股传统绿色 `#10B981` (Emerald) 或 `#34D399`。
* **品牌强调 (Brand Accents)**: 仅在 Logo、侧边栏头部、激活页签、特色指示器上使用当前激活的主题色（如紫或青），功能按钮及状态文字禁止使用品牌色替代红绿语义。

---

## 4. 排版与字体系统 (Typography)

### 4.1 字体家族 (Font Families)
* **无衬线主字体 (Sans-serif)**: `Inter`, `-apple-system`, `BlinkMacSystemFont`, `Segoe UI`, `Microsoft YaHei`, sans-serif
  * 应用于导航、常规文字、按钮、表单和说明。
* **等宽数字/代码字体 (Monospace)**: `JetBrains Mono`, `SFMono-Regular`, `Consolas`, monospace
  * 应用于股票代码、价格数据、涨跌幅、回测统计指标以及策略编辑器。

### 4.2 字阶规范 (Font Scale)
* **大字预览**: `text-base` 至 `text-lg` (带 `tracking-[0.10em]` 至 `tracking-[0.18em]` 的字距微调)。
* **正文**: `text-sm` (用于表格数据、设置选项)。
* **次要辅助字**: `text-xs` (用于股票代码、副标题、标签)。
* **数字大字报**: `text-2xl` 至 `text-3xl` font-mono (用于回测年化收益率、最大回撤等大指标)。

---

## 5. UI 交互设计规范 (UI & Interaction)

* **微发光 (Glow-Effect)**:
  在暗色背景下，Logo 与激活元素可使用当前主题色的半透明 drop-shadow，例如：
  `drop-shadow-[0_0_8px_rgba(brand-color,0.4)]`。
* **网格分割线 (Borders)**:
  使用统一的暗灰细线（`border-border`，通常为 `#27272a`），圆角采用微小圆角设计（`rounded-btn` 为 6px，`rounded-card` 为 10px），保持界面的精密感与紧凑感。
* **动效控制 (Transitions)**:
  导航切换与卡片悬停采用贝塞尔曲线过渡 `transition-all duration-150 ease-smooth`，避免拖泥带水的长动效，力求“瞬时响应”。
