---
title: Arrow recipes
parent: Rule Cookbook
nav_order: 2
---

# Arrow recipes (default)

Open-FDD 3.0 Rule Lab rules use **`apply_faults_arrow(table, cfg, context)`**, **`pyarrow.compute`**, and **module constants** (no `config.json`).

For **full GL36 A–M and plant recipes**, see **[Python recipes (full Arrow library)](python-recipes-arrow)**. Sensor tables: **[Expression cookbook](expression-cookbook)**.

## Simple threshold

```python
import pyarrow.compute as pc

VALUE_COLUMN = "zone_temp"
MAX_ZONE_TEMP = 78.0


def apply_faults_arrow(table, cfg, context=None):
    return pc.greater(table[VALUE_COLUMN], MAX_ZONE_TEMP)
```

## Supply air temp high

```python
import pyarrow.compute as pc

VALUE_COLUMN = "sa-t"
HIGH_F = 75.0


def apply_faults_arrow(table, cfg, context=None):
    return pc.greater(pc.cast(table[VALUE_COLUMN], "float64"), HIGH_F)
```

## Fan commanded but no airflow

```python
import pyarrow.compute as pc

FAN_CMD = "fan-cmd"
AIRFLOW = "supply-cfm"
FAN_ON = 0.5
MIN_CFM = 500.0


def apply_faults_arrow(table, cfg, context=None):
    fan_on = pc.greater(table[FAN_CMD], FAN_ON)
    low_airflow = pc.less(table[AIRFLOW], MIN_CFM)
    return pc.and_(fan_on, low_airflow)
```

## Flatline (1 h rolling window)

```python
import pyarrow.compute as pc
from open_fdd.arrow_runtime.windows import arrow_rolling_max, arrow_rolling_min

VALUE_COLUMN = "oa-t"
WINDOW_SAMPLES = 12
FLATLINE_TOLERANCE = 0.1


def apply_faults_arrow(table, cfg, context=None):
    vals = pc.cast(table[VALUE_COLUMN], "float64")
    spread = pc.subtract(arrow_rolling_max(vals, WINDOW_SAMPLES), arrow_rolling_min(vals, WINDOW_SAMPLES))
    return pc.less_equal(pc.abs(spread), FLATLINE_TOLERANCE)
```

## Sensor out of range (catalog defaults)

```python
from open_fdd.arrow_runtime.cookbook import sensor_bounds_mask

def apply_faults_arrow(table, cfg, context=None):
    return sensor_bounds_mask(table, "outdoor_air_temp", cfg)  # fault_code: BLD-B
```

## Sensor flatline + spike (catalog)

```python
from open_fdd.arrow_runtime.cookbook import sensor_flatline_mask, rate_of_change_mask
from open_fdd.arrow_runtime.sensor_catalog import cfg_from_profile

def apply_faults_arrow(table, cfg, context=None):
    merged = cfg_from_profile("zone_temp", cfg)
    merged["samples_per_hour"] = 12
    flat = sensor_flatline_mask(table, "zone_temp", cfg)
    spike = rate_of_change_mask(table, merged, col="stat_zn-t")
    return pc.or_(flat, spike)  # import pyarrow.compute as pc
```

Bounds table: [Expression cookbook — sensor validation](expression-cookbook#sensor-validation-bounds-flatline-rate-of-change).

More templates ship in `open_fdd.playground.arrow_templates` and via `GET /api/playground/arrow-templates`.

Bench examples: `workspace/data/rules_py/bench_*.py`.

Dev kit zip layout: [Rule Lab — dev kit zip](../operator-bridge/rule-lab.md#dev-kit-zip-download).
