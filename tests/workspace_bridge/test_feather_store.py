from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

API_ROOT = Path(__file__).resolve().parents[2] / "workspace" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from openfdd_bridge.feather_store import (  # noqa: E402
    FeatherStore,
    _shard_epoch_ms,
    feather_compact_on_ingest_from_env,
    feather_max_gib_from_env,
    maintain_storage,
    maintain_storage_if_needed,
)


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FeatherStore:
    monkeypatch.setenv("OFDD_DESKTOP_DATA_DIR", str(tmp_path / "data"))
    return FeatherStore(root=tmp_path / "data" / "feather_store")


def _frame(start: str, periods: int, *, col: str = "SAT") -> pd.DataFrame:
    ts = pd.date_range(start, periods=periods, freq="1h", tz="UTC")
    return pd.DataFrame({"timestamp": ts, col: range(periods)})


def _large_frame(start: str, periods: int, width: int = 40) -> pd.DataFrame:
    ts = pd.date_range(start, periods=periods, freq="1min", tz="UTC")
    data = {"timestamp": ts}
    for i in range(width):
        data[f"col-{i:02d}"] = [float((i + 1) * j) for j in range(periods)]
    return pd.DataFrame(data)


def test_write_read_and_dedupe(store: FeatherStore):
    store.write_shard(_frame("2025-01-01", 5), source="bacnet", site_id="s1")
    store.write_shard(_frame("2025-01-01 02:00", 5), source="bacnet", site_id="s1")
    df = store.read_site("s1", source="bacnet")
    assert df is not None
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


def test_prune_drops_old_rows(store: FeatherStore, monkeypatch: pytest.MonkeyPatch):
    anchor = pd.Timestamp("2026-05-30 12:00:00", tz="UTC")
    monkeypatch.setattr(
        "openfdd_bridge.feather_store.pd.Timestamp.now",
        lambda tz=None: anchor if tz is not None else anchor.tz_localize(None),
    )
    old = _frame("2000-01-01", 5)
    recent = _frame("2026-05-30 08:00", 5)
    store.write_shard(old, source="bacnet", site_id="s1")
    store.write_shard(recent, source="bacnet", site_id="s1")
    result = store.prune(retention_days=30, source="bacnet")
    assert result["rows_dropped"] == 5
    df = store.read_site("s1", source="bacnet")
    assert df is not None
    assert len(df) == 5


def test_write_shard_unique_when_same_millisecond(store: FeatherStore, monkeypatch: pytest.MonkeyPatch):
    fixed = 1_700_000_000.0
    monkeypatch.setattr("openfdd_bridge.feather_store.time.time", lambda: fixed)
    p1 = store.write_shard(_frame("2025-01-01", 2), source="bacnet", site_id="s1")
    p2 = store.write_shard(_frame("2025-01-02", 2), source="bacnet", site_id="s1")
    assert p1 != p2
    assert len(store.shard_files("bacnet", "s1")) == 2


def test_total_bytes_sums_feather_files(store: FeatherStore):
    store.write_shard(_frame("2025-01-01", 10), source="bacnet", site_id="s1")
    store.write_shard(_frame("2025-01-02", 10), source="bacnet", site_id="s1")
    total = store.total_bytes()
    assert total > 0
    assert total == sum(p.stat().st_size for p in store.root.rglob("*.feather"))


def test_shard_epoch_ms_parsing():
    assert _shard_epoch_ms("shard-1700000000123-ab12cd34.feather") == 1700000000123
    assert _shard_epoch_ms("latest.feather") is None


def test_enforce_max_deletes_oldest_loose_shard_first(store: FeatherStore, monkeypatch: pytest.MonkeyPatch):
    times = iter([1_700_000_000.0, 1_800_000_000.0])
    monkeypatch.setattr("openfdd_bridge.feather_store.time.time", lambda: next(times))

    old_path = store.write_shard(_frame("2020-01-01", 20), source="bacnet", site_id="s1")
    new_path = store.write_shard(_frame("2025-06-01", 20), source="bacnet", site_id="s1")
    before = store.total_bytes()
    old_size = old_path.stat().st_size
    assert old_path.exists() and new_path.exists()

    target = before - old_size + 1
    result = store.enforce_max_bytes(target)
    assert result["shards_deleted"] >= 1
    assert not old_path.exists()
    assert new_path.exists()
    assert store.total_bytes() <= target


def test_enforce_max_trims_latest_in_time_chunks(store: FeatherStore):
    wide = _large_frame("2020-01-01", 24 * 7, width=60)
    site = store.site_dir("bacnet", "s1")
    site.mkdir(parents=True, exist_ok=True)
    latest = site / "latest.feather"
    wide.to_feather(latest)

    before_rows = len(pd.read_feather(latest))
    before_bytes = store.total_bytes()
    # Trim one 24h chunk — target slightly below current size.
    target = max(1, int(before_bytes * 0.85))
    result = store.enforce_max_bytes(target, trim_chunk_hours=24)
    assert result["trim_passes"] >= 1
    assert result["rows_trimmed"] > 0
    assert latest.is_file()
    after_rows = len(pd.read_feather(latest))
    assert after_rows < before_rows
    assert store.total_bytes() <= before_bytes


