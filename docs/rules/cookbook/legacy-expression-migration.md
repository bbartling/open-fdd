---
title: Legacy expression migration
parent: Rule Cookbook
nav_order: 9
---

# Legacy YAML expression → SQL / Pandas

Open-FDD **3.2+ Rust edge** uses **DataFusion SQL** only. Pre-3.2 sites used **YAML expression rules** with NumPy (`np.maximum`, rolling windows, Brick class inputs). This guide maps the old pattern to the new cookbooks.

## Concept mapping

| Legacy (YAML expression) | Open-FDD edge (SQL) | Off-edge (Pandas) |
|--------------------------|---------------------|-------------------|
| `inputs.brick: Supply_Air_Temperature_Sensor` | Haystack assignment → `sat` column in `telemetry_pivot` | DataFrame column from CSV export |
| `params.err_thresh: 5.0` | SQL literal or `CASE` threshold | Python variable / `.assign()` |
| `expression: SAT > max_temp` | `CASE WHEN sat > 90 THEN true … END AS fault_raw` | `df['fault_raw'] = df['sat'] > 90` |
| `&` / `\|` / `~` | `AND` / `OR` / `NOT` | `&` / `\|` / `~` |
| `.rolling(12).std()` | Limited in SQL — use confirmation or Pandas | `df['sat'].rolling(12).std()` |
| `confirmation` in rule YAML | `confirmation_seconds` in API / UI | Manual rolling min duration |

## Example: Rule A (duct static low at full fan)

**Legacy YAML:**

```yaml
expression: |
  (Supply_Air_Static_Pressure_Sensor < Supply_Air_Static_Pressure_Setpoint - sp_margin)
  & (Supply_Fan_Speed_Command >= drv_hi_frac - drv_near_hi)
```

**DataFusion SQL:** [§4 in SQL cookbook](datafusion-sql-cookbook.html#4-duct-static-low-at-full-fan-gl36-rule-a)

**Pandas:** [§3 in Pandas cookbook](pandas-cookbook.html)

## Example: mixing envelope (Rules B/C)

Legacy used `np.minimum` / `np.maximum` on OAT/RAT/MAT. SQL uses `LEAST` / `GREATEST`; Pandas uses `np.minimum` / `np.maximum` — same physics.

## Brick / Haystack binding

Legacy rules never named BACnet columns — Brick TTL resolved timeseries IDs. On the Rust edge:

1. Assign driver points → Haystack model points → **FDD inputs** (`/api/model/assignments`)
2. Historian pivot exposes semantic names (`oa_t`, `sat`, …)
3. SQL references those names only

See [Haystack → SQL columns](haystack-assignments.html).

## What moved where

| Old path | New path |
|----------|----------|
| `docs/rule-cookbook/expression-cookbook.md` | [DataFusion SQL cookbook](datafusion-sql-cookbook.html) + [GL36 AHU rules](gl36-ahu-rules.html) |
| `docs/rule-cookbook/python-recipes*.md` | [Pandas cookbook](pandas-cookbook.html) |
| `docs/rule-cookbook/datafusion-sql-recipes.md` | [DataFusion SQL cookbook](datafusion-sql-cookbook.html) |
| `docs/expression_rule_cookbook.md` | This page + cookbooks above |
| PyArrow `apply_faults_arrow` | SQL `fault_raw` + API confirmation |

## Rolling / hunting rules

Expression rules with `.rolling().std()` or PID hunting detection are **best in Pandas** off-edge. On the edge, approximate with:

- Higher `confirmation_seconds` (debounce)
- Simpler threshold rules + sensor validation ([sensor validation](sensor-validation.html))

Full hunting patterns: [Pandas cookbook — oscillation](pandas-cookbook.html).
