import importlib.util
import tempfile
from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
ENGINE_PATH = REPO_ROOT / "src" / "recap_engine.py"


class OfflineAssetsTest(unittest.TestCase):
    def test_generated_html_uses_local_vendor_assets(self):
        spec = importlib.util.spec_from_file_location("recap_engine", ENGINE_PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

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
