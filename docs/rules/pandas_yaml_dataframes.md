---
title: YAML rules → Pandas (under the hood)
parent: Fault rules for HVAC
nav_order: 4
---

# YAML rules → Pandas DataFrames (under the hood)

This note is for engineers who want to see **exactly** how Open-FDD turns **rule YAML on disk** into **pandas operations** on **time-series DataFrames**—and where Brick TTL fits in. It complements [Fault rules overview](overview) and [standalone CSV / pandas](../standalone_csv_pandas).

---

## 1. YAML never becomes “one giant DataFrame of rules”

Rule files are **configuration**, not tabular data. Open-FDD:

1. Reads each `*.yaml` in `rules_dir` with PyYAML (`yaml.safe_load`) into a **Python `dict`** per file (`open_fdd.engine.runner.load_rule` / `load_rules_from_dir`).
2. Keeps those dicts in a **`list[dict]`** inside `RuleRunner` (`RuleRunner(rules=...)` or `RuleRunner(rules_path=...)`).
3. At evaluation time, walks that list and, for each rule, computes a **boolean mask** (`pandas.Series`) aligned to the **sensor DataFrame’s index**, then writes a **new column** for the fault flag (e.g. `my_rule_flag`).

So: **rules = list of dicts in memory**; **data = one wide-ish DataFrame** of timestamps and point columns.

---

## 2. From long telemetry rows to a wide DataFrame

A common pattern (warehouse export, historian CSV, SQL query) is a **long** table (`timestamp`, `point_id`, `value`). For **`RuleRunner`** you typically:

1. Load rows into pandas.
2. **Pivot to wide**: `df.pivot_table(index="timestamp", columns="point_id", values="value")` (or equivalent) so each sensor is a column.
3. **Rename columns** using **`column_map`** (dict or manifest) so rule inputs line up with Brick-style or logical keys.
4. Parse the index with **`pd.to_datetime`** when you need time-based checks.

pandas handles aggregation during the pivot when duplicate index/column pairs exist; the result is one row per timestamp.

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

- **`column_map` resolution**: For each logical input key, the runner picks a **DataFrame column name**. If the YAML input has a **`brick`** class, the supplied **`column_map`** dict is consulted (`brick` class key → column label), so the **same YAML** can run against different exports as long as the map matches your frame.
- **Bounds / thresholds**: Typical pattern is `(series < low) | (series > high)` using **vectorized** comparisons — these are **numpy ufuncs** under pandas, no Python `for` over rows.
- **Expressions**: String expressions may be evaluated in a **restricted eval** context (`open_fdd.engine.checks.check_expression`) with named series bound to `result[col]` — still vectorized.

If a required column is missing, the runner either **raises** or **skips** the rule (`skip_missing_columns=True`), depending on the call site.

---

## 5. Reloading rules vs DataFrame lifetime

If you call **`load_rules_from_dir`** before each **`RuleRunner`** construction, edits to YAML on disk take effect on the **next** run. The **DataFrame** you pass in exists only for that evaluation; construct a fresh frame for each batch or window as your pipeline requires.

---

## 6. Mental model checklist

| Artifact | In-memory shape | pandas role |
|----------|------------------|-------------|
| Rule YAML files | N/A (on disk) | None until loaded |
| Loaded rules | `list[dict]` | None |
| Telemetry window | `DataFrame` (time × points) | pivot, datetime index, column rename |
| Rule output | Same index, +flag columns | vectorized masks, optional `rolling` |
| Downstream store | Your app persists outputs if needed | After flags are computed |

For a **minimal** example of rules + CSV (no DB), see [standalone CSV / pandas](../standalone_csv_pandas) and unit tests in `open_fdd/tests/engine/test_runner.py`.
