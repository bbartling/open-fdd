#!/usr/bin/env python3
"""Compact Arrow-native rule benchmarks (CI smoke + local profiling)."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import pyarrow as pa
import pyarrow.compute as pc

from open_fdd.arrow_runtime.backend import run_arrow_rule
from open_fdd.arrow_runtime.config import configure_arrow_runtime, get_arrow_runtime_config
from open_fdd.arrow_runtime.testing import sample_hvac_table

RULES = {
    "threshold": """import pyarrow.compute as pc

def apply_faults_arrow(table, cfg, context=None):
    return pc.greater(table["zone_temp"], cfg["max_zone_temp"])
""",
    "fan_no_airflow": """import pyarrow.compute as pc

def apply_faults_arrow(table, cfg, context=None):
    fan_on = pc.greater(table["fan_cmd"], 0.5)
    low = pc.less(table["airflow_cfm"], 500)
    return pc.and_(fan_on, low)
""",
}


def _bench(rows: int, repeats: int) -> dict:
    configure_arrow_runtime()
    rt = get_arrow_runtime_config()
    table = sample_hvac_table(rows, seed=42)
    cfg = {"max_zone_temp": 72.0}
    results = []
    for name, code in RULES.items():
        times: list[float] = []
        true_count = 0
        for _ in range(repeats):
            t0 = time.perf_counter()
            out = run_arrow_rule(code, table, cfg, rule_id=name)
            times.append(time.perf_counter() - t0)
            true_count = out.true_count
        total_ms = sum(times) / len(times) * 1000
        results.append(
            {
                "rule": name,
                "rows": rows,
                "repeats": repeats,
                "total_ms": round(total_ms, 2),
                "rows_per_sec": round(rows / (total_ms / 1000), 1) if total_ms else 0,
                "true_count": true_count,
                "arrow_cpu_threads": rt.cpu_threads,
                "arrow_io_threads": rt.io_threads,
                "batch_rows": rt.batch_rows,
            }
        )
    return {"benchmark": "arrow_native", "results": results}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", nargs="+", type=int, default=[10_000, 100_000])
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--output", type=str, default="")
    args = parser.parse_args()
    payload = {"suites": [_bench(r, args.repeats) for r in args.rows]}
    text = json.dumps(payload, indent=2)
    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
