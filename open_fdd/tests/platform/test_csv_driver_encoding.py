"""CSV driver accepts UTF-16 tab Grafana-style exports and exposes ts as time column."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from open_fdd.desktop.storage.feather_store import FeatherStore
from open_fdd.platform.drivers.csv_driver import ingest_csv_to_feather


def test_ingest_utf16_tab_with_ts_column(tmp_path: Path) -> None:
    pytest.importorskip("pyarrow")
    p = tmp_path / "grafana.tsv"
    # UTF-16 LE BOM + tab-separated header "ts" + one metric (Grafana-style export)
    lines = ["ts\tmetric_a", "2026-01-01 12:00:00\t1.5", "2026-01-01 13:00:00\t2.0"]
    p.write_bytes(b"\xff\xfe" + "\n".join(lines).encode("utf-16-le"))
    store = FeatherStore(root=tmp_path / "feather")
    out = ingest_csv_to_feather(csv_path=p, source="csv", site_id="s1", store=store)
    assert out.success is True
    assert out.rows == 2
    assert out.timestamp_column == "timestamp"
    assert "metric_a" in out.metric_columns
    assert out.preview_rows is not None
    assert len(out.preview_rows) == 2
    assert out.preview_rows[0].get("timestamp")


def test_read_utf8_comma_unchanged(tmp_path: Path) -> None:
    pytest.importorskip("pyarrow")
    p = tmp_path / "plain.csv"
    pd.DataFrame({"timestamp": ["2026-01-01T00:00:00Z"], "x": [1.0]}).to_csv(p, index=False)
    store = FeatherStore(root=tmp_path / "feather")
    out = ingest_csv_to_feather(csv_path=p, source="csv", site_id="s1", store=store)
    assert out.success is True
    assert out.rows == 1
    assert out.preview_rows and len(out.preview_rows) == 1
