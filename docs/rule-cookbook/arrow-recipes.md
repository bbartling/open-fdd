---
title: Arrow recipes
parent: Rule Cookbook
nav_order: 1
---

# Arrow recipes (default)

Open-FDD 3.0 Rule Lab rules use **`apply_faults_arrow(table, cfg, context)`** and **`pyarrow.compute`**.

## Simple threshold

```python
import pyarrow.compute as pc

def apply_faults_arrow(table, cfg, context=None):
    return pc.greater(table["zone_temp"], cfg["max_zone_temp"])
```

## Supply air temp high

```python
import pyarrow.compute as pc

def apply_faults_arrow(table, cfg, context=None):
    col = str(cfg.get("column", "SAT"))
    return pc.greater(table[col], float(cfg["high"]))
```

Config: `{"column": "SAT", "high": 75}`

## Fan commanded but no airflow

```python
import pyarrow.compute as pc

def apply_faults_arrow(table, cfg, context=None):
    fan_on = pc.greater(table["fan_cmd"], cfg.get("fan_on_threshold", 0.5))
    low_airflow = pc.less(table["airflow_cfm"], cfg["min_airflow_cfm"])
    return pc.and_(fan_on, low_airflow)
```

## Economizer not opening

```python
import pyarrow.compute as pc

def apply_faults_arrow(table, cfg, context=None):
    oat_good = pc.less(table["outside_air_temp"], cfg["economizer_oat_limit"])
    cooling = pc.greater(table["cooling_cmd"], cfg.get("cooling_threshold", 0.5))
    damper_low = pc.less(table["oa_damper_cmd"], cfg["min_oa_damper_cmd"])
    return pc.and_(pc.and_(oat_good, cooling), damper_low)
```

## Heating and cooling simultaneously

```python
import pyarrow.compute as pc

def apply_faults_arrow(table, cfg, context=None):
    heating = pc.greater(table["heat_cmd"], cfg.get("heat_threshold", 0.1))
    cooling = pc.greater(table["cool_cmd"], cfg.get("cool_threshold", 0.1))
    return pc.and_(heating, cooling)
```

## Sensor out of range

```python
import pyarrow.compute as pc

def apply_faults_arrow(table, cfg, context=None):
    too_low = pc.less(table["sensor_value"], cfg["min_value"])
    too_high = pc.greater(table["sensor_value"], cfg["max_value"])
    return pc.or_(too_low, too_high)
```

More templates ship in `open_fdd.playground.arrow_templates` and via `GET /api/playground/arrow-templates`.
