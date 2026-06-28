"""Shared pytest fixtures and path setup for the dragon-seeking-formula test suite.

The `[tool.pytest.ini_options] pythonpath = ["src"]` in pyproject.toml already
puts `src/` on sys.path, so test modules can `import recap_engine` and
`from data_adapters import ...` directly. The helpers here provide isolated
database and adapter-state fixtures so tests never touch the real
`data/recap.db` or live network adapters.
"""
import sys
from pathlib import Path

import pytest

# Defensive: ensure src is importable even when pytest is invoked from a
# subdir or without the pyproject pythonpath (e.g. bare `unittest`).
SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    """Yield a fresh on-disk SQLite path and pin RECAP_DB_PATH to it.

    recap_engine reads the DB location via config.get_db_path() (env-backed),
    so setting the env var isolates every test from the real data/recap.db.
    Returns the db path string.
    """
    db_path = tmp_path / "test_recap.db"
    monkeypatch.setenv("RECAP_DB_PATH", str(db_path))
    # Refresh the module-level constant captured at import time, if present,
    # for any code path that still reads recap_engine.DB_PATH directly.
    try:
        import recap_engine
        recap_engine.DB_PATH = str(db_path)
    except Exception:
        pass
    yield str(db_path)
