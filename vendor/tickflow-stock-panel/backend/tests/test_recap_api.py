from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.api import recap  # noqa: E402
from app.config import settings  # noqa: E402


class TestManualRecapRunEndpoint(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._orig_data_dir = settings.data_dir
        settings.data_dir = Path(self.tmp.name)

    def tearDown(self):
        settings.data_dir = self._orig_data_dir
        self.tmp.cleanup()

    def test_manual_run_is_disabled_by_default(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(recap.HTTPException) as ctx:
                recap.trigger_recap_run()
        self.assertEqual(ctx.exception.status_code, 403)

    def test_manual_run_rejects_when_lock_is_held(self):
        lock_path = Path(self.tmp.name) / ".recap_run.lock"
        lock_path.write_text(str(os.getpid()), encoding="utf-8")

        with patch.dict(os.environ, {"RECAP_MANUAL_RUN_ENABLED": "true"}):
            with patch.object(recap.subprocess, "run") as run_mock:
                result = recap.trigger_recap_run()

        run_mock.assert_not_called()
        self.assertFalse(result["ok"])
        self.assertEqual(result["returncode"], 409)
        self.assertIn("already running", result["stderr"])
        self.assertTrue(lock_path.exists())

    def test_manual_run_releases_stale_lock(self):
        lock_path = Path(self.tmp.name) / ".recap_run.lock"
        lock_path.write_text("999999", encoding="utf-8")

        with patch.dict(os.environ, {"RECAP_MANUAL_RUN_ENABLED": "true"}):
            with patch.object(
                recap.subprocess,
                "run",
                return_value=SimpleNamespace(returncode=0, stdout="done", stderr=""),
            ) as run_mock:
                result = recap.trigger_recap_run()

        run_mock.assert_called_once()
        self.assertTrue(result["ok"])
        self.assertEqual(result["returncode"], 0)
        self.assertEqual(result["stdout"], "done")
        self.assertFalse(lock_path.exists())