def test_enforce_max_noop_when_under_limit(store: FeatherStore):
    store.write_shard(_frame("2025-01-01", 5), source="bacnet", site_id="s1")
    total = store.total_bytes()
    result = store.enforce_max_bytes(total + 10_000)
    assert result["bytes_freed"] == 0
    assert result["shards_deleted"] == 0
    assert result["after_bytes"] == total


def test_enforce_max_skipped_when_max_bytes_zero(store: FeatherStore):
    store.write_shard(_frame("2025-01-01", 5), source="bacnet", site_id="s1")
    result = store.enforce_max_bytes(0)
    assert result.get("skipped") == "max_bytes<=0"


def test_maintain_runs_prune_and_enforce(store: FeatherStore, monkeypatch: pytest.MonkeyPatch):
    anchor = pd.Timestamp("2026-05-30 12:00:00", tz="UTC")
    monkeypatch.setattr(
        "openfdd_bridge.feather_store.pd.Timestamp.now",
        lambda tz=None: anchor if tz is not None else anchor.tz_localize(None),
    )
    store.write_shard(_frame("2000-01-01", 5), source="bacnet", site_id="s1")
    store.write_shard(_frame("2026-05-30 08:00", 5), source="bacnet", site_id="s1")
    total = store.total_bytes()

    out = maintain_storage(
        retention_days=30,
        max_gib=total / (1024**3),
        trim_chunk_hours=24,
        store=store,
    )
    assert out["prune"]["rows_dropped"] == 5
    assert "enforce_max" in out
    assert out["after_bytes"] <= total


def test_maintain_storage_if_needed_only_when_over_cap(store: FeatherStore, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OFDD_FEATHER_MAX_GIB", "0")
    store.write_shard(_frame("2025-01-01", 5), source="bacnet", site_id="s1")
    assert maintain_storage_if_needed(store) is None

    total = store.total_bytes()
    monkeypatch.setenv("OFDD_FEATHER_MAX_GIB", str(total / (1024**3) + 0.001))
    assert maintain_storage_if_needed(store) is None

    monkeypatch.setenv("OFDD_FEATHER_MAX_GIB", str(max(0.000001, (total - 100) / (1024**3))))
    result = maintain_storage_if_needed(store)
    assert result is not None
    assert result.get("trigger") == "over_limit"


def test_feather_max_gib_from_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OFDD_FEATHER_MAX_GIB", "12.5")
    assert feather_max_gib_from_env() == 12.5
    monkeypatch.delenv("OFDD_FEATHER_MAX_GIB", raising=False)
    assert feather_max_gib_from_env() == 0.0


def test_read_site_merges_mixed_numeric_shard_types(store: FeatherStore):
    """Regression: BACnet ingest may write int64 in one shard and float64 in another."""
    t1 = pd.DataFrame(
        {
            "timestamp": pd.date_range("2025-01-01", periods=3, freq="1h", tz="UTC"),
            "web-oat-t": [1.0, 2.0, 3.0],
        }
    )
    t2 = pd.DataFrame(
        {
            "timestamp": pd.date_range("2025-01-01 03:00", periods=3, freq="1h", tz="UTC"),
            "web-oat-t": [4, 5, 6],
        }
    )
    store.write_shard(t1, source="bacnet", site_id="s1")
    store.write_shard(t2, source="bacnet", site_id="s1")
    df = store.read_site("s1", source="bacnet")
    assert df is not None
    assert len(df) == 6
    assert "web-oat-t" in df.columns


def test_read_site_column_prune(store: FeatherStore):
    wide = _large_frame("2025-01-01", 20, width=30)
    store.write_shard(wide, source="bacnet", site_id="s1")
    slim = store.read_site("s1", source="bacnet", columns=["timestamp", "col-00"])
    assert slim is not None
    assert list(slim.columns) == ["timestamp", "col-00"]


def test_compact_all_parallel(store: FeatherStore, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OFDD_FEATHER_COMPACT_WORKERS", "2")
    for sid in ("a", "b"):
        store.write_shard(_frame("2025-01-01", 4), source="bacnet", site_id=sid)
        store.write_shard(_frame("2025-01-03", 4), source="bacnet", site_id=sid)
    out = store.compact_all(source="bacnet")
    assert out["sites"] == 2
    assert out["workers"] == 2
    for sid in ("a", "b"):
        assert [p.name for p in store.shard_files("bacnet", sid)] == ["latest.feather"]


def test_maybe_compact_after_ingest_threshold(store: FeatherStore, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("OFDD_FEATHER_COMPACT_ON_INGEST", raising=False)
    monkeypatch.setenv("OFDD_FEATHER_COMPACT_SHARD_THRESHOLD", "3")
    assert feather_compact_on_ingest_from_env() is False
    for _ in range(2):
        store.write_shard(_frame("2025-01-01", 2), source="bacnet", site_id="s1")
    assert store.maybe_compact_after_ingest(source="bacnet", site_id="s1") is None
    store.write_shard(_frame("2025-01-02", 2), source="bacnet", site_id="s1")
    result = store.maybe_compact_after_ingest(source="bacnet", site_id="s1")
    assert result is not None
    assert result["rows"] >= 4
