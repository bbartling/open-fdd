from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc

API_ROOT = Path(__file__).resolve().parents[2] / "workspace" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))


def test_run_hours_source_avoids_pyarrow_tz_cast():
    script_path = (
        Path(__file__).resolve().parents[2]
        / "workspace"
        / "data"
        / "rules_py"
        / "ahu_run_hours.py"
    )
    code = script_path.read_text(encoding="utf-8")
    assert "total_seconds() / 3600.0" in code
    assert 'pa.timestamp("us", tz="UTC")' not in code
    assert "pc.cast(delta, pa.int64()) / 1_000_000" not in code


def test_dt_hours_python_gap_logic():
    base = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    ts = pa.array([base + timedelta(minutes=i) for i in range(4)], type=pa.timestamp("us"))
    table = pa.table({"timestamp": ts})
    code = (
        Path(__file__).resolve().parents[2]
        / "workspace"
        / "data"
        / "rules_py"
        / "ahu_run_hours.py"
    ).read_text(encoding="utf-8")
    ns: dict = {"pa": pa, "pc": pc, "table": table, "cfg": {}}
    exec(compile(code, "ahu_run_hours.py", "exec"), ns, ns)  # noqa: S102
    assert ns["out"]["metrics"]["fan_run_hours"] >= 0
