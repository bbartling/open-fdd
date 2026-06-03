---
title: Expression cookbook (YAML / pandas)
parent: Expression rule cookbooks
nav_order: 2
---

# Expression cookbook — YAML / pandas

For **`pip install open-fdd`** and offline CSV work. Rules are YAML evaluated by **`RuleRunner`** on a pandas `DataFrame`. Not used by the edge scheduled loop (see [Python cookbook](expression_rule_cookbook_python)).

---

## Minimal expression rule

```yaml
name: high_sat
type: expression
flag: high_sat_flag

inputs:
  sat:
    brick: Supply_Air_Temperature_Sensor

params:
  max_temp: 90.0

expression: |
  sat > max_temp
```

```python
from open_fdd.engine import RuleRunner
runner = RuleRunner(rules_path="my_rules/")
df_out = runner.run(df, column_map={"Supply_Air_Temperature_Sensor": "SAT"})
```

**`column_map`:** maps logical / Brick keys to DataFrame columns. Optional `brick:`, `haystack:`, `dbo:`, `s223:`, `223p:` on inputs — first match wins. See [Column map resolvers](column_map_resolvers).

## Ontology labels (optional) {#ontology-labels}

Brick/Haystack/DBO/223P keys on `inputs` are optional; plain logical names work.

---

## Schedule + weather gates {#occupied-hours-and-weather-gating-expressions}

```yaml
params:
  schedule:
    weekdays: [0, 1, 2, 3, 4]
    start_hour: 8
    end_hour: 17
  weather_band:
    oat_input: Outside_Air_Temperature_Sensor
    units: imperial
    low: 32
    high: 85

expression: |
  fan_on & ~schedule_occupied & weather_allows_fdd
```

Injects `schedule_occupied` and `weather_allows_fdd` booleans into expression scope.

---

## Signal scaling (0–1 vs 0–100 %) {#signal-scaling-0--1-fraction-vs-0--100-percent}

BACnet often exposes 0–100. Expression rules do **not** auto-scale (unlike `hunting` / `oa_fraction`).

Use injected **`normalize_cmd(series)`** (open-fdd 2.3+):

```yaml
expression: |
  (normalize_cmd(Supply_Fan_Speed_Command) >= drv_hi_frac - drv_near_hi)
```

Or explicit: `np.where(cmd > 1, cmd / 100.0, cmd)`.

---

## GL36-style example — duct static low at full fan

```yaml
name: duct_static_low_at_full_speed
type: expression
flag: rule_a_flag

inputs:
  Supply_Air_Static_Pressure_Sensor:
    brick: Supply_Air_Static_Pressure_Sensor
  Supply_Air_Static_Pressure_Setpoint:
    brick: Supply_Air_Static_Pressure_Setpoint
  Supply_Fan_Speed_Command:
    brick: Supply_Fan_Speed_Command

params:
  sp_margin: 0.12
  drv_hi_frac: 0.93
  drv_near_hi: 0.06

expression: |
  (Supply_Air_Static_Pressure_Sensor < Supply_Air_Static_Pressure_Setpoint - sp_margin) & (normalize_cmd(Supply_Fan_Speed_Command) >= drv_hi_frac - drv_near_hi)
```

More recipes (blend air bands, ERV, hunting): `examples/AHU/rules/`, [Test bench catalog](rules/test_bench_rule_catalog).

---

## Built-in types (non-expression)

| `type` | Purpose |
|--------|---------|
| `bounds` | Outside `[low, high]` |
| `flatline` | Rolling spread &lt; tolerance |
| `hunting` | Excessive toggling |
| `oa_fraction` | OA fraction error |
| `erv_efficiency` | ERV effectiveness |

Details: [Rules overview](rules/overview).

---

## Validation (2.3+)

`RuleRunner.run(..., input_validation='strict')` fails fast on bad column maps. Production often uses `skip_missing_columns=True` with warnings.

---

## Porting YAML → edge Python

When a rule graduates to production, reimplement window logic against feather **rows** in Rule Lab; bind via BRICK model. Keep YAML in repo for regression tests (`pytest open_fdd/tests/engine`).
