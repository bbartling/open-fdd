---
title: YAML rules → Pandas (under the hood)
parent: Fault rules for HVAC
nav_order: 4
---

# YAML rules → Pandas DataFrames (under the hood)

This note is for engineers who want to see **exactly** how Open-FDD turns **rule YAML on disk** into **pandas operations** on **time-series DataFrames**—and where Brick TTL fits in. It complements [Fault rules overview](overview), [Getting started](../getting_started), and [Examples](../examples).

---

## 1. YAML never becomes “one giant DataFrame of rules”

Rule files are **configuration**, not tabular data. Open-FDD:

1. Reads each `*.yaml` in `rules_dir` with PyYAML (`yaml.safe_load`) into a **Python `dict`** per file (`open_fdd.engine.runner.load_rule` / `load_rules_from_dir`).
2. Keeps those dicts in a **`list[dict]`** inside `RuleRunner` (`RuleRunner(rules=...)` or `RuleRunner(rules_path=...)`).
3. At evaluation time, walks that list and, for each rule, computes a **boolean mask** (`pandas.Series`) aligned to the **sensor DataFrame’s index**, then writes a **new column** for the fault flag (e.g. `my_rule_flag`).

So: **rules = list of dicts in memory**; **data = one wide-ish DataFrame** of timestamps and point columns.

---

## 2. From Postgres rows to a site/equipment DataFrame

The continuous loop (`openfdd_stack.platform.loop.run_fdd_loop`) loads telemetry with SQL, then reshapes it for pandas:

1. **Query** `timeseries_readings` joined to `points` for the time window (`load_timeseries_for_site` / `load_timeseries_for_equipment`).
2. **Build a long table**: `pd.DataFrame(rows)` with columns like `ts`, `external_id`, `value`.
3. **Pivot to wide**: `df.pivot_table(index="ts", columns="external_id", values="value")` so each point is a column (one column per `external_id`).
4. **Rename columns** using a **column map**: logical keys (often Brick class names) → your frame’s column names. On the AFDD stack, that map is built from TTL; with **`pip install open-fdd`** alone, use a dict or **`load_column_map_manifest`**.
5. **Add** `timestamp = pd.to_datetime(df["ts"])` for time-based checks.

Under the hood, pandas is doing **grouped aggregation in the pivot** (duplicate `(ts, external_id)` would aggregate), then **aligning** all series to a common `DatetimeIndex` (implicit via the pivot index).

---

## 3. What `RuleRunner.run` does to that DataFrame

`RuleRunner.run` (`open_fdd.engine.runner`):

1. **`result = df.copy()`** — rules never mutate the caller’s frame in place (callers can still hold a reference to the original).
2. For **each** rule dict:
   - Derives **`flag_name`** from `flag` or `{name}_flag`.
   - Calls **`_evaluate_rule`** → returns a **boolean `Series`** (fault mask) aligned to `result.index`.
   - Optionally applies a **rolling window** on the mask: `mask.astype(int).rolling(window=rw).sum() >= rw` so a fault must persist for N consecutive samples.
   - Assigns **`result[flag_name] = ...`** as integer 0/1.

So each rule adds **one column** of flags; the frame grows **width-wise**, not row-wise.

---

## 4. How a YAML rule dict becomes pandas expressions

Inside `_evaluate_rule`, Open-FDD branches on `rule["type"]` (e.g. `bounds`, `flatline`, `expression`, …):

- **`column_map` resolution**: For each logical input key, the runner picks a **DataFrame column name**. If the YAML input has a **`brick`** class, the global `column_map` from TTL is consulted first (`brick` → column label), so the **same YAML** can run against different exports as long as TTL maps Brick classes to the right columns.
- **Bounds / thresholds**: Typical pattern is `(series < low) | (series > high)` using **vectorized** comparisons — these are **numpy ufuncs** under pandas, no Python `for` over rows.
- **Expressions**: String expressions may be evaluated in a **restricted eval** context (`open_fdd.engine.checks.check_expression`) with named series bound to `result[col]` — still vectorized.

If a required column is missing, the runner either **raises** or **skips** the rule (`skip_missing_columns=True`), depending on the call site.

---

## 5. Hot reload: YAML vs DataFrame lifetime

`run_fdd_loop` calls **`load_rules_from_dir(rules_path)` every run**, then filters by equipment types from TTL, then **`RuleRunner(rules=rules)`**. There is **no** long-lived compiled rule object on disk—editing YAML affects the **next** scheduled run (or the next manual `POST /run-fdd`). The **DataFrame** exists only for the duration of that run’s Python call stack (load → run → persist results).

---

## 6. Mental model checklist

| Artifact | In-memory shape | pandas role |
|----------|------------------|-------------|
| Rule YAML files | N/A (on disk) | None until loaded |
| Loaded rules | `list[dict]` | None |
| Telemetry window | `DataFrame` (time × points) | pivot, datetime index, column rename |
| Rule output | Same index, +flag columns | vectorized masks, optional `rolling` |
| `fault_results` / DB | Written from row-wise `FDDResult` | After flags are computed |

For a **minimal** library-side example, use **`pd.read_csv`** + **`RuleRunner`** as in [Getting started](../getting_started); sample CSVs and notebooks live under **[`examples/AHU/`](https://github.com/bbartling/open-fdd/tree/master/examples/AHU)**. Unit tests: [`open_fdd/tests/engine/test_runner.py`](https://github.com/bbartling/open-fdd/blob/master/open_fdd/tests/engine/test_runner.py).
