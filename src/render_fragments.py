VENDOR_ASSETS = (
    "assets/vendor/tailwind.min.js",
    "assets/vendor/vue.global.js",
    "assets/vendor/chart.umd.min.js",
    "assets/vendor/lucide.min.js",
)

THEME_STYLE_RULES = """        body[data-theme=\"light\"] {
            background: radial-gradient(circle at top left, rgba(194, 65, 12, 0.07) 0%, rgba(194, 65, 12, 0) 28%), radial-gradient(circle at top right, rgba(37, 99, 235, 0.06) 0%, rgba(37, 99, 235, 0) 30%), #f5f1e8;
            color: #334155;
        }
        body[data-theme=\"light\"]::before {
            opacity: 0.03;
        }
        body[data-theme=\"light\"] ::-webkit-scrollbar-track {
            background: #f5f1e8;
        }
        body[data-theme=\"light\"] ::-webkit-scrollbar-thumb {
            background: #cbd5e1;
        }
        body[data-theme=\"light\"] ::-webkit-scrollbar-thumb:hover {
            background: #94a3b8;
        }
        body[data-theme=\"light\"] .console-card {
            background-color: rgba(255, 255, 255, 0.78);
            background-image: linear-gradient(180deg, rgba(255, 255, 255, 0.74), rgba(255, 255, 255, 0.52));
            border-color: rgba(31, 41, 55, 0.10);
            box-shadow:
                inset 0 1px 0 0 rgba(255, 255, 255, 0.65),
                0 8px 24px 0 rgba(15, 23, 42, 0.06);
        }
        body[data-theme=\"light\"] .console-card:hover {
            border-color: rgba(194, 65, 12, 0.20);
            box-shadow:
                inset 0 1px 0 0 rgba(255, 255, 255, 0.72),
                0 16px 36px 0 rgba(15, 23, 42, 0.08);
        }
        body[data-theme=\"light\"] .console-input {
            background-color: rgba(255, 250, 240, 0.96);
            border-color: rgba(31, 41, 55, 0.10);
            box-shadow: inset 0 1px 2px 0 rgba(15, 23, 42, 0.06);
        }
        body[data-theme=\"light\"] .console-input:focus {
            border-color: rgba(194, 65, 12, 0.45);
            box-shadow:
                inset 0 1px 2px 0 rgba(15, 23, 42, 0.06),
                0 0 16px 0 rgba(194, 65, 12, 0.10);
        }
        body[data-theme=\"light\"] #app [class*=\"border-[#1e222b]\"] {
            border-color: rgba(31, 41, 55, 0.10) !important;
        }
        body[data-theme=\"light\"] #app [class*=\"border-[#1e222b]/80\"] {
            border-color: rgba(31, 41, 55, 0.08) !important;
        }
        body[data-theme=\"light\"] #app [class*=\"border-[#1e222b]/60\"] {
            border-color: rgba(31, 41, 55, 0.06) !important;
        }
        body[data-theme=\"light\"] #app [class*=\"border-[#1e222b]/20\"] {
            border-color: rgba(31, 41, 55, 0.04) !important;
        }
        body[data-theme=\"light\"] #app [class*=\"divide-[#1e222b]\"] > * + * {
            border-color: rgba(31, 41, 55, 0.10) !important;
        }
        body[data-theme=\"light\"] #app [class*=\"bg-[#08090a]\"] {
            background-color: #fffaf0 !important;
        }
        body[data-theme=\"light\"] #app [class*=\"bg-[#0e1013]\"] {
            background-color: #fffdf8 !important;
        }
        body[data-theme=\"light\"] #app [class*=\"bg-[#0\"],
        body[data-theme=\"light\"] #app [class*=\"bg-[#1\"] {
            background-color: #fffaf0 !important;
        }
        body[data-theme=\"light\"] #app [class*=\"border-[#1\"],
        body[data-theme=\"light\"] #app [class*=\"border-[#2\"] {
            border-color: rgba(31, 41, 55, 0.10) !important;
        }
        body[data-theme=\"light\"] #app [class*=\"text-[#9aa8be]\"] {
            color: #64748b !important;
        }
        body[data-theme=\"light\"] #app [class*=\"text-[#d1d5db]\"] {
            color: #334155 !important;
        }
        body[data-theme=\"light\"] #app [class*=\"text-[#8b9bb4]\"] {
            color: #64748b !important;
        }
        body[data-theme=\"light\"] #app [class*=\"text-gray-500\"] {
            color: #64748b !important;
        }
        body[data-theme=\"light\"] #app [class*=\"text-gray-400\"] {
            color: #94a3b8 !important;
        }
        body[data-theme=\"light\"] #app [class*=\"text-gray-600\"] {
            color: #475569 !important;
        }
        body[data-theme=\"light\"] #app [class*=\"text-white\"] {
            color: #0f172a !important;
        }
        body[data-theme=\"light\"] #app [class*=\"hover:border-red-500/20\"]:hover {
            border-color: rgba(194, 65, 12, 0.20) !important;
        }
        body[data-theme=\"light\"] #app [class*=\"hover:bg-[#1d212b]/20\"]:hover {
            background-color: rgba(194, 65, 12, 0.04) !important;
        }
        body[data-theme=\"light\"] #app [class*=\"bg-red-950/40\"],
        body[data-theme=\"light\"] #app [class*=\"bg-red-950\"] {
            background-color: rgba(194, 65, 12, 0.10) !important;
            border-color: rgba(194, 65, 12, 0.25) !important;
            color: #c2410c !important;
            border-radius: 2px !important;
        }
        body[data-theme=\"light\"] #app select,
        body[data-theme=\"light\"] #app input[type=\"text\"] {
            background-color: #fffaf0 !important;
            border-color: rgba(31, 41, 55, 0.10) !important;
            color: #0f172a !important;
        }
        body[data-theme=\"light\"] #app select:focus-visible,
        body[data-theme=\"light\"] #app input[type=\"text\"]:focus-visible {
            outline-color: rgba(194, 65, 12, 0.22);
        }"""


