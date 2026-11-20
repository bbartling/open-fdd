---
title: Using the SQL analytics in your own database
parent: Rules
nav_order: 3.5
---

# Using the SQL analytics in your own database

The RCx analytics in [`sql/analytics/`](https://github.com/bbartling/open-fdd/tree/master/sql/analytics) run on PostgreSQL / TimescaleDB, DuckDB and SQLite 3.28+. Tests check each one against its pandas twin on all three. MIT licensed.

| File | Answers |
|---|---|
| `motor_weekly_runtime.sql` | Run hours per motor per week, OAT while running, in-schedule / after-hours |
| `mech_cooling_oat_bins.sql` | Cooling hours per outdoor-air bin |
| `economizer_metrics.sql` | Identifiable samples, median and MAE of the mixed-air residual |
| `bas_vs_web_oat.sql` | BAS outdoor-air sensor vs weather service: bias, MAE, share within ±2 °C |
| `anomaly_zscore.sql` | Rolling z-score flags per point |
| `sensor_stats.sql` | Count, min, max, mean, sample stddev, first / last time per point |
| `diurnal_hourly.sql` | Mean by UTC hour of day per point |
| `setpoints_latest.sql` | Latest value of each setpoint point |

## Input

| Table | Columns |
|---|---|
| `fdd.point` | `site_id`, `point_key`, `equipment_id`, `role` |
| `fdd.input_sample` | `site_id`, `point_key`, `ts` (UTC), `value` (SI) |

An Open-FDD TimescaleDB already has both. Elsewhere, `create_core` and `load_core` in `open_fdd.analytics.sql_anomaly` make them.

## Quick start

```python
import math, sqlite3
from open_fdd.analytics.sql_anomaly import create_core, load_core
from open_fdd.analytics.sql_bas_web import run_bas_web_sql
from open_fdd.analytics.sql_economizer import run_economizer_sql
from open_fdd.analytics.sql_mech_cooling import build_plan, run_mech_bins_sql
from open_fdd.analytics.sql_runtime import run_runtime_sql

# One AHU plus a web outdoor-air point: 7 days every 5 minutes, SI, UTC epoch ms.
T0, STEP = 1_772_409_600_000, 300_000                              # 2026-03-02 00:00 UTC, a Monday
points = [{"site_id": "local", "point_key": k, "equipment_id": eq, "role": r} for k, eq, r in [
    ("ahu1/fan", "AHU-1", "fan_status"), ("ahu1/oat", "AHU-1", "oa_t"), ("ahu1/rat", "AHU-1", "rat"),
    ("ahu1/mat", "AHU-1", "mat"), ("ahu1/dmp", "AHU-1", "oa_damper_pct"), ("ahu1/comp", "AHU-1", "compressor_status"),
    ("web/oat", None, "web_oa_t")]]
samples = []
for i in range(7 * 288):
    t, hour = T0 + i * STEP, (i % 288) / 12
    oat = 12 + 10 * math.sin((hour - 9) / 24 * 2 * math.pi)
    on, dmp = (1.0 if 6 <= hour < 18 else 0.0), (80.0 if oat < 18 else 20.0)
    samples += [("local", "ahu1/fan", t, on), ("local", "ahu1/oat", t, oat), ("local", "ahu1/rat", t, 22.0),
                ("local", "ahu1/mat", t, 22 + dmp / 100 * (oat - 22)), ("local", "ahu1/dmp", t, dmp),
                ("local", "ahu1/comp", t, 1.0 if on and oat > 18 else 0.0)]
    if i % 12 == 0:
        samples.append(("local", "web/oat", t, oat - 0.8))       # hourly, 0.8 °C cooler

conn = sqlite3.connect(":memory:")            # DuckDB: conn = duckdb.connect() and engine "duckdb"
create_core(conn, "sqlite")
load_core(conn, "sqlite", points, samples)

print(run_runtime_sql(conn, "sqlite", oats=[("AHU-1", "ahu1/oat")])[0]["run_hours"])          # 84.0
econ = run_economizer_sql(conn, "sqlite", [("AHU-1", "fan", "ahu1/fan"), ("AHU-1", "oat", "ahu1/oat"),
    ("AHU-1", "rat", "ahu1/rat"), ("AHU-1", "mat", "ahu1/mat"), ("AHU-1", "damper", "ahu1/dmp")])
print(econ[0]["n_identifiable"], econ[0]["median_resid"])                                   # 406 0.0
plan = build_plan([("AHU-1", "AHU", {"compressor-status": "ahu1/comp", "outside-air-temp": "ahu1/oat"})])
print([(b["bin_label"], b["on_ms"] / 3.6e6) for b in run_mech_bins_sql(conn, "sqlite", plan)])  # [('16-21', 22.75), ('21-27', 22.75)]
print(round(run_bas_web_sql(conn, "sqlite", [("AHU-1", "ahu1/oat", "web/oat", 5_400_000)])[0]["bias"], 3))  # 0.8
```

## Plain SQL

Render a file once for your engine, then run it from `psql` or any scheduler. Re-render when the points change.

```python
from open_fdd.analytics.sql_runtime import render_runtime_sql
open("weekly_runtime.sql", "w").write(render_runtime_sql("postgres", site_id="my-site", oats=[("AHU-1", "ahu1/oat")]))
```

Each `.sql` file's header lists its roles, placeholders and exact semantics.

## If the numbers differ

Check SI units, UTC timestamps and duplicate timestamps first, as for the [SQL rules](borrowing-sql.html#if-the-numbers-do-not-match-pandas). `tests/test_sql_*.py` show the pandas comparison for each file.
