from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

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

