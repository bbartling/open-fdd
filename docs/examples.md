---
title: Examples
nav_order: 6
---

# Examples

## 1. Minimal (in-memory)

```python
import pandas as pd
from open_fdd import RuleRunner

df = pd.DataFrame({
    "timestamp": pd.date_range("2024-01-01", periods=100, freq="15min"),
    "sat": [55.0] * 100,
    "mat": [60.0] * 100,
    "oat": [45.0] * 100,
    "rat": [70.0] * 100,
})

runner = RuleRunner("open_fdd/rules")
result = runner.run(df, timestamp_col="timestamp", skip_missing_columns=True)

print("bad_sensor_flag:", result["bad_sensor_flag"].sum())
print("flatline_flag:", result["flatline_flag"].sum())
```

## 2. AHU7 CSV with manual column mapping

```python
import pandas as pd
from pathlib import Path

import open_fdd
from open_fdd import RuleRunner

csv_path = Path("examples/ahu7_sample.csv")
df = pd.read_csv(csv_path)
df["timestamp"] = pd.to_datetime(df["timestamp"])

rename = {
    "SAT (°F)": "sat",
    "MAT (°F)": "mat",
    "OAT (°F)": "oat",
    "RAT (°F)": "rat",
}
df = df.rename(columns=rename)

rules_dir = Path(open_fdd.__file__).parent / "rules"
runner = RuleRunner(rules_path=rules_dir)
runner._rules = [
    r for r in runner._rules
    if r.get("name") in ("bad_sensor_check", "sensor_flatline")
]

result = runner.run(
    df, timestamp_col="timestamp",
    params={"units": "imperial"},
    skip_missing_columns=True,
)
print("Bounds:", result["bad_sensor_flag"].sum())
print("Flatline:", result["flatline_flag"].sum())
```

## 3. AHU7 with BRICK-driven column mapping

```python
import pandas as pd
from pathlib import Path
import sys

import open_fdd
from open_fdd import RuleRunner

script_dir = Path(__file__).parent
ttl_path = script_dir / "ahu7_brick_model.ttl"
csv_path = script_dir / "ahu7_sample.csv"

df = pd.read_csv(csv_path)
df["timestamp"] = pd.to_datetime(df["timestamp"])

sys.path.insert(0, str(script_dir))
from brick_resolver import resolve_from_ttl

column_map = resolve_from_ttl(ttl_path)

rules_dir = Path(open_fdd.__file__).parent / "rules"
runner = RuleRunner(rules_path=rules_dir)
runner._rules = [
    r for r in runner._rules
    if r.get("name") in ("bad_sensor_check", "sensor_flatline")
]

result = runner.run(
    df,
    timestamp_col="timestamp",
    params={"units": "imperial"},
    skip_missing_columns=True,
    column_map=column_map,
)
print("Bounds:", result["bad_sensor_flag"].sum())
print("Flatline:", result["flatline_flag"].sum())
```

## 4. With fault analytics

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
df_result = runner.run(df, rolling_window=3)

summary = summarize_fault(df_result, "fc1_flag", motor_col="supply_vfd_speed")
print_summary(summary, "FC1 Low Duct Static")
```

## Units

For sensor bounds, pass `params={"units": "metric"}` for °C. Your DataFrame must already be in that unit — no auto-conversion.
