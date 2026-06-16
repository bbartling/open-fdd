"""Feather shard concat tolerates mixed numeric dtypes."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.feather as feather

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "workspace" / "api"))

from openfdd_bridge.feather_store import FeatherStore, _concat_arrow_tables  # noqa: E402


def test_concat_arrow_tables_promotes_int_and_float(tmp_path):
    t1 = pa.table({"timestamp": [1, 2], "web-oat-t": pa.array([32, 33], type=pa.int64())})
    t2 = pa.table({"timestamp": [3, 4], "web-oat-t": pa.array([34.5, 35.0], type=pa.float64())})
    merged = _concat_arrow_tables([t1, t2])
    assert merged.num_rows == 4
    assert pa.types.is_floating(merged.schema.field("web-oat-t").type)


def test_read_site_table_merges_mixed_shards(tmp_path, monkeypatch):
    store = FeatherStore(root=tmp_path / "feather_store")
    site = store.site_dir("json_api", "acme")
    site.mkdir(parents=True)
    df1 = pd.DataFrame({"timestamp": pd.to_datetime(["2025-01-01"], utc=True), "web-oat-t": [40]})
    df2 = pd.DataFrame({"timestamp": pd.to_datetime(["2025-01-02"], utc=True), "web-oat-t": [41.2]})
    feather.write_feather(pa.Table.from_pandas(df1), site / "shard-1.feather")
    feather.write_feather(pa.Table.from_pandas(df2), site / "shard-2.feather")
    out = store.read_site("acme", source="json_api")
    assert out is not None
    assert len(out) == 2
    assert float(out["web-oat-t"].iloc[-1]) == 41.2
