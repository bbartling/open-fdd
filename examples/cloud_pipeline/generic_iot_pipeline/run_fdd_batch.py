#!/usr/bin/env python3
"""Batch FDD: fake IoT source → Arrow table → Open-FDD rule → fake sink."""

from __future__ import annotations

import pyarrow as pa
import pyarrow.compute as pc

from open_fdd.arrow_runtime import run_arrow_rule

from fake_fault_sink import write_fault_events
from fake_iot_source import iter_rows

RULE = '''
import pyarrow.compute as pc

def apply_faults_arrow(table, cfg, context=None):
    return pc.greater(table["SAT"], float(cfg["high"]))
'''


def main() -> None:
    rows = list(iter_rows("demo-site", 40))
    table = pa.Table.from_pylist(rows)
    result = run_arrow_rule(RULE, table, {"high": 58.0})
    events = [
        {
            "site_id": rows[i]["site_id"],
            "timestamp": rows[i]["timestamp"],
            "fault": "high_sat",
            "value": rows[i]["SAT"],
        }
        for i in range(table.num_rows)
        if result.fault_mask[i].as_py()
    ]
    write_fault_events(events)
    print("flagged", len(events), "of", table.num_rows)


if __name__ == "__main__":
    main()
