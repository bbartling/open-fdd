from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc

API_ROOT = Path(__file__).resolve().parents[2] / "workspace" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))


def test_run_hours_source_uses_pc_divide():
    script_path = (
        Path(__file__).resolve().parents[2]
        / "workspace"
        / "data"
        / "rules_py"
        / "ahu_run_hours.py"
    )
    code = script_path.read_text(encoding="utf-8")
    assert "pc.divide(pc.cast(delta, pa.int64()), 1_000_000)" in code
    assert "pc.cast(delta, pa.int64()) / 1_000_000" not in code


def test_dt_hours_chunked_array_divide_does_not_raise():
    from open_fdd.arrow_runtime.windows import arrow_shift

    base = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    ts = pa.array([base + timedelta(minutes=i) for i in range(4)], type=pa.timestamp("us", tz="UTC"))
    table = pa.table({"timestamp": ts})
    ts_col = "timestamp"
    prev = arrow_shift(table[ts_col], 1)
    delta = pc.subtract(pc.cast(table[ts_col], pa.timestamp("us", tz="UTC")), prev)
    secs = pc.divide(pc.cast(delta, pa.int64()), 1_000_000)
    hours = pc.divide(pc.cast(secs, pa.float64()), 3600.0)
    assert len(hours) == 4
    assert hours.to_pylist()[1] is not None
