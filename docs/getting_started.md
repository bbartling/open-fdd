---
title: Getting Started
nav_order: 2
---

# Getting Started

The simplest way to run open-fdd: in-memory DataFrame, no CSV, no Brick. All code below — copy and run.

## 1. Install

```bash
pip install open-fdd
```

Or from source:

```bash
git clone https://github.com/bbartling/open-fdd.git && cd open-fdd
pip install -e ".[dev]"
```

## 2. Minimal example (all code)

```python
import pandas as pd
from open_fdd import RuleRunner

# In-memory AHU-style data
df = pd.DataFrame({
    "timestamp": pd.date_range("2024-01-01", periods=100, freq="15min"),
    "sat": [55.0] * 100,      # flatline — sensor stuck
    "mat": [60.0] * 100,
    "oat": [45.0] * 100,
    "rat": [70.0] * 100,
})

# Load rules from package
runner = RuleRunner("open_fdd/rules")

# Run (sensor checks: bounds + flatline)
result = runner.run(df, timestamp_col="timestamp", skip_missing_columns=True)

# Fault counts
print("bad_sensor_flag:", result["bad_sensor_flag"].sum())
print("flatline_flag:", result["flatline_flag"].sum())
```

## 3. With fault analytics

```python
import pandas as pd
from open_fdd import RuleRunner
from open_fdd.reports import summarize_fault, print_summary

df = pd.DataFrame({
    "timestamp": pd.date_range("2023-01-01", periods=20, freq="15min"),
    "duct_static": [0.4, 0.35, 0.3, 0.25, 0.2] * 4,
    "duct_static_setpoint": [0.5] * 20,
    "supply_vfd_speed": [0.95, 0.96, 0.97, 0.98, 0.99] * 4,
    "mat": [60] * 20,
    "rat": [72] * 20,
})

runner = RuleRunner("open_fdd/rules")
# rolling_window=3: fault only when condition holds for 3+ consecutive samples (reduces noise)
df_result = runner.run(df, rolling_window=3)

# Analytics for FC1 (low duct static at max fan)
summary = summarize_fault(df_result, "fc1_flag", motor_col="supply_vfd_speed")
print_summary(summary, "FC1 Low Duct Static")
```

## 4. Next step

→ **[Data Model & Brick](data_model.md)** — Use a Brick TTL and `brick_resolver` to map rule inputs from your BAS/BMS schema.