def render_vendor_head() -> str:
    return "\n".join(
        [
            "    <!-- Local vendor assets for offline-friendly rendering -->",
            f'    <script src="{VENDOR_ASSETS[0]}"></script>',
            "    <!-- Vue 3 -->",
            f'    <script src="{VENDOR_ASSETS[1]}"></script>',
            "    <!-- Chart.js -->",
            f'    <script src="{VENDOR_ASSETS[2]}"></script>',
            "    <!-- Lucide Icons -->",
            f'    <script src="{VENDOR_ASSETS[3]}"></script>',
        ]
    )


def render_theme_styles() -> str:
    return THEME_STYLE_RULES


def render_theme_runtime() -> str:
    return """                const themeMediaQuery = window.matchMedia("(prefers-color-scheme: light)");
                const themeStorageKey = "rtk_recap_theme";
                const prefersLight = ref(themeMediaQuery.matches);
                const themeMode = ref("system");
                const resolvedTheme = computed(() => {
                    if (themeMode.value === "light" || themeMode.value === "dark") {
                        return themeMode.value;
                    }
                    return prefersLight.value ? "light" : "dark";
                });
                const loadTheme = () => {
                    try {
                        const storedTheme = localStorage.getItem(themeStorageKey);
                        if (storedTheme === "system" || storedTheme === "light" || storedTheme === "dark") {
                            themeMode.value = storedTheme;
                        }
                    } catch (error) {}
                };
                const saveTheme = () => {
                    try {
                        localStorage.setItem(themeStorageKey, themeMode.value);
                    } catch (error) {}
                };
                const applyTheme = () => {
                    const theme = resolvedTheme.value;
                    document.body.dataset.theme = theme;
                    document.documentElement.dataset.theme = theme;
                    document.body.dataset.themeMode = themeMode.value;
                    document.documentElement.dataset.themeMode = themeMode.value;
                };
                const syncSystemTheme = (event) => {
                    prefersLight.value = event.matches;
                };
                const getChartTheme = () => {
                    if (resolvedTheme.value === "light") {
                        return {
                            grid: "rgba(148, 163, 184, 0.18)",
                            axis: "#64748b",
                            promo: "#e11d48",
                            promoFill: "rgba(225, 29, 72, 0.06)",
                            limit: "#d97706"
                        };
                    }
                    return {
                        grid: "rgba(255, 255, 255, 0.05)",
                        axis: "#8b9bb4",
                        promo: "#f43f5e",
                        promoFill: "rgba(244, 63, 94, 0.03)",
                        limit: "#f59e0b"
                    };
                };
                loadTheme();
                applyTheme();"""
