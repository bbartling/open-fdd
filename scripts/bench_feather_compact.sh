#!/usr/bin/env bash
# Quick local benchmark: pandas concat vs Arrow concat + parallel compact.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
VENV="${ROOT}/.venv"
export PYTHONPATH="${ROOT}:${ROOT}/workspace/api"
export OFDD_DESKTOP_DATA_DIR="${ROOT}/workspace/data"

"${VENV}/bin/python" - <<'PY'
import os
import shutil
import tempfile
import time
from pathlib import Path

import pandas as pd

from openfdd_bridge.feather_store import FeatherStore

tmp = Path(tempfile.mkdtemp(prefix="ofdd-bench-"))
try:
    store = FeatherStore(root=tmp / "feather_store")
    n_sites, n_shards, rows = 4, 6, 500
    for s in range(n_sites):
        for sh in range(n_shards):
            ts = pd.date_range("2025-01-01", periods=rows, freq="1min", tz="UTC")
            df = pd.DataFrame(
                {
                    "timestamp": ts,
                    "oa-t": range(rows),
                    "stat_zn-t": [x * 0.1 for x in range(rows)],
                    **{f"extra-{i}": range(rows) for i in range(20)},
                }
            )
            store.write_shard(df, source="bacnet", site_id=f"site-{s}")

    os.environ["OFDD_FEATHER_COMPACT_WORKERS"] = "1"
    t0 = time.perf_counter()
    r1 = store.compact_all(source="bacnet")
    t1 = time.perf_counter()

    # Re-shard and test column-pruned read
    for s in range(n_sites):
        store.write_shard(
            pd.DataFrame({"timestamp": pd.date_range("2026-01-01", periods=10, freq="1h", tz="UTC"), "oa-t": range(10)}),
            source="bacnet",
            site_id=f"site-{s}",
        )
    t2 = time.perf_counter()
    slim = store.read_site("site-0", source="bacnet", columns=["timestamp", "oa-t"])
    t3 = time.perf_counter()
    wide = store.read_site("site-0", source="bacnet")
    t4 = time.perf_counter()

    print("compact_all:", r1, f"{t1 - t0:.3f}s")
    print("read_site slim cols:", slim.shape if slim is not None else None, f"{t4 - t3:.3f}s")
    print("read_site all cols:", wide.shape if wide is not None else None, f"{t3 - t2:.3f}s")
finally:
    shutil.rmtree(tmp, ignore_errors=True)
PY
