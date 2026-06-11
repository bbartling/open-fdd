#!/usr/bin/env python3
"""Run an Arrow rule against a Feather telemetry file."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pyarrow as pa
import pyarrow.feather as feather

from open_fdd.arrow_runtime import run_arrow_rule

RULE = '''
from open_fdd.arrow_runtime.cookbook import flatline_1h_mask

def apply_faults_arrow(table, cfg, context=None):
    return flatline_1h_mask(table, cfg)
'''

def main() -> None:
    table = pa.table(
        {
            "timestamp": [f"2024-06-01T12:{i:02d}:00Z" for i in range(20)],
            "zone_t": [72.0] * 19 + [72.1],
        }
    )
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "zone.feather"
        feather.write_feather(table, path)
        loaded = feather.read_table(path)
        cfg = {"value_column": "zone_t", "flatline_tolerance": 0.05, "flatline_window_samples": 10}
        result = run_arrow_rule(RULE, loaded, cfg)
        print(json.dumps({"true_count": result.true_count, "errors": result.errors}))


if __name__ == "__main__":
    main()
