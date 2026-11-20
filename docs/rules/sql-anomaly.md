---
title: SQL anomaly screen
parent: Rules
nav_order: 3.6
---

# SQL anomaly screen

A rolling z-score over each point's samples, in portable SQL (PostgreSQL / TimescaleDB, DuckDB, SQLite). It matches
the pandas detector `rolling_zscore_flags` exactly; parity tests run on all three engines. It flags unusual values;
it is not a fault rule.

```python
from open_fdd.analytics.sql_anomaly import run_zscore_sql
from open_fdd.analytics.sql_point_stats import run_anomaly_coverage_sql

flags = run_zscore_sql(conn, "duckdb", window=24, threshold=3.0)
gaps = run_anomaly_coverage_sql(conn, "duckdb", window=24)
```

| Query | Code | Output |
|---|---|---|
| [`anomaly_zscore.sql`](https://github.com/bbartling/open-fdd/blob/master/sql/analytics/anomaly_zscore.sql) | [`sql_anomaly.py`](https://github.com/bbartling/open-fdd/blob/master/open_fdd/analytics/sql_anomaly.py) | `point_key`, `equipment_id`, `role`, `ts`, `value`, `z2`, `is_anomaly`, `is_event` per sample |
| [`anomaly_series_coverage.sql`](https://github.com/bbartling/open-fdd/blob/master/sql/analytics/anomaly_series_coverage.sql) | [`sql_point_stats.py`](https://github.com/bbartling/open-fdd/blob/master/open_fdd/analytics/sql_point_stats.py) | `n`, `var_val`, `is_short`, `is_constant` per point, empty points included |

| Behavior | Detail |
|---|---|
| Window | last `window` samples, current sample included |
| Flag | \|z\| > `threshold` (sample stddev) |
| Never flags | fewer than `window` samples, or no spread |
| Ceiling | \|z\| ≤ (n − 1) / √n: with threshold 3, a window of 10 or fewer never flags; 24 caps \|z\| at 4.69 |
| `is_event` | first flagged sample of a run |

Run the coverage query next to the screen: short, constant and empty series are listed there, not silently skipped.
Input tables are the same as in [borrowing analytics](borrowing-analytics.html).
