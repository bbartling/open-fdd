---
title: Arrow-native FDD runtime
parent: Developer
---

# Arrow-native FDD runtime

Open-FDD 3.x runs rule-based HVAC fault detection on an **Arrow-native columnar execution engine** by default.

```
Feather / Arrow IPC
  → Arrow Table / RecordBatch stream
  → apply_faults_arrow(table, cfg, context)
  → Boolean fault mask
  → summaries / events (JSON for UI)
```

## Rule contract

```python
import pyarrow.compute as pc

def apply_faults_arrow(table, cfg, context=None):
    return pc.greater(table["zone_temp"], cfg["max_zone_temp"])
```

Rules return a `pyarrow.BooleanArray` or `ChunkedArray` with the same row count as the input table.

## Legacy row rules

Old `evaluate(row, cfg, …)` rules are supported only when:

- the rule sets `"backend": "legacy_row"`, or
- `OPEN_FDD_FDD_BACKEND=legacy_row` is set.

The Rule Lab shows a migration message for legacy rules.

## Threading

| Variable | Purpose |
|----------|---------|
| `OPEN_FDD_ARROW_THREADS` | Arrow CPU thread pool |
| `OPEN_FDD_ARROW_IO_THREADS` | Arrow I/O threads (when supported) |
| `OPEN_FDD_ARROW_BATCH_ROWS` | RecordBatch chunk size (default 50000) |
| `OPEN_FDD_ARROW_PARALLEL_RULES` | Parallel rule batches |
| `OPEN_FDD_ARROW_PARALLEL_SITES` | Parallel site jobs |

Large jobs use Arrow projection/filtering, chunked batches, and job-level parallelism across sites/rules. Not every scalar kernel uses every core; throughput comes from batch scans plus parallel orchestration.

## Benchmarks

```bash
python benchmarks/bench_arrow_native.py --rows 10000 100000 --repeats 3 --output .bench/arrow_native.json
python benchmarks/bench_arrow_end_to_end.py --sites 1 --rows-per-site 100000 --repeats 2 --output .bench/arrow_end_to_end.json
```
