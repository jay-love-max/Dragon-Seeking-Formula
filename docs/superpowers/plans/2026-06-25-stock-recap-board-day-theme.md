# stock-recap-board 日间/夜间双主题 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为复盘看板增加可持久化的日间 / 夜间双主题，默认日间采用米白纸感风格，保留现有深色主题。

**Architecture:** 主题状态只存在于前端视图层：Vue 维护 `themeMode`，`body` 根据主题挂载 `data-theme`，CSS 用同一套 token 在浅 / 深色之间切换。图表不单独写死颜色，而是从当前主题 token 读取坐标轴、网格、图例和数据线颜色。数据采集、SQLite、导出和复盘计算不改。

**Tech Stack:** `src/recap_engine.py` 里的 HTML 模板生成器、Vue 3、Chart.js、浏览器本地存储、生成后的 `index.html`。

---

### Task 1: Add theme state and persistence

**Files:**
- Modify: `src/recap_engine.py:1171-1415` (HTML/CSS shell)
- Modify: `src/recap_engine.py:2144-2198` (Vue setup state)
- Modify: `src/recap_engine.py:2508-2523` (LocalStorage helpers area if needed)

- [ ] **Step 1: Add the theme state shape**

```js
const themeMode = ref("system");
const resolvedTheme = computed(() => {
    if (themeMode.value === "system") {
        return window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
    }
    return themeMode.value;
});
```

- [ ] **Step 2: Persist and restore the choice**

```js
const loadTheme = () => {
    const storedTheme = localStorage.getItem("rtk_recap_theme");
    if (storedTheme === "system" || storedTheme === "light" || storedTheme === "dark") {
        themeMode.value = storedTheme;
    }
};

const saveTheme = () => {
    localStorage.setItem("rtk_recap_theme", themeMode.value);
};
```

- [ ] **Step 3: Bind the theme to `<body>`**

```js
const applyTheme = () => {
    document.body.dataset.theme = resolvedTheme.value;
    document.body.dataset.themeMode = themeMode.value;
};
```

- [ ] **Step 4: Initialize theme on mount and react to system change**

```js
onMounted(() => {
    loadTheme();
    applyTheme();
    const media = window.matchMedia("(prefers-color-scheme: light)");
    const onChange = () => {
        if (themeMode.value === "system") applyTheme();
    };
    media.addEventListener?.("change", onChange);
});

watch(themeMode, () => {
    saveTheme();
    applyTheme();
});
```

- [ ] **Step 5: Expose theme controls to the template**

```html
<select v-model="themeMode" class="console-input ..." aria-label="主题模式">
    <option value="system">跟随系统</option>
    <option value="light">日间主题</option>
    <option value="dark">夜间主题</option>
</select>
```

- [ ] **Step 6: Run a focused smoke check**

Run: `python -c "from src.recap_engine import generate_html; generate_html()"`
Expected: `index.html` is regenerated without Python errors and includes `rtk_recap_theme` / `data-theme` logic.

---

### Task 2: Add light-theme CSS overrides

**Files:**
- Modify: `src/recap_engine.py:1187-1313`

- [ ] **Step 1: Replace hardcoded global dark defaults with theme tokens**

```css
body {
    font-family: 'Inter', 'Geist', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: var(--app-bg);
    color: var(--app-text);
}

body[data-theme="dark"] {
    --app-bg: radial-gradient(circle at 50% 0%, rgba(244, 63, 94, 0.04) 0%, rgba(10, 11, 15, 0) 60%), #0a0b0e;
    --app-text: #94a3b8;
    --surface: rgba(17, 19, 24, 0.96);
    --surface-strong: rgba(13, 14, 18, 0.96);
    --border: rgba(255, 255, 255, 0.05);
    --muted: #8b9bb4;
}

body[data-theme="light"] {
    --app-bg: radial-gradient(circle at top left, rgba(194, 65, 12, 0.07), transparent 30%), radial-gradient(circle at top right, rgba(37, 99, 235, 0.06), transparent 30%), #f5f1e8;
    --app-text: #334155;
    --surface: rgba(255, 255, 255, 0.72);
    --surface-strong: rgba(255, 250, 240, 0.96);
    --border: rgba(31, 41, 55, 0.10);
    --muted: #64748b;
}
```

