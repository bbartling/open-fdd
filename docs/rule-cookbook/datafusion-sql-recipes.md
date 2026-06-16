---
title: DataFusion SQL rule recipes
nav_order: 3
---

# DataFusion SQL recipes

Use when you need simple threshold, `CASE WHEN`, or SQL-readable **stateless** rules. Requires `pip install 'open-fdd[datafusion]'` (optional extra in `pyproject.toml`). SQL runs **server-side only**.

**Not for:** rolling windows, PID hunting, flatline detection, schedule logic, or ML prep — use [PyArrow recipes](python-recipes-arrow.md). See [decision table]({{ "/rule-cookbook/expression-cookbook/" | relative_url }}#pyarrow-vs-datafusion-sql).

## Temperature high

```sql
SELECT
  *,
  "duct-t" > 80.0 AS fault
FROM telemetry
```

Quote hyphenated historian columns.

## Humidity high

```sql
SELECT
  *,
  "oa-h" > 70.0 AS fault
FROM telemetry
```

## Occupied + temperature

```sql
SELECT
  *,
  CASE
    WHEN occupied = true AND "stat_zn-t" > 76.0 THEN true
    ELSE false
  END AS fault
FROM telemetry
```

## With fault confirmation

Add to rule `config`:

```json
{"min_true_rows": 5, "poll_interval_s": 60}
```

PyArrow remains better for rolling windows, custom helpers, and ML prep. See [PyArrow recipes](python-recipes-arrow.md).
