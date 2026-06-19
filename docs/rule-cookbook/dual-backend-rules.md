---
title: PyArrow & DataFusion SQL rules
parent: Rule Cookbook
nav_order: 1
---

# PyArrow & DataFusion SQL rules

Open-FDD evaluates faults on a **single PyArrow historian table** (`telemetry`). You author rules in **one of two backends**:

| Backend | Rule Lab field | Best for |
|---------|----------------|----------|
| **PyArrow** | `apply_faults_arrow(table, cfg, context)` | Rolling windows, flatline, rate-of-change, hunting, schedule gates, multi-column HVAC logic |
| **DataFusion SQL** | `backend: datafusion_sql` + `sql:` | Simple thresholds, spreads, boolean `CASE WHEN`, SQL-readable rules for operators |

Both backends share the same **confirmation window** (`min_true_rows`, `poll_interval_s`, `min_elapsed_minutes`) and produce the same boolean fault mask for batch FDD.

Install SQL support (optional):

```bash
pip install 'open-fdd[datafusion]'
```

---

## Mini tutorial — same rule, both backends

**Goal:** Flag when outside-air temperature (`oa-t`) is above **85 °F**.

Historian column: `oa-t` (from BRICK `fdd_input` / point binding). Poll interval: **60 s**. Confirmation: **5 consecutive true rows** (~5 minutes).

### PyArrow

Save in Rule Lab or `workspace/data/rules_py/oa_t_high.py`:

```python
import pyarrow.compute as pc


def apply_faults_arrow(table, cfg, context=None):
    col = str((cfg or {}).get("value_column") or "oa-t")
    high = float((cfg or {}).get("high", 85.0))
    vals = pc.cast(table[col], "float64")
    return pc.greater(vals, high)
```

Rule metadata:

```json
{
  "id": "oa-t-high-arrow",
  "backend": "arrow",
  "config": { "high": 85.0, "value_column": "oa-t" },
  "fault_code": "BLD-B"
}
```

### DataFusion SQL

Same logic as SQL — register with `backend: datafusion_sql`:

```sql
SELECT
  *,
  "oa-t" > 85.0 AS fault
FROM telemetry
```

Rule metadata:

```json
{
  "id": "oa-t-high-sql",
  "backend": "datafusion_sql",
  "fault_column": "fault",
  "sql": "SELECT *, \"oa-t\" > 85.0 AS fault FROM telemetry"
}
```

### Prove parity

In **Rule Lab → Compare backends**, run the PyArrow and SQL rules on the same lookback window. Masks must match row-for-row (see bench rules `bench-oa-temp-high-arrow` / `bench-oa-temp-high-sql`).

CLI / CI:

```bash
pytest open_fdd/tests/validation/test_datafusion_arrow_parity.py -q
```

---

## When to use which backend

### Prefer **DataFusion SQL**

- One or two column comparisons (`>`, `<`, `BETWEEN`, `ABS(a - b)`)
- Operator-facing rules that should read like SQL
- Stateless row-wise logic (no rolling window)
- Proving a rule before a future Rust port

### Prefer **PyArrow**

- Rolling min/max/sum, flatline detection, rate-of-change
- PID hunting / excessive command reversals
- Schedule or occupancy gating combined with sensor logic
- Reuse of cookbook helpers (`sensor_bounds_mask`, `arrow_rolling_min`, etc.)
- Anything not expressible in a single `SELECT … FROM telemetry`

### Do not use SQL for

- Rolling windows, hunting detectors, file I/O, joins to external tables, or ML features — use PyArrow modules instead.

SQL is linted server-side: single statement, `FROM telemetry` only, boolean `fault` column required. See [Arrow rule contract]({{ "/rule-authoring/arrow-rule-contract/" | relative_url }}).

---

## Workflow

1. Bind points in **Model** → assign rule in **Rule Lab**.
2. Set `fault_code` from [Fault codes]({{ "/fault-codes/" | relative_url }}).
3. Configure confirmation in rule `config` — [Fault confirmation]({{ "/rule-cookbook/fault-confirmation/" | relative_url }}).
4. Run `POST /api/rules/batch` or wait for the scheduled FDD loop.
5. View results on the dashboard or in `fdd_results.json`.

---

## More recipes

| Topic | Page |
|-------|------|
| Full Arrow helper library | [Python recipes (Arrow)]({{ "/rule-cookbook/python-recipes-arrow/" | relative_url }}) |
| Additional SQL patterns | [DataFusion SQL recipes]({{ "/rule-cookbook/datafusion-sql-recipes/" | relative_url }}) |
| GL36 / AHU patterns | [GL36 & sensor patterns]({{ "/rule-cookbook/expression-cookbook/" | relative_url }}) |
| Contract & types | [Rule authoring]({{ "/rule-authoring/" | relative_url }}) |