- [ ] **Step 2: Add theme-aware overrides for existing utility classes**

```css
body[data-theme="light"] #app [class*="bg-[#08090a]"],
body[data-theme="light"] #app [class*="bg-[#0e1013]"] {
    background-color: #fffaf0 !important;
}

body[data-theme="light"] #app [class*="text-[#8b9bb4]"],
body[data-theme="light"] #app [class*="text-gray-500"] {
    color: #64748b !important;
}
```

- [ ] **Step 3: Re-skin cards, inputs, scrollbars, and focus states**

```css
body[data-theme="light"] .console-card { background-color: var(--surface); border-color: var(--border); box-shadow: inset 0 1px 0 rgba(255,255,255,.65), 0 8px 24px rgba(15,23,42,.06); }
body[data-theme="light"] .console-input { background-color: var(--surface-strong); border-color: rgba(31,41,55,.10); box-shadow: inset 0 1px 2px rgba(15,23,42,.06); }
body[data-theme="light"] ::-webkit-scrollbar-thumb { background: #cbd5e1; }
```

- [ ] **Step 4: Verify the page still renders in dark mode**

Run: `python -c "from src.recap_engine import generate_html; generate_html()"`
Expected: the generated HTML still contains the dark theme defaults and no CSS syntax breakage.

---

### Task 3: Make Chart.js theme-aware

**Files:**
- Modify: `src/recap_engine.py:2667-2805`

- [ ] **Step 1: Add a theme color helper for charts**

```js
const getChartTheme = () => resolvedTheme.value === "light"
    ? {
        grid: "rgba(148, 163, 184, 0.18)",
        axis: "#64748b",
        promo: "#e11d48",
        promoFill: "rgba(225, 29, 72, 0.06)",
        limit: "#d97706"
    }
    : {
        grid: "rgba(255, 255, 255, 0.05)",
        axis: "#8b9bb4",
        promo: "#f43f5e",
        promoFill: "rgba(244, 63, 94, 0.03)",
        limit: "#f59e0b"
    };
```

- [ ] **Step 2: Use the helper in `initChart()`**

```js
const chartTheme = getChartTheme();
chartInstance = new Chart(ctx, {
    data: {
        datasets: [
            { borderColor: chartTheme.promo, backgroundColor: chartTheme.promoFill, ... },
            { borderColor: chartTheme.limit, ... }
        ]
    },
    options: {
        plugins: { legend: { labels: { color: chartTheme.axis } } },
        scales: {
            x: { grid: { color: chartTheme.grid }, ticks: { color: chartTheme.axis } },
            y1: { grid: { color: chartTheme.grid }, ticks: { color: chartTheme.promo } },
            y2: { grid: { drawOnChartArea: false }, ticks: { color: chartTheme.limit } }
        }
    }
});
```

- [ ] **Step 3: Recreate the chart when theme changes**

```js
watch(resolvedTheme, () => {
    nextTick(() => {
        if (chartInstance) {
            chartInstance.destroy();
            chartInstance = null;
        }
        initChart();
    });
});
```

- [ ] **Step 4: Regenerate the HTML after chart changes**

Run: `python -c "from src.recap_engine import generate_html; generate_html()"`
Expected: the chart config in the generated `index.html` reflects the theme-aware palette.

---

### Task 4: Browser smoke test and commit

**Files:**
- Verify: `index.html`
- Verify: `src/recap_engine.py`

- [ ] **Step 1: Open the generated page in a browser and toggle themes**

Expected checks:
- 日间主题 loads with 米白 background and lighter cards
- 夜间主题 restores the current dark control-room look
- Theme choice persists after refresh

- [ ] **Step 2: Confirm the chart remains readable in both themes**

Expected checks:
- x/y axes visible
- legend text readable
- line colors have sufficient contrast on both backgrounds

- [ ] **Step 3: Commit the implementation**

```bash
git add src/recap_engine.py index.html docs/superpowers/plans/2026-06-25-stock-recap-board-day-theme.md
git commit -m "feat: add day theme to recap board"
```
