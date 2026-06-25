import importlib.util
import sys
import tempfile
import types
from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
ENGINE_PATH = REPO_ROOT / "src" / "recap_engine.py"
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import render_fragments


def load_recap_engine_module():
    stubs = {
        "mootdx": types.ModuleType("mootdx"),
        "mootdx.quotes": types.ModuleType("mootdx.quotes"),
        "akshare": types.ModuleType("akshare"),
        "sklearn": types.ModuleType("sklearn"),
        "sklearn.ensemble": types.ModuleType("sklearn.ensemble"),
    }
    stubs["mootdx.quotes"].Quotes = object
    stubs["sklearn.ensemble"].RandomForestClassifier = object
    original = {name: sys.modules.get(name) for name in stubs}
    try:
        sys.modules.update(stubs)
        spec = importlib.util.spec_from_file_location("recap_engine", ENGINE_PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        for name, module in original.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


class OfflineAssetsTest(unittest.TestCase):
    def test_vendor_head_helper_is_local(self):
        html = render_fragments.render_vendor_head()
        self.assertIn('assets/vendor/tailwind.min.js', html)
        self.assertIn('assets/vendor/vue.global.js', html)
        self.assertIn('assets/vendor/chart.umd.min.js', html)
        self.assertIn('assets/vendor/lucide.min.js', html)
        self.assertNotIn('https://cdn.tailwindcss.com', html)

    def test_theme_runtime_helper_keeps_shared_palette(self):
        js = render_fragments.render_theme_runtime()
        self.assertIn('const themeMode = ref("system");', js)
        self.assertIn('const getChartTheme = () => {', js)
        self.assertIn('promoFill: "rgba(225, 29, 72, 0.06)"', js)
        self.assertIn('document.body.dataset.theme = theme;', js)

    def test_generated_html_uses_local_vendor_assets(self):
        module = load_recap_engine_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            html_path = Path(tmpdir) / "index.html"
            module.HTML_PATH = str(html_path)
            module.generate_html()
            html = html_path.read_text(encoding="utf-8")

        self.assertIn('src="assets/vendor/vue.global.js"', html)
        self.assertIn('src="assets/vendor/chart.umd.min.js"', html)
        self.assertIn('src="assets/vendor/lucide.min.js"', html)
        self.assertIn('src="assets/vendor/tailwind.min.js"', html)
        self.assertNotIn("https://cdn.tailwindcss.com", html)
        self.assertNotIn("https://unpkg.com/vue@3/dist/vue.global.js", html)
        self.assertNotIn("https://cdn.jsdelivr.net/npm/chart.js", html)
        self.assertNotIn("https://unpkg.com/lucide@latest", html)


if __name__ == "__main__":
    unittest.main()
