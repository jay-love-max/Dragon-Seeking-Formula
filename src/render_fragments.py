VENDOR_ASSETS = (
    "assets/vendor/tailwind.min.js",
    "assets/vendor/vue.global.js",
    "assets/vendor/chart.umd.min.js",
    "assets/vendor/lucide.min.js",
)


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
