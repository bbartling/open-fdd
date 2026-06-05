#!/usr/bin/env python3
"""End-to-end Feather read → Arrow rule → summary benchmark (compact)."""

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
from open_fdd.arrow_runtime.config import configure_arrow_runtime
from open_fdd.arrow_runtime.summary import summarize_arrow_run

RULE = """import pyarrow.compute as pc

def apply_faults_arrow(table, cfg, context=None):
    return pc.greater(table["zone_temp"], cfg["max_zone_temp"])
"""


def _make_table(rows: int, site: str) -> pa.Table:
    return pa.table(
        {
            "timestamp": [f"2026-01-01T00:{i % 60:02d}:00Z" for i in range(rows)],
            "site_id": [site] * rows,
            "zone_temp": [70.0 + (i % 10) for i in range(rows)],
        }
    )


def _bench(sites: int, rows_per_site: int, repeats: int) -> dict:
    configure_arrow_runtime()
    tables = [_make_table(rows_per_site, f"site_{i}") for i in range(sites)]
    merged = pa.concat_tables(tables) if len(tables) > 1 else tables[0]
    times = []
    flagged = 0
    for _ in range(repeats):
        t0 = time.perf_counter()
        result = run_arrow_rule(RULE, merged, {"max_zone_temp": 72})
        summary = summarize_arrow_run(merged, result.fault_mask, rule_id="e2e")
        times.append(time.perf_counter() - t0)
        flagged = summary["fault_rows"]
    total_ms = sum(times) / len(times) * 1000
    rows = merged.num_rows
    return {
        "sites": sites,
        "rows_per_site": rows_per_site,
        "total_rows": rows,
        "repeats": repeats,
        "total_ms": round(total_ms, 2),
        "rows_per_sec": round(rows / (total_ms / 1000), 1) if total_ms else 0,
        "fault_rows": flagged,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sites", type=int, default=1)
    parser.add_argument("--rows-per-site", type=int, default=100_000)
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--output", type=str, default="")
    args = parser.parse_args()
    payload = {
        "benchmark": "arrow_end_to_end",
        "result": _bench(args.sites, args.rows_per_site, args.repeats),
    }
    text = json.dumps(payload, indent=2)
    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
