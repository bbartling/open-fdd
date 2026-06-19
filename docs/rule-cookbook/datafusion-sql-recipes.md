---
title: DataFusion SQL recipes
parent: Rule Cookbook
nav_order: 4
---

# DataFusion SQL recipes

Additional SQL patterns beyond the [PyArrow & DataFusion tutorial]({{ "/rule-cookbook/dual-backend-rules/" | relative_url }}). Requires `pip install 'open-fdd[datafusion]'`. SQL runs **server-side only**.

**Not for:** rolling windows, PID hunting, flatline, or schedule logic — use [Python recipes (Arrow)]({{ "/rule-cookbook/python-recipes-arrow/" | relative_url }}).

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
