from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

API_ROOT = Path(__file__).resolve().parents[2] / "workspace" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from openfdd_bridge.feather_store import FeatherStore  # noqa: E402


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FeatherStore:
    monkeypatch.setenv("OFDD_DESKTOP_DATA_DIR", str(tmp_path / "data"))
    return FeatherStore(root=tmp_path / "data" / "feather_store")


def _frame(start: str, periods: int) -> pd.DataFrame:
    ts = pd.date_range(start, periods=periods, freq="1h", tz="UTC")
    return pd.DataFrame({"timestamp": ts, "SAT": range(periods)})


def test_write_read_and_dedupe(store: FeatherStore):
    store.write_shard(_frame("2025-01-01", 5), source="bacnet", site_id="s1")
    store.write_shard(_frame("2025-01-01 02:00", 5), source="bacnet", site_id="s1")
    df = store.read_site("s1", source="bacnet")
    assert df is not None
    # Overlapping timestamps de-duplicated, sorted ascending.
    assert df["timestamp"].is_monotonic_increasing
    assert df["timestamp"].duplicated().sum() == 0


def test_list_sites(store: FeatherStore):
    store.write_shard(_frame("2025-01-01", 3), source="bacnet", site_id="s1")
    store.write_shard(_frame("2025-01-01", 3), source="weather", site_id="s2")
    sites = store.list_sites()
    assert {"source": "bacnet", "site_id": "s1"} in sites
    assert {"source": "weather", "site_id": "s2"} in sites


def test_compact_collapses_shards(store: FeatherStore):
    store.write_shard(_frame("2025-01-01", 3), source="bacnet", site_id="s1")
    store.write_shard(_frame("2025-01-02", 3), source="bacnet", site_id="s1")
    result = store.compact(source="bacnet", site_id="s1")
    assert result["rows"] == 6
    files = store.shard_files("bacnet", "s1")
    assert [f.name for f in files] == ["latest.feather"]


def test_prune_drops_old_rows(store: FeatherStore):
    old = _frame("2000-01-01", 5)
    recent = _frame(pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%d %H:%M"), 5)
    store.write_shard(old, source="bacnet", site_id="s1")
    store.write_shard(recent, source="bacnet", site_id="s1")
    result = store.prune(retention_days=30, source="bacnet")
    assert result["rows_dropped"] == 5
    df = store.read_site("s1", source="bacnet")
    assert df is not None
    assert len(df) == 5
