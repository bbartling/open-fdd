from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from open_fdd.desktop.column_utils import dedupe_dataframe_columns
from open_fdd.desktop.storage.feather_store import FeatherStore


def test_feather_store_roundtrip(tmp_path: Path) -> None:
    pytest.importorskip("pyarrow")
    store = FeatherStore(root=tmp_path / "feather")
    frame = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(["2026-01-01T00:00:00Z", "2026-01-01T01:00:00Z"], utc=True),
            "value": [1.0, 2.0],
        }
    )
    out = store.write_frame(source="csv", site_id="site-1", frame=frame)
    assert out.exists()
    merged = store.read_site_frames(source="csv", site_id="site-1")
    assert len(merged.index) == 2
    assert "value" in merged.columns


def test_feather_store_read_multiple_files_keeps_unique_columns(tmp_path: Path) -> None:
    pytest.importorskip("pyarrow")
    store = FeatherStore(root=tmp_path / "feather")
    t = pd.Timestamp("2026-01-01T00:00:00Z", tz="UTC")
    frame = pd.DataFrame({"timestamp": [t], "value": [1.0]})
    store.write_frame(source="csv", site_id="site-1", frame=frame)
    store.write_frame(source="csv", site_id="site-1", frame=frame)
    merged = store.read_site_frames(source="csv", site_id="site-1")
    assert merged.columns.is_unique
    assert len(merged.index) == 2


def test_dedupe_dataframe_columns_renames_duplicate_labels() -> None:
    """``read_site_frames`` relies on :func:`dedupe_dataframe_columns` when concat yields duplicate headers."""
    dup = pd.DataFrame([[1, 2, 3]], columns=["timestamp", "value", "value"])
    out = dedupe_dataframe_columns(dup)
    assert out.columns.is_unique
    assert list(out.columns) == ["timestamp", "value", "value__1"]


def test_feather_store_stats_and_targeted_purge(tmp_path: Path) -> None:
    pytest.importorskip("pyarrow")
    store = FeatherStore(root=tmp_path / "feather")
    frame = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(["2026-01-01T00:00:00Z"], utc=True),
            "value": [1.0],
        }
    )
    store.write_frame(source="csv", site_id="site-1", frame=frame)
    store.write_frame(source="csv", site_id="site-2", frame=frame)
    store.write_frame(source="weather", site_id="site-1", frame=frame)

    stats_before = store.stats()
    assert stats_before["file_count"] == 3
    assert stats_before["source_count"] == 2
    assert stats_before["site_count"] == 3
    assert stats_before["bytes_total"] > 0

    purged = store.purge(source="csv", site_id="site-1")
    assert purged["files_deleted"] == 1
    assert purged["bytes_deleted"] > 0

    stats_after = store.stats()
    assert stats_after["file_count"] == 2
    assert stats_after["source_count"] == 2

