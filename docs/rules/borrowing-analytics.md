---
title: Using the SQL analytics in your own database
parent: Rules
nav_order: 3.5
---

# Using the SQL analytics in your own database

The Open-FDD analytics behind the RCx charts are plain SQL files in [`sql/analytics/`](https://github.com/bbartling/open-fdd/tree/master/sql/analytics). They run on PostgreSQL / TimescaleDB, DuckDB and SQLite 3.28+, with no extensions. Each one has a pandas twin, and tests check that both give the same answer on all three engines. The license is MIT: copy them into your own historian or warehouse.

| File | Answers | Pandas twin |
|---|---|---|
| `motor_weekly_runtime.sql` | Run hours per motor per week, average OAT while running, in-schedule and after-hours split | `open_fdd.analytics.core.motor_run_hours_weekly` |
| `mech_cooling_oat_bins.sql` | Mechanical-cooling hours per outdoor-air bin (six fixed bins, °C) | `open_fdd.analytics.core.mech_cooling_oat_bins` |
| `economizer_metrics.sql` | Fan-on samples, identifiable samples, median and MAE of the mixed-air residual | `open_fdd.analytics.core.economizer_free_cooling_diagnostics` |
| `bas_vs_web_oat.sql` | BAS outdoor-air sensor vs a weather service: bias, MAE, max \|delta\|, share within ±2 °C | `open_fdd.analytics.weather_resolver.bas_vs_web_oat_stats` |
| `anomaly_zscore.sql` | Rolling z-score anomaly flags per point | `open_fdd.analytics.anomaly.detectors.rolling_zscore_flags` |

## What your database needs

Two tables in a schema named `fdd`. These are the only columns the analytics read:

| Table | Columns |
|---|---|
| `fdd.point` | `site_id`, `point_key`, `equipment_id`, `role` |
| `fdd.input_sample` | `site_id`, `point_key`, `ts`, `value` (a view is fine) |

- `ts` is `timestamptz` (PostgreSQL), `timestamp` in UTC (DuckDB) or integer UTC epoch milliseconds (SQLite).
- Values are SI: °C, Δ°C, percent 0-100 or fraction 0-1 for commands and dampers, 0/1 for statuses.
- `role` comes from your point tagging, never from point names. Weekly runtime and the z-score read it (the motor roles are listed in the header of `motor_weekly_runtime.sql`). The economizer, cooling-bin and BAS-vs-web queries take the point keys you pass instead, as a small inline table.

On an Open-FDD TimescaleDB these already exist (`sql/fdd/schema/core.sql`). Anywhere else, `open_fdd.analytics.sql_anomaly.create_core` creates a minimal copy, and `load_core` fills it.

## Quick start (no server)

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

SQLite and DuckDB print the same numbers. Needs `pip install open-fdd` (plus `duckdb` for DuckDB).

## Plain SQL, no Python at run time

Each file has `{placeholders}`: the site, the window, a small inline table of your points, and the engine's timestamp-to-milliseconds expression. Render a file once for your engine and keep the result. Every value is checked and quoted, so no caller string reaches the SQL unquoted:

```python
from open_fdd.analytics.sql_runtime import render_runtime_sql
open("weekly_runtime.sql", "w").write(render_runtime_sql("postgres", site_id="my-site", oats=[("AHU-1", "ahu1/oat")]))
```

Then run `weekly_runtime.sql` from `psql`, a dashboard tool or a scheduled job. Re-render it when the point list changes. The renderers are `render_runtime_sql`, `render_mech_bins_sql`, `render_economizer_sql`, `render_bas_web_sql` and `render_zscore_sql`, in the matching `open_fdd.analytics.sql_*` modules.

## Definitions worth knowing

| Rule | Meaning |
|---|---|
| On | Value above 5 % after scaling to 0-1 (a value above 1.5 is read as percent). The whole interval counts. |
| Interval | Each sample owns the time to its point's next sample. An interval over 1 h is unknown and counts 0 h. |
| Weeks | UTC Mondays by default. Pass your own week starts (site time zone) and occupied intervals for the schedule split. Weeks with no run time have no row. |
| Weather | Outdoor air is joined as-of: the latest reading at or before the sample, within an age limit. |
| Economizer | Identifiable when \|OAT - RAT\| ≥ 50/9 Δ°C (10 Δ°F). The residual is MAT - (RAT + damper × (OAT - RAT)). |

## Checking your port

Load the same samples into your database and into pandas, then compare. `tests/test_sql_*.py` in the repository do exactly this for each analytic, and `tests/fixtures/sql_analytics_cases.json` holds small generated cases with their pandas answers. If your numbers drift, first check the units (SI), the time zone (UTC timestamps), and duplicate timestamps. This is the same list as for the [SQL rules](borrowing-sql.html#if-the-numbers-do-not-match-pandas).
