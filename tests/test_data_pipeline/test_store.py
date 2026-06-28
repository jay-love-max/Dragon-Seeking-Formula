import os
import tempfile

import pandas as pd
import pytest

from data_pipeline.store import Store


@pytest.fixture
def store():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    s = Store(db_path)
    yield s
    s.close()
    os.unlink(db_path)


def test_store_creates_table(store):
    cursor = store.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in cursor.fetchall()]
    assert "realtime_snapshot" in tables


def test_store_upsert(store):
    df = pd.DataFrame({
        "code": ["600519"],
        "name": ["茅台"],
        "price": [1500.0],
        "turnover": [1.5],
        "quality_state": ["complete"],
        "missing_fields": [""],
    })
    store.write_snapshot(df)

    result = store.get_snapshot()
    assert "600519" in result
    assert result["600519"]["name"] == "茅台"
    assert result["600519"]["price"] == 1500.0
    assert result["600519"]["quality_state"] == "complete"

    df2 = pd.DataFrame({
        "code": ["600519"],
        "name": ["茅台"],
        "price": [1510.0],
        "turnover": [1.5],
        "quality_state": ["degraded"],
        "missing_fields": ["price"],
    })
    store.write_snapshot(df2)
    result = store.get_snapshot()
    assert result["600519"]["price"] == 1510.0
    assert result["600519"]["quality_state"] == "degraded"


def test_store_wal_mode(store):
    cursor = store.conn.execute("PRAGMA journal_mode")
    assert cursor.fetchone()[0].lower() == "wal"


def test_store_configures_writer_busy_timeout(store):
    cursor = store.conn.execute("PRAGMA busy_timeout")
    assert cursor.fetchone()[0] >= 10_000


def test_store_rejects_unknown_columns_instead_of_silently_dropping_batch(store):
    df = pd.DataFrame({"code": ["600519"], "unknown_metric": [1.0]})

    with pytest.raises(ValueError, match="unknown_metric"):
        store.write_snapshot(df)

    assert store.get_snapshot() == {}


def test_store_cleanup(store):
    df = pd.DataFrame({"code": ["600519"], "name": ["茅台"]})
    store.write_snapshot(df)
    store.cleanup()
    result = store.get_snapshot()
    assert len(result) == 0


def test_store_preserves_instant_ratio(store):
    df = pd.DataFrame(
        {
            "code": ["600519"],
            "name": ["茅台"],
            "price": [1500.0],
            "turnover": [1.5],
            "seal_funds": [50000000.0],
            "float_mcap": [2500000000.0],
        }
    )
    store.write_snapshot(df)
    result = store.get_snapshot()
    assert result["600519"]["seal_ratio_instant"] == 2.0


def test_store_persists_sector_limit_up_count(store):
    store.write_snapshot(
        pd.DataFrame(
            {
                "code": ["600519"],
                "name": ["茅台"],
                "sector_limit_ups": [5],
            }
        )
    )

    assert store.get_snapshot()["600519"]["sector_limit_ups"] == 5
